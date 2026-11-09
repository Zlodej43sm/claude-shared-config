#!/usr/bin/env python3
"""
env_exports — load the project's .claude/.env into a shell without executing it.

Skills and agents run:

    eval "$(python3 .claude/tools/env_exports.py)"

Sourcing the file instead (`. .claude/.env`) runs it as shell: an unquoted value
with a space, such as `op://Dev Tooling/item/field`, makes bash execute the text
after the space as a command, relative to the project root. This tool parses the
file with hooks/sync-env.py's parser and prints one `export KEY='value'` line per
key, every value quoted with shlex.quote.

Value per key:
  - a literal value in .env wins (an edit to .env applies without a restart);
  - an `op://` reference uses the session's value when hooks/sync-env.py already
    resolved it, else resolves it now with `op read`;
  - an empty or placeholder value keeps a usable session value (e.g. GITHUB_OWNER
    taken from the origin remote, GITHUB_TOKEN from `gh auth login`).
A reference that cannot be resolved is not exported, so the key is reported as
missing rather than holding an op:// string.

Project dir: $CLAUDE_PROJECT_DIR, else the cwd.

STDOUT  export lines (nothing when .claude/.env is absent)
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
    spec.loader.exec_module(module)
    return module


def main() -> int:
    env_file = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()) / ".claude" / ".env"
    if not env_file.is_file():
        return 0
    sync_env = load_sync_env()
    file_env = {k: v for k, v in sync_env.parse_env_file(env_file).items() if KEY_RE.fullmatch(k)}

    values: dict[str, str] = {}
    to_resolve: dict[str, str] = {}
    for key, value in file_env.items():
        session = os.environ.get(key, "")
        if value.startswith("op://"):
            if sync_env.usable_secret(session):
                values[key] = session
            else:
                to_resolve[key] = value
        elif sync_env.usable_secret(value) or not sync_env.usable_secret(session):
            values[key] = value
        else:
            values[key] = session
    for key, value in sync_env.resolve_op_refs(to_resolve).items():
        if not value.startswith("op://"):
            values[key] = value

    sys.stdout.write("".join(f"export {k}={shlex.quote(v)}\n" for k, v in values.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
