#!/usr/bin/env python3
"""
mcp-run — launch an MCP server with its configuration filled in from the
project's .claude/.env, then exec it (stdio passes straight through).

Why this exists: Claude Code expands ${VAR} in .mcp.json only from the real
process environment, never from .claude/settings*.json `env`, and substitutes
${VAR:-default} before anything else sees it — so a static, shared
mcp.json.template cannot be filled from .claude/.env by itself. This wrapper
reads .claude/.env directly (resolving `op://` 1Password references in memory
via `op read`, only for the keys the server uses — secrets never touch disk).

Usage, as written in mcp.json.template:
    python3 .claude/tools/mcp-run.py [--env NAME=VALUE]... [--fallback KEY=cmd]... -- <command> [args...]

  {{KEY}}          required: value of KEY (real process env wins, then .env).
                   Missing, empty, a template placeholder, or an unresolved
                   op:// reference -> message on stderr, exit 1 (the server
                   shows as failed in /mcp instead of running half-configured).
  {{KEY|default}}  optional: falls back to `default` (may be empty). The default
                   may reference other keys as {OTHER}, e.g.
                   {{CONFLUENCE_BASE_URL|{JIRA_BASE_URL}/wiki}}; referenced keys
                   are looked up like KEY (incl. op:// and --fallback). If one has
                   no usable value the whole default expands to "" (the variable
                   is then left unset, like an empty optional).

--fallback KEY=<command line>: when KEY has no usable value (not in the process env or
.env, or a template placeholder / unresolved op:// reference), run the command and use its trimmed stdout (e.g. GITHUB_TOKEN="gh auth token" reuses
the user's `gh auth login` session — a browser sign-in — so no API key is needed).
A failing/empty command just leaves KEY unset, so the usual "not set" error follows.

Placeholders are expanded in --env values and in the command/args. --env
variables whose expanded value is empty are not exported at all, so
`docker run -e VAR` forwards nothing rather than an empty string.

The server gets only the credentials it asks for: the inherited environment is
passed on without every key defined in .claude/.env, without any variable with
a secret-looking name (*TOKEN*, *SECRET*, *PASSWORD*, *_KEY, OP_SESSION_*, *_PAT,
*_PWD, ...: SECRET_NAME in hooks/sync-env.py) and without any variable whose value
holds URL credentials (`scheme://user:password@...`), then the --env pairs are added. A server started with `npx`/`uvx` runs
on the host and resolves its dependencies at start; mcp.json.template pins that resolution to
a date (`--exclude-newer` / `--before`).

Project dir: the cwd (Claude Code starts stdio servers there), else
$CLAUDE_PROJECT_DIR.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# {{KEY}} or {{KEY|default}}; the default may contain {OTHER} key references.
PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)(?:\|((?:[^{}]|\{[A-Za-z0-9_]+\})*))?\}\}")
KEY_REF = re.compile(r"\{([A-Za-z0-9_]+)\}")
# A value carrying URL userinfo with a password, e.g. https://user:pass@host (a proxy URL).
URL_CREDENTIALS = re.compile(r"://[^/?#@\s:]*:[^/?#@\s]*@")


def load_sync_env():
    # hooks/sync-env.py owns the .env parser, op:// resolution and the placeholder
    # heuristics; reuse it so every consumer of .claude/.env behaves the same.
    path = Path(__file__).resolve().parent.parent / "hooks" / "sync-env.py"
    spec = importlib.util.spec_from_file_location("sync_env", path)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True  # no __pycache__ in the shared hooks/ directory
    spec.loader.exec_module(module)
    return module


def die(msg: str) -> None:
    sys.stderr.write(f"[mcp-run] {msg}\n")
    raise SystemExit(1)


def find_project() -> Path:
    for candidate in (Path.cwd(), Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))):
        if (candidate / ".claude" / ".env").is_file():
            return candidate
    return Path.cwd()


def main(argv: list[str]) -> int:
    if "--" not in argv:
        die("usage: mcp-run.py [--env NAME=VALUE]... -- <command> [args...]")
    split = argv.index("--")
    opts, command = argv[:split], argv[split + 1:]
    if not command:
        die("no command after --")

    pairs: list[tuple[str, str]] = []
    fallbacks: dict[str, str] = {}
    it = iter(opts)
    for flag in it:
        value = next(it, None)
        if flag not in ("--env", "--fallback") or value is None or "=" not in value:
            die(f"bad option {flag!r} (expected --env NAME=VALUE or --fallback KEY=command)")
        name, _, raw = value.partition("=")
        if flag == "--env":
            pairs.append((name, raw))
        else:
            fallbacks[name] = raw

    sync_env = load_sync_env()
    env_file = find_project() / ".claude" / ".env"
    file_env = sync_env.parse_env_file(env_file) if env_file.is_file() else {}

    templates = [raw for _, raw in pairs] + command
    keys: set[str] = set()
    for m in (m for t in templates for m in PLACEHOLDER.finditer(t)):
        keys.add(m.group(1))
        keys.update(KEY_REF.findall(m.group(2) or ""))

    # Real process env wins over the file; only op:// refs for keys we use get resolved.
    values = {k: os.environ[k] for k in keys if os.environ.get(k)}
    from_file = {k: file_env[k] for k in keys if k not in values and file_env.get(k)}
    values.update(sync_env.resolve_op_refs(from_file))
    for key, cmdline in fallbacks.items():
        if key in keys and not sync_env.usable_secret(values.get(key, "")):
            try:
                out = subprocess.run(shlex.split(cmdline), capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if out.returncode == 0 and out.stdout.strip():
                values[key] = out.stdout.strip()

    problems: list[str] = []

    def expand(text: str) -> str:
        def sub(m: re.Match) -> str:
            key, default = m.group(1), m.group(2)
            val = values.get(key, "")
            if val.startswith("op://"):
                problems.append(f"{key} is an unresolved op:// reference (is `op` installed and signed in?)")
                return ""
            if val and sync_env.looks_like_placeholder(val):
                problems.append(f"{key} still looks like a placeholder ({val!r})")
                return ""
            if val:
                return val
            if default is not None:
                refs = KEY_REF.findall(default)
                if not all(sync_env.usable_secret(values.get(r, "")) for r in refs):
                    return ""
                return KEY_REF.sub(lambda r: values[r.group(1)], default)
            problems.append(f"{key} is not set in {env_file}")
            return ""
        return PLACEHOLDER.sub(sub, text)

    child_env = {k: v for k, v in os.environ.items()
                 if k not in file_env and not sync_env.SECRET_NAME.search(k)
                 and not URL_CREDENTIALS.search(v)}
    for name, raw in pairs:
        expanded = expand(raw)
        if expanded:
            child_env[name] = expanded
        else:
            child_env.pop(name, None)
    cmd = [expand(a) for a in command]

    if problems:
        die("; ".join(dict.fromkeys(problems)))
    try:
        os.execvpe(cmd[0], cmd, child_env)
    except OSError as exc:
        die(f"cannot run {cmd[0]!r}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
