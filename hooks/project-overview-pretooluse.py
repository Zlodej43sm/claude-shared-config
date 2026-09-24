#!/usr/bin/env python3
"""PROTOTYPE — PreToolUse hook that self-filters to fire ONLY when the Skill
tool is invoking `project-overview`; a silent no-op (no stdout, exit 0) for
every other tool or skill, so it adds zero overhead and changes nothing else
in the session.

Why self-filter in the script rather than relying on the settings.json
matcher/`if` field alone: the exact `tool_input` shape Claude Code sends for
a Skill-tool call, and the exact `if`-field syntax for narrowing a matcher to
one specific skill name, are NOT confirmed by documentation as of writing.
This script tries several plausible field names, falls back to a substring
scan of the whole `tool_input`, and — critically — treats every parse/lookup
failure as "not a match" rather than guessing. Getting this wrong should
always fail toward doing nothing, never toward misfiring on the wrong tool.

Deliberately conservative about WHERE it scans: it always defaults ROOT to
$CLAUDE_PROJECT_DIR rather than trying to parse a user-supplied `<path>` out
of free-text skill arguments — injecting a scan of the WRONG directory as if
authoritative would actively mislead the model, which is worse than
injecting nothing. The injected context says so explicitly and tells the
skill to re-run the scanner itself if the real arguments differ.

Logs the raw stdin payload to DEBUG_LOG once per invocation so a real Skill
call's actual tool_input shape can be inspected and this script tightened
accordingly — remove that logging once the shape is confirmed.

STDIN   PreToolUse hook payload JSON
STDOUT  nothing (no-op) or {"hookSpecificOutput": {...}} on a confirmed match
EXIT    always 0 — this hook must never block or slow down any tool call
"""
import json
import os
import subprocess
import sys
from pathlib import Path

DEBUG_LOG = Path("/tmp/project-overview-pretooluse-debug.jsonl")


def log_debug(payload: dict) -> None:
    try:
        with DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError:
        pass


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
    try:
        return "project-overview" in json.dumps(tool_input)
    except TypeError:
        return False


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return

    log_debug(payload)  # prototype only — confirms the real tool_input shape

    try:
        matched = is_project_overview(payload)
    except Exception:  # noqa: BLE001 - a bug here must never block the tool
        matched = False
    if not matched:
        return

    project_root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    scanner = Path(project_root) / ".claude" / "tools" / "project_overview_scan.py"
    if not scanner.is_file():
        scanner = Path(project_root) / "tools" / "project_overview_scan.py"
    if not scanner.is_file():
        return  # scanner not present in this project — Step 1's own fallback handles it

    try:
        result = subprocess.run(
            ["python3", str(scanner), str(project_root)],
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
            "permissionDecision": "allow",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
