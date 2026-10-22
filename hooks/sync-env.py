    #!/usr/bin/env python3
"""
SessionStart hook: sync .claude/.env into .claude/settings.local.json `env` block
so every Bash/agent/skill invocation inherits the keys automatically.

Behavior:
- Reads .claude/.env (KEY=VALUE, ignores #comments and blanks, strips matching quotes).
- Values of the form `op://vault/item/field` are resolved via `op read` (1Password CLI)
  before merging, so no secret needs to sit in .env as plaintext. Never blocks the
  session: if `op` is missing, not signed in, or a read fails, warns on stderr and
  merges the unresolved op:// string as-is (skills needing that key will then fail
  the same way they would with a missing/placeholder value today).
- Merges into settings.local.json `env` (values from .env win on conflict).
- ANTHROPIC_API_KEY: when .env holds a usable key it is merged like the rest, so
  Claude Code authenticates with it from the next session start (before this hook
  runs the session is already signed in, so the first session still uses the login)
  and every skill/agent that calls the Anthropic API inherits it. A placeholder,
  empty or unresolved op:// value is never merged (it would break auth instead of
  falling back to the login).
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
from pathlib import Path

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
JIRA_KEYS = (
    "JIRA_WORKSPACE",
    "JIRA_BASE_URL",
)
JIRA_CREDENTIAL_KEYS = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")  # optional: else atlassian-oauth
ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
# Registered as `apiKeyHelper` next to the env var: Claude Code asks once whether to use an
# env-provided key and remembers a "No" per key (customApiKeyResponses.rejected in
# ~/.claude.json), silently falling back to the claude.ai login. A helper has no prompt.
API_KEY_HELPER = f"printenv {ANTHROPIC_KEY}"
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


def apply_api_key_helper(settings: dict, env: dict[str, str]) -> bool:
    """Set `apiKeyHelper` while a usable ANTHROPIC_API_KEY is synced; remove it again
    (only if it is ours) once there is none. A helper the user set themselves is kept.
    Returns True if settings changed."""
    has_key = usable_secret(env.get(ANTHROPIC_KEY, ""))
    current = settings.get("apiKeyHelper")
    if has_key and current != API_KEY_HELPER:
        if current:
            warn(f"apiKeyHelper already set ({current!r}); leaving it alone")
            return False
        settings["apiKeyHelper"] = API_KEY_HELPER
        return True
    if not has_key and current == API_KEY_HELPER:
        del settings["apiKeyHelper"]
        return True
    return False


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


def github_remote_slug() -> tuple[str, str] | None:
    """(owner, repo) parsed from the origin URL when it points at github.com."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return None
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return (m.group(1), m.group(2)) if m else None


def warn(msg: str) -> None:
    sys.stderr.write(f"[sync-env] {msg}\n")


def looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(p in lowered for p in PLACEHOLDER_PATTERNS)


def detect_git_host(env: dict[str, str]) -> str | None:
    """Mirrors tools/detect_git_host.sh: explicit GIT_HOST override, then the
    origin remote URL, then whichever of BITBUCKET_WORKSPACE/GITHUB_OWNER is
    the only one populated. Returns None if undeterminable (caller warns)."""
    override = env.get("GIT_HOST", "").strip().lower()
    if override in ("bitbucket", "github"):
        return override

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        remote_url = result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        remote_url = ""

    if "bitbucket.org" in remote_url:
        return "bitbucket"
    if "github.com" in remote_url:
        return "github"

    if env.get("BITBUCKET_WORKSPACE") and not env.get("GITHUB_OWNER"):
        return "bitbucket"
    if env.get("GITHUB_OWNER") and not env.get("BITBUCKET_WORKSPACE"):
        return "github"
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
    sonarqube stays on."""
    unused: set[str] = set()
    if host != "github":
        unused.add("github")
    unused.add("atlassian-oauth" if all(usable_secret(env.get(k, "")) for k in JIRA_CREDENTIAL_KEYS) else "atlassian")
    if env.get("NOTION_MCP", "").strip().lower() == "off":
        unused |= {"notion", "notion-oauth"}
    else:
        unused.add("notion-oauth" if usable_secret(env.get("NOTION_TOKEN", "")) else "notion")
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
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        warn(f"could not write CLAUDE_ENV_FILE ({exc}); keys apply from the next session")


def main() -> int:
    project_root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    env_path = project_root / ".claude" / ".env"
    settings_path = project_root / ".claude" / "settings.local.json"

    if not env_path.is_file():
        warn(f"{env_path} not found; skipping sync (skills that need keys will fail).")
        return 0

    try:
        env = parse_env_file(env_path)
    except OSError as exc:
        warn(f"failed to read {env_path}: {exc}; skipping.")
        return 0

    if not env:
        warn(f"{env_path} parsed to zero entries; skipping.")
        return 0

    env = resolve_op_refs(env)

    host = detect_git_host(env)
    if host == "bitbucket":
        required_keys = BITBUCKET_KEYS + JIRA_KEYS
    elif host == "github":
        required_keys = GITHUB_KEYS + JIRA_KEYS
    else:
        warn(
            "could not determine git host (set GIT_HOST=bitbucket|github, or "
            "populate BITBUCKET_WORKSPACE/GITHUB_OWNER); skipping host-specific "
            "required-key checks"
        )
        required_keys = JIRA_KEYS

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

    merged = {**current_env, **env}
    env_changed = merged != original_env
    mcp_changed = apply_mcp_servers(project_root, settings, unused_mcp_servers(host, env))
    helper_changed = apply_api_key_helper(settings, merged)
    if not (env_changed or mcp_changed or helper_changed):
        return 0

    settings["env"] = merged
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if env_changed:
        warn(f"synced {len(env)} vars from .claude/.env into settings.local.json")
    if helper_changed:
        warn("updated apiKeyHelper in settings.local.json (takes effect next session)")
    if mcp_changed:
        warn("updated enabled/disabledMcpjsonServers in settings.local.json (takes effect next session)")
    return 0


if __name__ == "__main__":
    sys.exit(main())