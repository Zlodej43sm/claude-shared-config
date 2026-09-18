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
- Warns on stderr if .env is missing, unparseable, or required keys are absent /
  still placeholders. Never blocks the session.
"""
from __future__ import annotations

import json
import os
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
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
)
PLACEHOLDER_PATTERNS = (
    "replace-with-",
    "your-",
    "your.name@",
    "_here",
)


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

    for key in required_keys:
        value = env.get(key, "")
        if not value:
            warn(f"required key {key} missing from .claude/.env")
        elif looks_like_placeholder(value):
            warn(f"required key {key} still looks like a placeholder ({value!r})")

    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            warn(f"{settings_path} is not valid JSON ({exc}); skipping to avoid corruption.")
            return 0

    current_env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    merged = {**current_env, **env}
    if merged == current_env:
        return 0

    settings["env"] = merged
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    warn(f"synced {len(env)} vars from .claude/.env into settings.local.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())