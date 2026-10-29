#!/usr/bin/env python3
"""
pr_line_links — turn `path:line` anchors into links that open the PR's own diff
view ("Files changed") at that line, and say whether the line is in a diff hunk.

SCHEMA_IN
  stdin   unified diff of the PR (GitHub: `Accept: application/vnd.github.v3.diff`,
          Bitbucket: `${base_url}/diff`)
  args    --host=github|bitbucket  --owner=<owner|workspace>  --repo=<repo>
          --pr=<id>  --commit=<head sha>  [--web-base=https://github.com]
          ANCHOR ...    each `path:LINE` or `path:START-END` (new side of the diff)

SCHEMA_OUT  stdout JSON list, one entry per anchor
  [{
    "anchor":   "src/a.ts:12-14",
    "path":     "src/a.ts", "start": 12, "end": 14,
    "in_diff":  true,          # file is changed by the PR
    "in_hunk":  true,          # START is a line shown in the diff (new side)
    "link":     "<best link: PR diff at the line, else PR diff at the file, else file at commit>",
    "pr_link":  "<PR diff link, line-level when in_hunk, file-level when only in_diff, else null>",
    "blob_link":"<file at the head commit, at the line(s)>"
  }]
  GitHub   line: <web>/<o>/<r>/pull/<id>/changes#diff-<sha256(path)>R<start>[-R<end>]
           file: <web>/<o>/<r>/pull/<id>/changes#diff-<sha256(path)>
  Bitbucket line: https://bitbucket.org/<ws>/<r>/pull-requests/<id>/diff#L<path>T<start>
           file: https://bitbucket.org/<ws>/<r>/pull-requests/<id>/diff#chg-<path>
  A range whose END leaves the hunk is cut to the hunk's last line.

EXIT  0=ok  2=bad arguments
"""

import argparse, hashlib, json, re, sys
from urllib.parse import quote

parser = argparse.ArgumentParser()
parser.add_argument("--host", required=True, choices=["github", "bitbucket"])
parser.add_argument("--owner", required=True)
parser.add_argument("--repo", required=True)
parser.add_argument("--pr", required=True)
parser.add_argument("--commit", required=True)
parser.add_argument("--web-base", default="https://github.com")
parser.add_argument("anchors", nargs="+")
args = parser.parse_args()

# ── parse the diff: new-side line ranges shown per file ──────────────────────

hunks: dict[str, list[tuple[int, int]]] = {}
current = None
for line in sys.stdin.read().splitlines():
    if line.startswith("diff --git "):
        current = None
    elif line.startswith("+++ "):
        target = line[4:].split("\t")[0]
        current = None if target == "/dev/null" else re.sub(r"^b/", "", target)
        if current:
            hunks.setdefault(current, [])
    elif line.startswith("@@") and current:
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            start, count = int(m.group(1)), int(m.group(2) or 1)
            if count:
                hunks[current].append((start, start + count - 1))

# ── build links ──────────────────────────────────────────────────────────────

web = args.web_base.rstrip("/")


def pr_file_link(path: str) -> str:
    if args.host == "github":
        digest = hashlib.sha256(path.encode()).hexdigest()
        return f"{web}/{args.owner}/{args.repo}/pull/{args.pr}/changes#diff-{digest}"
    return f"https://bitbucket.org/{args.owner}/{args.repo}/pull-requests/{args.pr}/diff#chg-{quote(path, safe='')}"


def pr_line_link(path: str, start: int, end: int) -> str:
    if args.host == "github":
        suffix = f"R{start}" + (f"-R{end}" if end != start else "")
        return pr_file_link(path) + suffix
    return f"https://bitbucket.org/{args.owner}/{args.repo}/pull-requests/{args.pr}/diff#L{quote(path, safe='')}T{start}"


def blob_link(path: str, start: int, end: int) -> str:
    if args.host == "github":
        lines = f"L{start}" + (f"-L{end}" if end != start else "")
        return f"{web}/{args.owner}/{args.repo}/blob/{args.commit}/{path}#{lines}"
    lines = f"{start}" + (f":{end}" if end != start else "")
    return f"https://bitbucket.org/{args.owner}/{args.repo}/src/{args.commit}/{path}#lines-{lines}"


out = []
for anchor in args.anchors:
    m = re.match(r"^(.+):(\d+)(?:[-–](\d+))?$", anchor)
    if not m:
        print(f"ERROR: anchor must be path:LINE or path:START-END, got {anchor!r}", file=sys.stderr)
        sys.exit(2)
    path, start = m.group(1), int(m.group(2))
    end = int(m.group(3) or start)
    file_hunks = hunks.get(path)
    hunk = next((h for h in file_hunks or [] if h[0] <= start <= h[1]), None)
    if hunk:
        link_end = min(end, hunk[1])
        pr = pr_line_link(path, start, link_end)
    else:
        pr = pr_file_link(path) if file_hunks is not None else None
    blob = blob_link(path, start, end)
    out.append({
        "anchor": anchor, "path": path, "start": start, "end": end,
        "in_diff": file_hunks is not None, "in_hunk": hunk is not None,
        "link": pr or blob,
        "pr_link": pr, "blob_link": blob,
    })

print(json.dumps(out, indent=2))
