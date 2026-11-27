#!/usr/bin/env python3
"""
activity_range — collect your git and Claude Code activity in a repo over a date range,
as raw material for a recap demo (the `demo-recap` skill). Day-level collection is
`daily_activity.collect`; this script loops it over the range and merges the result.

SCHEMA_IN
  argv  --from DATE     first day, inclusive (default -6: the last 7 days with today)
        --to DATE       last day, inclusive (default today)
                        DATE = today | yesterday | -N (N days ago) | YYYY-MM-DD
        --repo PATH     repo to report on (default: git top level of the cwd)
        --author TEXT   git author to match (default: `git config user.email`)
        --max-prompts N prompts kept per session per day (default 5)

SCHEMA_OUT  stdout JSON
  { "repo", "author", "from", "to", "active_days": [YYYY-MM-DD],
    "commits":  [{date, time, sha, subject, body, refs, files_changed, insertions, deletions}],
    "branches_touched": [names],
    "sessions": [{id, title, dates: [YYYY-MM-DD], branches, prompts: [text], commands: [/name],
                  files_edited: [path], done_todos: [text], open_todos: [text],
                  last_reply: text}],
    "totals": {commits, sessions, files_changed, insertions, deletions} }
  Oldest first. Times are local. Text fields are truncated. Read-only: runs git and
  reads ~/.claude/projects/*.jsonl; writes nothing.

EXIT  0=ok  1=bad args / not a git repo / --from after --to
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from daily_activity import collect, parse_date, run


def merge_session(into: dict, s: dict, day: str, max_prompts: int) -> None:
    into["dates"].append(day)
    into["title"] = s["title"] or into["title"]
    for key in ("branches", "commands", "files_edited"):
        into[key] += [v for v in s[key] if v not in into[key]]
    room = max_prompts * 3 - len(into["prompts"])
    into["prompts"] += s["prompts"][:max(room, 0)]
    into["done_todos"] += [t for t in s["done_todos"] if t not in into["done_todos"]]
    into["open_todos"] = s["open_todos"]  # the latest day's list is the current one
    into["last_reply"] = s["last_reply"] or into["last_reply"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", default="-6")
    ap.add_argument("--to", dest="end", default="today")
    ap.add_argument("--repo")
    ap.add_argument("--author")
    ap.add_argument("--max-prompts", type=int, default=5)
    a = ap.parse_args()

    repo = run(["git", "rev-parse", "--show-toplevel"], a.repo or os.getcwd()).strip()
    if not repo:
        sys.stderr.write("ERROR: not inside a git repository (use --repo PATH)\n")
        return 1
    repo = os.path.realpath(repo)
    author = a.author or run(["git", "config", "user.email"], repo).strip() \
        or run(["git", "config", "user.name"], repo).strip()
    today = dt.date.today()
    first, last = parse_date(a.start, today), parse_date(a.end, today)
    if first > last:
        sys.stderr.write(f"ERROR: --from {first} is after --to {last}\n")
        return 1

    commits, branches, sessions, active = [], {}, {}, []
    day = first
    while day <= last:
        r = collect(repo, author, day, a.max_prompts)
        iso = day.isoformat()
        if r["git"]["commits"] or r["claude"]["sessions"]:
            active.append(iso)
        # git log lists newest first; keep the range oldest first
        commits += [{"date": iso, **c} for c in reversed(r["git"]["commits"])]
        branches.update(dict.fromkeys(r["git"]["branches_touched"]))
        for s in r["claude"]["sessions"]:
            merged = sessions.setdefault(s["id"], {
                "id": s["id"], "title": "", "dates": [], "branches": [], "prompts": [],
                "commands": [], "files_edited": [], "done_todos": [], "open_todos": [],
                "last_reply": ""})
            merge_session(merged, s, iso, a.max_prompts)
        day += dt.timedelta(days=1)

    out = {"repo": repo, "author": author, "from": first.isoformat(), "to": last.isoformat(),
           "active_days": active, "commits": commits, "branches_touched": list(branches),
           "sessions": list(sessions.values()),
           "totals": {"commits": len(commits), "sessions": len(sessions),
                      **{k: sum(c[k] for c in commits)
                         for k in ("files_changed", "insertions", "deletions")}}}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
