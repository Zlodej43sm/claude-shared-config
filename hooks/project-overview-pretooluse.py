#!/usr/bin/env python3
"""PROTOTYPE — PreToolUse hook that self-filters to fire ONLY when the Skill
tool is invoking `project-overview`; a silent no-op (no stdout, exit 0) for
every other tool or skill, so it adds zero overhead and changes nothing else
in the session.

Why self-filter in the script rather than relying on the settings.json
matcher/`if` field alone: the exact `tool_input` shape Claude Code sends for
a Skill-tool call, and the exact `if`-field syntax for narrowing a matcher to
one specific skill name, are NOT confirmed by documentation as of writing.
This script checks several plausible field names for an exact skill name
(never a substring match on the whole `tool_input`, which an argument that
merely mentions the skill would trip), and — critically — treats every
parse/lookup failure as "not a match" rather than guessing. Getting this wrong should
always fail toward doing nothing, never toward misfiring on the wrong tool.

Deliberately conservative about WHERE it scans: it always defaults ROOT to
$CLAUDE_PROJECT_DIR rather than trying to parse a user-supplied `<path>` out
of free-text skill arguments — injecting a scan of the WRONG directory as if
authoritative would actively mislead the model, which is worse than
injecting nothing. The injected context says so explicitly and tells the
skill to re-run the scanner itself if the real arguments differ.

Runs the scanner from this hook's own shared tree (hooks/../tools/), never a
copy inside the scanned project: a repo's own `tools/*.py` is untrusted code.

STDIN   PreToolUse hook payload JSON
STDOUT  nothing (no-op) or {"hookSpecificOutput": {hookEventName, additionalContext}}
        on a confirmed match — context only, never a permission decision
EXIT    always 0 — this hook must never block or slow down any tool call
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCANNER = Path(__file__).resolve().parent.parent / "tools" / "project_overview_scan.py"


def is_project_overview(payload: dict) -> bool:
    if payload.get("tool_name") != "Skill":
        return False
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return False
    for key in ("name", "skill", "skill_name", "command"):
        value = str(tool_input.get(key, "")).strip().lstrip("/")
        if value == "project-overview":
            return True
    return False


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return

    try:
        matched = is_project_overview(payload)
    except Exception:  # noqa: BLE001 - a bug here must never block the tool
        matched = False
    if not matched:
        return

    project_root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    if not SCANNER.is_file():
        return  # scanner missing from the shared tree — Step 1 runs it itself

    try:
        result = subprocess.run(
            ["python3", str(SCANNER), str(project_root)],
            capture_output=True, text=True, timeout=25, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return
    scan_json = result.stdout.strip()
    if result.returncode != 0 or not scan_json:
        return

    context = (
        "[project-overview-pretooluse hook — PROTOTYPE] Best-effort pre-scan "
        f"of $CLAUDE_PROJECT_DIR ({project_root}) below — a head start for "
        "Step 1, NOT authoritative. If the actual <path>/--related/--siblings "
        "arguments for this invocation differ from the default (whole "
        "project root, no related repos, no siblings), re-run the scanner "
        "yourself with the correct arguments instead of trusting this.\n\n"
        f"{scan_json}"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
