#!/usr/bin/env python3
"""PreToolUse (Bash) hook: before `git commit` or `git push`, scans the lines the
change adds for patterns reviewers keep rejecting, and asks the user before
the command runs.

Checked on added lines only:
- a Zod `.describe(` (field descriptions: the name should say it);
- a `.refine(` / `.superRefine(` (keep contracts lean);
- a `description` line in a method config (`methods/<name>/config.ts`);
- a `type` / `interface` declared in `models/` or `helpers/` outside `types.ts`;
- a helper, provider or client importing a method contract (`…/dist/methods/…`): a
  contract change would ripple into it, so it declares the fields it reads itself;
- an `it.each` / `test.each` over a named list declared above it (the cases belong inline);
- an upper-case constant declared at the top of a file that is not a constants file
  (constants live in the layer's `constants.ts`);
- a new `.feature` scenario title that names an input detail (a different case,
  whitespace) or a caller's lookback window: titles state the rule.

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


CONTRACT_IMPORT = re.compile(r"""from\s+['"][^'"]*/dist/methods/""")
CONTRACT_OWNERS = re.compile(r"(^|/)(helpers|providers|clients)/")
TEST_EACH_NAMED = re.compile(r"\b(it|test|describe)\.each\(\s*[A-Za-z_]\w*\s*\)")
TOP_LEVEL_CONSTANT = re.compile(r"^(export\s+)?const\s+[A-Z][A-Z0-9_]{2,}\b")
SCENARIO_TITLE = re.compile(r"^\s*Scenario( Outline)?:")
TITLE_DETAIL = re.compile(
    r"\b(different|upper|lower|mixed)[- ]?case\b|\bcase[- ]insensitive|"
    r"\b(trailing|leading) (space|whitespace)|\bwhitespace\b|\blookback\b",
    re.IGNORECASE,
)


def findings_from_diff(diff):
    findings = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        text = line[1:]
        if "__tests__" in path:
            if path.endswith(".test.ts") and TEST_EACH_NAMED.search(text):
                findings.append(f"{path}: it.each over a named list; inline the cases — {text.strip()[:80]}")
            continue
        if path.endswith(".feature"):
            if SCENARIO_TITLE.match(text) and TITLE_DETAIL.search(text):
                findings.append(f"{path}: scenario title names an input detail or a caller's window — {text.strip()[:80]}")
            continue
        if not path.endswith((".ts", ".js")):
            continue
        if TOP_LEVEL_CONSTANT.match(text) and not re.search(r"(^|/)constants(\.ts|/)", path):
            findings.append(f"{path}: constant declared outside a constants file — {text.strip()[:80]}")
        if CONTRACT_OWNERS.search(path) and CONTRACT_IMPORT.search(text):
            findings.append(f"{path}: imports a method contract; declare the fields it reads inline — {text.strip()[:80]}")
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
