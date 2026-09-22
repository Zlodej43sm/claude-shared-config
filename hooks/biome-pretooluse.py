#!/usr/bin/env python3
"""PreToolUse (Edit|Write) hook: blocks a save whose resulting content fails
`biome check`.

Calls node_modules/.bin/biome directly — the RTK `biome check` filter has been
observed to report a real exit-1 failure as "No issues found", so routing this
through RTK would silently defeat the check.

`biome check --stdin-file-path=... -` looks like the obvious way to check
content that isn't on disk yet, but it only runs the formatter/import-sort
pass: it misses real lint-rule violations entirely (verified against
`noExplicitAny` — file-mode catches it, stdin-mode doesn't). To get the same
diagnostics a real save would get, the prospective content is written to a
throwaway sibling file (same directory, same extension) and checked with a
normal file-mode `biome check`, then removed.

Project-agnostic: everything is derived from CLAUDE_PROJECT_DIR and the
project's own node_modules/biome.json, so this works unmodified on any repo
that symlinks this shared hooks/ directory and has Biome installed. Projects
without a node_modules/.bin/biome binary get a silent no-op, not a block.
"""
import json
import os
import subprocess
import sys
import tempfile

LINTED_EXTENSIONS = (".ts", ".tsx", ".js", ".mjs", ".json")


def prospective_edit_content(file_path: str, tool_input: dict) -> str | None:
    if not os.path.isfile(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        current = f.read()
    old = tool_input.get("old_string", "")
    new = tool_input.get("new_string", "")
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def main() -> None:
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path")
    if tool_name not in ("Write", "Edit") or not file_path:
        return
    if not file_path.endswith(LINTED_EXTENSIONS):
        return

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    biome = os.path.join(project_dir, "node_modules", ".bin", "biome")
    if not os.path.isfile(biome) or not os.access(biome, os.X_OK):
        return  # project doesn't use biome, or pre-install state — don't block

    if tool_name == "Write":
        content = tool_input.get("content", "")
    else:
        content = prospective_edit_content(file_path, tool_input)
        if content is None:
            return  # file doesn't exist yet — nothing to reconstruct

    ext = os.path.splitext(file_path)[1]
    directory = os.path.dirname(file_path)
    fd, tmp_path = tempfile.mkstemp(prefix=".pretooluse-tmp-", suffix=ext, dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        result = subprocess.run(
            # The temp file matches the crash-safety-net .gitignore pattern
            # (**/.pretooluse-tmp-*) each project should add alongside this
            # hook, which would otherwise make biome's VCS-aware ignore logic
            # skip it entirely.
            [biome, "check", "--vcs-use-ignore-file=false", tmp_path],
            capture_output=True,
            text=True,
            cwd=project_dir,
        )
    finally:
        os.remove(tmp_path)

    if result.returncode != 0:
        rel_path = os.path.relpath(file_path, project_dir)
        report = (result.stdout + result.stderr).replace(
            os.path.basename(tmp_path), os.path.basename(file_path)
        )
        deny(f"Biome check failed for {rel_path}:\n{report.strip()}")


if __name__ == "__main__":
    main()
