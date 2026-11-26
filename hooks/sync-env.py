#!/usr/bin/env python3
"""
SessionStart hook: make .claude/.env available to every Bash/agent/skill call.

Behavior:
- Reads .claude/.env (KEY=VALUE, ignores #comments and blanks, strips matching quotes).
- Values of the form `op://vault/item/field` are resolved via `op read` (1Password CLI),
  so no secret needs to sit in .env as plaintext. Never blocks the session: if `op` is
  missing, not signed in, or a read fails, warns on stderr and leaves the key unset.
- Every key is exported to this session's Bash calls through CLAUDE_ENV_FILE.
- Non-secret keys are also merged into settings.local.json `env` (values from .env win
  on conflict), so they apply from the next session start. Secret keys (an op://
  reference in .env, or a name like *TOKEN*, *SECRET*, *PASSWORD*, *API_KEY*) are never
  written there, and a copy synced by an earlier version is removed; MCP servers
  resolve their own secrets through tools/mcp-run.py.
- ANTHROPIC_API_KEY is the one secret written to settings.local.json: Claude Code reads
  it at startup to authenticate (from the next session start; the first session still
  uses the login). The file is then kept owner-only (0600). A placeholder, empty or
  unresolved op:// value is never written (it would break auth instead of falling back
  to the login).
- Never sets `apiKeyHelper`, and removes a `printenv ANTHROPIC_API_KEY` helper it finds:
  that helper exits 1 whenever the variable is missing from the environment Claude Code
  starts in, which fails authentication instead of falling back to the login.
- Warns on stderr if .env is missing, unparseable, or required keys are absent /
  still placeholders. Never blocks the session.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

BITBUCKET_KEYS = (
    "BITBUCKET_WORKSPACE",
    "BITBUCKET_REPO_SLUG",
    "BITBUCKET_EMAIL",
    "BITBUCKET_API_TOKEN",
)
GITHUB_KEYS = (
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "GITHUB_TOKEN",
)
AZURE_KEYS = (  # token optional: without AZURE_DEVOPS_PAT the MCP server signs in through the browser
    "AZURE_DEVOPS_ORG",
    "AZURE_DEVOPS_PROJECT",
    "AZURE_DEVOPS_REPO",
)
AZURE_URL_KEY = "AZURE_DEVOPS_URL"  # an org, project or repo URL; fills the AZURE_KEYS left unset
# Web URLs down to any level: https://dev.azure.com/<org>[/<project>[/_git[/<repo>]]],
# https://<org>.visualstudio.com[/DefaultCollection][/<project>[/_git[/<repo>]]].
AZURE_WEB_URL = (
    re.compile(r"^https?://(?:[^@/\s]+@)?dev\.azure\.com/([^/?#\s]+)(?:/([^/?#\s]+))?(?:/_git(?:/([^/?#\s]+))?)?"),
    re.compile(r"^https?://(?:[^@/\s]+@)?([^./\s]+)\.visualstudio\.com(?:/DefaultCollection)?(?:/([^/?#\s]+))?(?:/_git(?:/([^/?#\s]+))?)?"),
)
# Azure DevOps remotes: ssh.dev.azure.com:v3/<org>/<project>/<repo>,
# https://[user@]dev.azure.com/<org>/<project>/_git/<repo>,
# https://<org>.visualstudio.com/[DefaultCollection/]<project>/_git/<repo>,
# <org>@vs-ssh.visualstudio.com:v3/<org>/<project>/<repo>.
AZURE_REMOTE = (
    re.compile(r"(?:ssh\.dev\.azure\.com|vs-ssh\.visualstudio\.com):v3/([^/\s]+)/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$"),
    re.compile(r"dev\.azure\.com/([^/\s]+)/([^/\s]+)/_git/([^/\s?#]+?)(?:\.git)?/?(?:[?#].*)?$"),
    re.compile(r"//(?:[^@/\s]+@)?([^./\s]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/\s]+)/_git/([^/\s?#]+?)(?:\.git)?/?(?:[?#].*)?$"),
)
JIRA_KEYS = (
    "JIRA_WORKSPACE",
    "JIRA_BASE_URL",
)
JIRA_CREDENTIAL_KEYS = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")  # optional: else atlassian-oauth
DESIGN_MCP_SERVERS = {"figma", "playwright"}  # on only with DESIGN_MCP=on
ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
# Secret-looking env var names: kept out of settings.local.json here and out of MCP child envs
# by tools/mcp-run.py. Anchored parts avoid non-secrets such as SSH_AUTH_SOCK or TERM_SESSION_ID.
# OP_SESSION_* are 1Password CLI session tokens; *_PAT personal access tokens; *_PWD passwords
# (e.g. MYSQL_PWD).
SECRET_NAME = re.compile(
    r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL|WEBHOOK|COOKIE"
    r"|(^|_)KEY$|(^|_)PASS(PHRASE)?($|_)|(^|_)(AUTH|SESSION)$|(^|_)DSN($|_)"
    r"|^OP_SESSION_|_PAT$|_PWD$",
    re.I,
)
# Removed from settings.local.json on sight: `printenv` exits 1 whenever the variable is absent
# from the environment Claude Code starts in, and a failing helper blocks authentication instead
# of falling back to the env var or the `claude` login. A helper the user set otherwise is kept.
STALE_API_KEY_HELPER = f"printenv {ANTHROPIC_KEY}"
PLACEHOLDER_PATTERNS = (
    "replace-with-",
    "your-",
    "your.name@",
    "_here",
)


def usable_secret(value: str) -> bool:
    """A real value: set, not a template placeholder, not an unresolved op:// ref."""
    value = value.strip()
    return bool(value) and not looks_like_placeholder(value) and not value.startswith("op://")


def drop_unusable_anthropic_key(env: dict[str, str], current_env: dict[str, str]) -> None:
    """An ANTHROPIC_API_KEY that is empty, a template placeholder or an unresolved op://
    ref must not reach the session env: Claude Code would prefer it over the login and
    every request would fail. Drop it from `env`, and from the previously synced
    settings.local.json `env` too when that copy is equally unusable."""
    if ANTHROPIC_KEY not in env or usable_secret(env[ANTHROPIC_KEY]):
        return
    warn(f"{ANTHROPIC_KEY} in .claude/.env is empty/placeholder/unresolved — ignoring it; "
         "Claude Code keeps using your `claude` login")
    del env[ANTHROPIC_KEY]
    if not usable_secret(current_env.get(ANTHROPIC_KEY, "x")):
        current_env.pop(ANTHROPIC_KEY, None)


def remove_stale_api_key_helper(settings: dict) -> bool:
    """Drop the `printenv ANTHROPIC_API_KEY` apiKeyHelper. Returns True if settings changed."""
    if settings.get("apiKeyHelper") != STALE_API_KEY_HELPER:
        return False
    del settings["apiKeyHelper"]
    return True


def gh_auth_token() -> str:
    """Token of the user's `gh auth login` session (browser/device sign-in), or ''."""
    gh = shutil.which("gh")
    if not gh:
        return ""
    try:
        result = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def origin_url(cwd: str | None = None) -> str:
    try:
        return subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                              text=True, timeout=5, cwd=cwd).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def github_remote_slug() -> tuple[str, str] | None:
    """(owner, repo) parsed from the origin URL when it points at github.com."""
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", origin_url())
    return (m.group(1), m.group(2)) if m else None


def azure_remote_slug(url: str) -> tuple[str, str, str] | None:
    """(org, project, repo) of an Azure DevOps git URL (remote or web), URL-decoded,
    e.g. ("MyOrg", "My Project", "api") for ssh.dev.azure.com:v3/MyOrg/My%20Project/api."""
    for pattern in AZURE_REMOTE:
        m = pattern.search(url)
        if m:
            return tuple(unquote(part) for part in m.groups())  # type: ignore[return-value]
    return None


def azure_url_parts(url: str) -> tuple[str, str, str]:
    """(org, project, repo) of an Azure DevOps web URL at any level, URL-decoded; parts
    the URL doesn't reach are "". Repo URLs and remotes also go through azure_remote_slug."""
    url = url.strip()
    slug = azure_remote_slug(url)
    if slug:
        return slug
    for pattern in AZURE_WEB_URL:
        m = pattern.search(url)
        if m:
            org, project, repo = (unquote(g or "") for g in m.groups())
            project = "" if project.startswith("_") else project  # /_settings, /_git without a project
            return org, project, repo.removesuffix(".git")
    return "", "", ""


def azure_settings(env: dict[str, str], cwd: str | None = None) -> dict[str, str]:
    """AZURE_DEVOPS_ORG / _PROJECT / _REPO, each from the first source that has it:
    the key itself, then AZURE_DEVOPS_URL, then the origin remote (cwd). Missing → ""."""
    sources = [
        tuple(env.get(k, "").strip() if usable_secret(env.get(k, "")) else "" for k in AZURE_KEYS),
        azure_url_parts(env.get(AZURE_URL_KEY, "")),
        azure_remote_slug(origin_url(cwd)) or ("", "", ""),
    ]
    return {key: next((src[i] for src in sources if src[i]), "") for i, key in enumerate(AZURE_KEYS)}


def warn(msg: str) -> None:
    sys.stderr.write(f"[sync-env] {msg}\n")


def looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(p in lowered for p in PLACEHOLDER_PATTERNS)


def detect_git_host(env: dict[str, str]) -> str | None:
    """Mirrors tools/detect_git_host.sh: explicit GIT_HOST override, then the
    origin remote URL, then whichever of BITBUCKET_WORKSPACE/GITHUB_OWNER is the
    only one populated, then azure when AZURE_DEVOPS_ORG or AZURE_DEVOPS_URL is (a
    workspace root may hold GitHub and Azure DevOps repos: the Azure keys there only
    turn on the azure-devops server and the PR skills take the host from a PR URL).
    Returns None if undeterminable (caller warns)."""
    override = env.get("GIT_HOST", "").strip().lower()
    if override in ("bitbucket", "github", "azure"):
        return override

    remote_url = origin_url()
    if "bitbucket.org" in remote_url:
        return "bitbucket"
    if "github.com" in remote_url:
        return "github"
    if "dev.azure.com" in remote_url or ".visualstudio.com" in remote_url:
        return "azure"

    signals = {"bitbucket": "BITBUCKET_WORKSPACE", "github": "GITHUB_OWNER"}
    populated = [host for host, key in signals.items() if env.get(key)]
    if len(populated) == 1:
        return populated[0]
    if not populated and (env.get("AZURE_DEVOPS_ORG") or env.get(AZURE_URL_KEY)):
        return "azure"
    return None


def unused_mcp_servers(host: str | None, env: dict[str, str]) -> set[str]:
    """MCP servers from mcp.json.template this project doesn't use. Where a service
    has an API-key server and a hosted browser-sign-in (OAuth) server, the key wins
    when usable credentials exist, otherwise the OAuth one is on:
      - atlassian (JIRA_BASE_URL + JIRA_EMAIL + JIRA_API_TOKEN) / atlassian-oauth
      - notion (NOTION_TOKEN) / notion-oauth; NOTION_MCP=off disables both
      - github only when the git host is github (its token may come from `gh auth
        login`, see main()); Bitbucket has no MCP server — the PR skills use
        tools/bb_*.sh.
      - azure-devops when the git host is azure or an Azure DevOps org is known from
        AZURE_DEVOPS_ORG / AZURE_DEVOPS_URL (a workspace root that is not a repo but
        reviews Azure DevOps PRs); AZURE_DEVOPS_PAT if set, else browser sign-in.
      - figma and playwright (the design-spec / design-build servers) only with
        DESIGN_MCP=on: most projects never use them, and playwright starts a
        browser server at every session start.
    sonarqube stays on."""
    unused: set[str] = set()
    if host != "github":
        unused.add("github")
    if host != "azure" and not azure_settings(env)["AZURE_DEVOPS_ORG"]:
        unused.add("azure-devops")
    unused.add("atlassian-oauth" if all(usable_secret(env.get(k, "")) for k in JIRA_CREDENTIAL_KEYS) else "atlassian")
    if env.get("NOTION_MCP", "").strip().lower() == "off":
        unused |= {"notion", "notion-oauth"}
    else:
        unused.add("notion-oauth" if usable_secret(env.get("NOTION_TOKEN", "")) else "notion")
    if env.get("DESIGN_MCP", "").strip().lower() != "on":
        unused |= DESIGN_MCP_SERVERS
    return unused


def apply_mcp_servers(project_root: Path, settings: dict, unused: set[str]) -> bool:
    """Approve the project's .mcp.json servers (no manual approval prompt) and
    disable the unused ones, via enabled/disabledMcpjsonServers in
    settings.local.json. Touches only servers named in .mcp.json; entries the
    user added for other servers are kept. Returns True if settings changed.
    Takes effect from the next session start (servers are already launched when
    this hook runs)."""
    mcp_path = project_root / ".mcp.json"
    if not mcp_path.is_file():
        return False
    try:
        names = set(json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers", {}))
    except (OSError, json.JSONDecodeError):
        return False
    disabled_now = unused & names
    enabled = [n for n in settings.get("enabledMcpjsonServers", []) if n not in names]
    disabled = [n for n in settings.get("disabledMcpjsonServers", []) if n not in names]
    enabled += sorted(names - disabled_now)
    disabled += sorted(disabled_now)
    changed = (settings.get("enabledMcpjsonServers") != enabled
               or settings.get("disabledMcpjsonServers") != disabled)
    settings["enabledMcpjsonServers"] = enabled
    settings["disabledMcpjsonServers"] = disabled
    return changed


def parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def resolve_op_refs(env: dict[str, str]) -> dict[str, str]:
    op_keys = [k for k, v in env.items() if v.startswith("op://")]
    if not op_keys:
        return env
    op_path = shutil.which("op")
    if not op_path:
        warn(
            f"{len(op_keys)} key(s) use op:// references but the 1Password CLI "
            "('op') is not installed/on PATH; leaving them unresolved."
        )
        return env
    resolved = dict(env)
    for key in op_keys:
        ref = env[key]
        try:
            result = subprocess.run(
                [op_path, "read", ref],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            resolved[key] = result.stdout.strip()
        except subprocess.CalledProcessError as exc:
            warn(f"'op read {ref}' failed for {key}: {exc.stderr.strip() or exc}")
        except (subprocess.TimeoutExpired, OSError) as exc:
            warn(f"'op read {ref}' errored for {key}: {exc}")
    return resolved


def export_to_session(env: dict[str, str]) -> None:
    """Make the keys visible to Bash/skill/agent calls in *this* session. Claude Code
    reads settings.local.json `env` before this hook runs, so that merge only helps
    from the next session; CLAUDE_ENV_FILE is sourced before each Bash command now."""
    target = os.environ.get("CLAUDE_ENV_FILE")
    if not target:
        return
    lines = [
        f"export {k}={shlex.quote(v)}"
        for k, v in env.items()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) and not v.startswith("op://")
    ]
    try:
        # 0600 from creation (and before writing to an existing file): never readable by others
        fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        if hasattr(os, "fchmod"):  # not on Windows
            try:
                os.fchmod(fd, 0o600)
            except OSError as exc:
                warn(f"could not make CLAUDE_ENV_FILE owner-only ({exc}); writing it anyway")
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        warn(f"could not write CLAUDE_ENV_FILE ({exc}); keys apply from the next session")


def write_private(path: Path, text: str) -> None:
    """Replace `path` atomically with a file that is 0600 from creation."""
    # mkstemp: a fresh random name (a stale temp file from a crashed run cannot block
    # the write), created O_EXCL with mode 0600
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if hasattr(os, "fchmod"):  # not on Windows
                os.fchmod(fh.fileno(), 0o600)
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def secret_keys(raw_env: dict[str, str]) -> set[str]:
    """Keys never written to settings.local.json: an op:// reference in .env, a
    secret-looking name, and GITHUB_TOKEN (it may come from `gh auth token`)."""
    keys = {k for k, v in raw_env.items() if v.startswith("op://") or SECRET_NAME.search(k)}
    keys.add("GITHUB_TOKEN")
    keys.discard(ANTHROPIC_KEY)
    return keys


def main() -> int:
    project_root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    env_path = project_root / ".claude" / ".env"
    settings_path = project_root / ".claude" / "settings.local.json"

    if not env_path.is_file():
        warn(f"{env_path} not found; skipping sync (skills that need keys will fail).")
        return 0

    try:
        raw_env = parse_env_file(env_path)
    except OSError as exc:
        warn(f"failed to read {env_path}: {exc}; skipping.")
        return 0

    if not raw_env:
        warn(f"{env_path} parsed to zero entries; skipping.")
        return 0

    env = resolve_op_refs(raw_env)

    host = detect_git_host(env)
    if host == "bitbucket":
        required_keys = BITBUCKET_KEYS + JIRA_KEYS
    elif host == "github":
        required_keys = GITHUB_KEYS + JIRA_KEYS
    elif host == "azure":
        required_keys = AZURE_KEYS[:1] + JIRA_KEYS  # project/repo also come from a PR URL
    else:
        warn(
            "could not determine git host (set GIT_HOST=bitbucket|github|azure, or "
            "populate BITBUCKET_WORKSPACE/GITHUB_OWNER/AZURE_DEVOPS_ORG); skipping "
            "host-specific required-key checks"
        )
        required_keys = JIRA_KEYS

    if host == "azure" or env.get(AZURE_URL_KEY):
        for key, val in azure_settings(env).items():
            if val and not usable_secret(env.get(key, "")):
                env[key] = val
                warn(f"{key} not set — using {val!r} from {AZURE_URL_KEY} or the origin remote")

    if host == "github":
        slug = github_remote_slug()
        for key, val in zip(("GITHUB_OWNER", "GITHUB_REPO"), slug or ()):
            if not usable_secret(env.get(key, "")):
                env[key] = val
                warn(f"{key} not set — using {val!r} from the origin remote")
        if not usable_secret(env.get("GITHUB_TOKEN", "")):
            token = gh_auth_token()
            if token:
                env["GITHUB_TOKEN"] = token
                warn("GITHUB_TOKEN not set — using your `gh auth login` session")
            else:
                warn("GITHUB_TOKEN not set and no `gh auth login` session — run `gh auth login` (browser sign-in) or set GITHUB_TOKEN")

    if not all(usable_secret(env.get(k, "")) for k in JIRA_CREDENTIAL_KEYS):
        warn("no usable JIRA_EMAIL/JIRA_API_TOKEN — Jira/Confluence use browser sign-in: /mcp > atlassian-oauth > Authenticate. "
             "REST-only features (ticket image attachments, REST fallback, PR-review Jira preflight) need an API token")

    for key in required_keys:
        value = env.get(key, "")
        if not value:
            warn(f"required key {key} missing from .claude/.env")
        elif looks_like_placeholder(value):
            warn(f"required key {key} still looks like a placeholder ({value!r})")

    if env.get("NOTION_TOKEN") and looks_like_placeholder(env["NOTION_TOKEN"]):
        warn(f"NOTION_TOKEN still looks like a placeholder ({env['NOTION_TOKEN']!r})")

    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            warn(f"{settings_path} is not valid JSON ({exc}); skipping to avoid corruption.")
            return 0

    current_env = dict(settings["env"]) if isinstance(settings.get("env"), dict) else {}
    original_env = dict(current_env)
    drop_unusable_anthropic_key(env, current_env)
    export_to_session(env)

    secrets = secret_keys(raw_env)
    for key in secrets:
        current_env.pop(key, None)
    persisted = {k: v for k, v in env.items() if k not in secrets and not v.startswith("op://")}
    merged = {**current_env, **persisted}
    env_changed = merged != original_env
    mcp_changed = apply_mcp_servers(project_root, settings, unused_mcp_servers(host, env))
    helper_changed = remove_stale_api_key_helper(settings)
    if not (env_changed or mcp_changed or helper_changed):
        if settings_path.is_file():
            os.chmod(settings_path, 0o600)
        return 0

    settings["env"] = merged
    write_private(settings_path, json.dumps(settings, indent=2) + "\n")
    if env_changed:
        warn(f"synced {len(persisted)} non-secret vars from .claude/.env into settings.local.json "
             "(secrets go to this session only)")
    if helper_changed:
        warn(f"removed apiKeyHelper ({STALE_API_KEY_HELPER!r}) from settings.local.json")
    if mcp_changed:
        warn("updated enabled/disabledMcpjsonServers in settings.local.json (takes effect next session)")
    return 0


if __name__ == "__main__":
    sys.exit(main())