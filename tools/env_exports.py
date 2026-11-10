#!/usr/bin/env python3
"""
env_exports — load the project's .claude/.env into a shell without executing it.

Skills and agents run:

    eval "$(python3 .claude/tools/env_exports.py)"

Sourcing the file instead (`. .claude/.env`) runs it as shell: an unquoted value
with a space, such as `op://Dev Tooling/item/field`, makes bash execute the text
after the space as a command, relative to the project root. This tool parses the
file with hooks/sync-env.py's parser and prints one export line per key.

Non-secret keys: `export KEY='value'`, quoted with shlex.quote. A literal value
in .env wins (an edit to .env applies without a restart); an empty or placeholder
value keeps a usable session value (e.g. GITHUB_OWNER taken from the origin remote).

Secret keys (an op:// reference in .env, a name matching SECRET_NAME in
hooks/sync-env.py, or ANTHROPIC_API_KEY): the value is never printed, so running
the tool without `eval` leaks nothing into a transcript.
  - the session already holds a usable value and .env has an op:// reference, an
    empty/placeholder value, or the same value -> no line (it is already set; e.g.
    GITHUB_TOKEN from `gh auth login`);
  - otherwise -> `export KEY="$(... env_exports.py --value KEY)"`, which reads
    the value only when the shell evaluates the line. An op:// reference is
    resolved with `op read` then; one that cannot be resolved leaves the key empty,
    so it is reported as missing rather than holding an op:// string.

--value KEY  print KEY's value from .env: the literal, or its op:// reference
             resolved with `op read`. Prints nothing when KEY is absent or the
             reference cannot be resolved, so KEY ends up empty (= missing).

Project dir: $CLAUDE_PROJECT_DIR, else the cwd.

STDOUT  export lines (nothing when .claude/.env is absent); with --value, the value
EXIT    0
"""
from __future__ import annotations

import importlib.util
import os
import re
import shlex
import sys
from pathlib import Path

KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_sync_env():
    path = Path(__file__).resolve().parent.parent / "hooks" / "sync-env.py"
    spec = importlib.util.spec_from_file_location("sync_env", path)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True  # no __pycache__ in the shared hooks/ directory
    spec.loader.exec_module(module)
    return module


def print_value(sync_env, file_env: dict[str, str], key: str) -> int:
    value = file_env.get(key, "")
    if value.startswith("op://"):
        value = sync_env.resolve_op_refs({key: value})[key]
        if value.startswith("op://"):
            return 0
    if value:
        sys.stdout.write(value + "\n")
    return 0


def main(argv: list[str]) -> int:
    project_dir = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    env_file = Path(project_dir) / ".claude" / ".env"
    if argv and (argv[0] != "--value" or len(argv) != 2):
        sys.stderr.write("usage: env_exports.py [--value KEY]\n")
        return 2
    if not env_file.is_file():
        return 0
    sync_env = load_sync_env()
    file_env = {k: v for k, v in sync_env.parse_env_file(env_file).items() if KEY_RE.fullmatch(k)}
    if argv:
        return print_value(sync_env, file_env, argv[1])

    value_cmd = (f"CLAUDE_PROJECT_DIR={shlex.quote(project_dir)} python3 -I "
                 f"{shlex.quote(str(Path(__file__).resolve()))} --value")
    lines: list[str] = []
    for key, value in file_env.items():
        session = os.environ.get(key, "")
        if value.startswith("op://") or sync_env.SECRET_NAME.search(key) or key == sync_env.ANTHROPIC_KEY:
            if sync_env.usable_secret(session) and (
                    value.startswith("op://") or not sync_env.usable_secret(value) or value == session):
                continue
            lines.append(f'export {key}="$({value_cmd} {key})"\n')
        elif sync_env.usable_secret(value) or not sync_env.usable_secret(session):
            lines.append(f"export {key}={shlex.quote(value)}\n")
        else:
            lines.append(f"export {key}={shlex.quote(session)}\n")

    sys.stdout.write("".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
