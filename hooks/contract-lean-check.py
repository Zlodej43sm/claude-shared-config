#!/usr/bin/env python3
"""PreToolUse (Bash) hook: before `git commit` or `git push`, scans the lines the
change adds for patterns reviewers keep rejecting, and asks the user before
the command runs.

Checked on added lines only:
- a Zod `.describe(` (field descriptions: the name should say it);
- a `.refine(` / `.superRefine(` (keep contracts lean);
- a `description` line in a method config (`methods/<name>/config.ts`);
- a `type` / `interface` declared in `models/` or `helpers/` outside `types.ts`.

Commit: the staged files against the merge base with the remote default
branch, so a line put back as it was on the base is not flagged. Push: the
branch against that merge base. The repo is the command's `cd <dir>` / `git -C <dir>`,
else the tool call's cwd. Anything unexpected (not a repo, no remote) is a
silent no-op, never a block. Project-agnostic: rules for when an exception is
fine live in the project's coding-standards docs.
"""
import json
import os
import re
import shlex
import subprocess
import sys

DOC_HINT = (
    "Keep it only if the project's coding-standards allow it (siblings do the same, "
    "the refine changes the outcome); otherwise remove it before committing."
)


def run(args, cwd):
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_dir(command, cwd):
    tokens = []
    try:
        tokens = shlex.split(command)
    except ValueError:
        pass
    for i, token in enumerate(tokens[:-1]):
        if token in ("cd", "-C") and not tokens[i + 1].startswith("-"):
            path = os.path.expanduser(tokens[i + 1])
            return path if os.path.isabs(path) else os.path.join(cwd, path)
    return cwd


def branch_base(repo):
    head = run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo).strip()
    for candidate in [head, "origin/master", "origin/main"]:
        if candidate:
            base = run(["git", "merge-base", candidate, "HEAD"], repo).strip()
            if base:
                return base
    return ""


def findings_from_diff(diff):
    findings = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++") or "__tests__" in path:
            continue
        text = line[1:]
        if not path.endswith((".ts", ".js")):
            continue
        if ".describe(" in text:
            findings.append(f"{path}: new `.describe(` — {text.strip()[:80]}")
        if re.search(r"\.(super)?[Rr]efine\(", text):
            findings.append(f"{path}: new refine — {text.strip()[:80]}")
        if re.search(r"/methods/[^/]+/config\.ts$", path) and re.search(r"\bdescription\b", text):
            findings.append(f"{path}: method/response description added or changed")
        if (
            re.search(r"(^|/)(models|helpers)/", path)
            and not path.endswith("types.ts")
            and re.match(r"\s*(export\s+)?(type|interface)\s+\w+", text)
        ):
            findings.append(f"{path}: type declared outside a types.ts file — {text.strip()[:80]}")
    return findings


def main():
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command", "")
    is_commit = re.search(r"\bgit\b[^;&|]*\bcommit\b", command)
    is_push = re.search(r"\bgit\b[^;&|]*\bpush\b", command)
    if not (is_commit or is_push):
        return
    repo = repo_dir(command, data.get("cwd") or os.getcwd())
    if not os.path.isdir(repo) or not run(["git", "rev-parse", "--git-dir"], repo):
        return
    base = branch_base(repo)
    if is_commit:
        diff = run(["git", "diff", "--cached", "--unified=0"] + ([base] if base else []), repo)
    else:
        diff = run(["git", "diff", "--unified=0", base, "HEAD"], repo) if base else ""
    findings = findings_from_diff(diff)
    if not findings:
        return
    reason = "Lean-contract check found:\n- " + "\n- ".join(findings[:15]) + "\n" + DOC_HINT
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
