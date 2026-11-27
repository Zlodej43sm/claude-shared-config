#!/usr/bin/env python3
"""
activity — collect your git and Claude Code activity in a repo, for one day (day mode,
the `daily-status` skill) or over a date range (range mode, the `demo-recap` skill).

SCHEMA_IN
  argv  [DATE]          day mode: yesterday (default) | today | -N (N days ago) | YYYY-MM-DD
        --from DATE     range mode, first day, inclusive (default: 6 days before --to)
        --to DATE       range mode, last day, inclusive (default today)
                        Either flag turns range mode on; it cannot be combined with [DATE].
        --repo PATH     repo to report on (default: git top level of the cwd)
        --author TEXT   git author to match (default: `git config user.email`)
        --lookback N    day mode: when DATE was not given and that day has no activity, step
                        back up to N days to the last day that has some (default 7; 0 = off)
        --max-prompts N prompts kept per session and day (default 15 day mode, 5 range mode)
  env   JIRA_WORKSPACE  optional Jira project key; with it, lower-case keys in branch names
                        are read only for this project (feature/more-123-x -> MORE-123)

SCHEMA_OUT (range mode)  stdout JSON, oldest first
  { "repo", "author", "from", "to", "active_days": [YYYY-MM-DD],
    "git":    {"commits": [{date, time, sha, subject, body, refs, files_changed, insertions,
                            deletions}], "branches_touched": [names]},
    "claude": {"sessions": [{id, title, dates: [YYYY-MM-DD], branches, prompts, commands,
                             files_edited, open_todos (latest day), done_todos, last_reply,
                             started_in}]},
    "totals": {commits, sessions, files_changed, insertions, deletions},
    "now":    {branch, uncommitted, unpushed, recent_branches, recent_plans},
    "tickets" }                                 (fields as in day mode)

SCHEMA_OUT (day mode)  stdout JSON
  { "repo", "author", "requested_date", "date", "fell_back": bool,
    "git": {
      "commits":  [{sha, time, subject, body, refs, files_changed, insertions, deletions}],
      "branches_touched": [branch names checked out / committed to that day],
      "reflog":   [{time, action}]              (HEAD moves that day, newest first)
    },
    "claude": {
      "sessions": [{id, title, branches, start, end, prompts: [text], commands: [/name],
                    files_edited: [path], open_todos: [text], done_todos: [text],
                    last_reply: text}]
    },
    "now": {                                    (current state, for "next steps")
      "branch", "uncommitted": [porcelain lines], "unpushed": {branch: n},
      "recent_branches": [{name, last_commit}], "recent_plans": [path],
      "since": {"sessions": [{title, branches, prompts}], "commits": [subject]}
                                                (activity after DATE, up to now)
    },
    "tickets": {KEY: [where it was seen: branch | commit | title | prompt | reply]} }
  Times are local. Text fields are truncated. Read-only: runs git and reads
  ~/.claude/projects/*.jsonl; writes nothing.

EXIT  0=ok  1=bad args / not a git repo / --from after --to
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,14})-(\d{1,6})\b")
NOT_TICKETS = {"UTF", "SHA", "ISO", "RFC", "HTTP", "TLS", "SSL", "CVE", "ES", "GPT",
               "MD5", "AES", "RSA", "ECMA", "IEEE", "WCAG", "PEP", "X", "COVID", "CLAUDE"}
STAT_RE = re.compile(r"^\s*\d+ files? changed")
# Branch names are often lower case: feature/proj-123-retry.
BRANCH_KEY_RE = re.compile(r"(?:^|[/_-])([a-z][a-z0-9]{1,9})-(\d{1,6})(?=$|[/_-])", re.I)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def run(args: list[str], cwd: str) -> str:
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    except OSError:  # missing --repo directory, git not installed
        return ""
    return r.stdout if r.returncode == 0 else ""


def clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def parse_date(raw: str | None, today: dt.date) -> dt.date:
    if raw in (None, "", "yesterday"):
        return today - dt.timedelta(days=1)
    if raw == "today":
        return today
    if re.fullmatch(r"-\d+", raw):
        return today - dt.timedelta(days=int(raw[1:]))
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        sys.stderr.write(f"ERROR: bad date {raw!r}: use yesterday, today, -N or YYYY-MM-DD\n")
        raise SystemExit(1)


def day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time.min).astimezone()
    return start, start + dt.timedelta(days=1)


def local_time(iso: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return None


# ------------------------------------------------------------------------- git

def git_commits(repo: str, author: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    sep, rec = "\x1f", "\x1e"
    out = run(["git", "log", "--exclude=refs/stash", "--all", "--no-merges", f"--author={author}",
               f"--since={start.isoformat()}", f"--until={end.isoformat()}",
               "--date=format-local:%H:%M", "--shortstat",
               f"--format={rec}%h{sep}%ad{sep}%s{sep}%b{sep}%D"], repo)
    commits = []
    for chunk in out.split(rec)[1:]:
        lines = chunk.rstrip("\n").split("\n")
        stat = lines.pop() if lines and STAT_RE.match(lines[-1]) else ""
        parts = "\n".join(lines).split(sep)
        if len(parts) < 5:
            continue
        sha, time, subject, body, refs = parts[:5]
        nums = {k: int(v) for v, k in re.findall(r"(\d+) (file|insertion|deletion)", stat)}
        commits.append({"sha": sha, "time": time, "subject": subject.strip(),
                        "body": clip(body, 400), "refs": refs.strip(),
                        "files_changed": nums.get("file", 0),
                        "insertions": nums.get("insertion", 0),
                        "deletions": nums.get("deletion", 0)})
    return commits


def git_reflog(repo: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    out = run(["git", "log", "-g", "--date=iso-strict", "--format=%gd\x1f%gs", "HEAD"], repo)
    entries = []
    for line in out.splitlines():
        sel, _, action = line.partition("\x1f")
        m = re.search(r"\{(.+)\}", sel)
        when = local_time(m.group(1)) if m else None
        if when and start <= when < end:
            entries.append({"time": when.strftime("%H:%M"), "action": clip(action, 160)})
    return entries


def branches_from(reflog: list[dict], commits: list[dict]) -> list[str]:
    seen: dict[str, None] = {}
    for e in reflog:
        m = re.match(r"checkout: moving from (\S+) to (\S+)", e["action"])
        if m:
            seen.setdefault(m.group(2))
    for c in commits:
        for ref in c["refs"].split(","):
            ref = ref.replace("HEAD -> ", "").strip()
            if ref and not ref.startswith("tag:") and not ref.startswith("origin/HEAD"):
                seen.setdefault(ref.removeprefix("origin/"))
    return [b for b in seen if not re.fullmatch(r"[0-9a-f]{7,40}", b)]


def git_now(repo: str, author: str, since: dt.datetime) -> dict:
    branch = run(["git", "branch", "--show-current"], repo).strip()
    uncommitted = run(["git", "status", "--porcelain"], repo).splitlines()
    unpushed = {}
    for line in run(["git", "for-each-ref", "--format=%(refname:short)\x1f%(upstream:track)",
                     "refs/heads"], repo).splitlines():
        name, _, track = line.partition("\x1f")
        m = re.search(r"ahead (\d+)", track)
        if m:
            unpushed[name] = int(m.group(1))
    recent = []
    for line in run(["git", "for-each-ref", "--sort=-committerdate", "--count=6",
                     "--format=%(refname:short)\x1f%(committerdate:relative)", "refs/heads"],
                    repo).splitlines():
        name, _, when = line.partition("\x1f")
        recent.append({"name": name, "last_commit": when})
    plans_dir = Path(repo, ".claude", "plans")
    plans = []
    if plans_dir.is_dir():
        files = sorted(plans_dir.glob("**/*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        plans = [str(p.relative_to(repo)) for p in files[:5]]
    later = run(["git", "log", "--exclude=refs/stash", "--all", "--no-merges", f"--author={author}",
                 f"--since={since.isoformat()}", "--format=%s"], repo).splitlines()
    return {"branch": branch, "uncommitted": uncommitted[:30], "unpushed": unpushed,
            "recent_branches": recent, "recent_plans": plans, "since_commits": later[:20]}


# ---------------------------------------------------------------------- claude

def encode(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def transcript_files(repo: str) -> list[Path]:
    """Sessions started in the repo, in a subdirectory or worktree of it (prefix match),
    or in a parent directory such as a workspace root holding several repos (exact match;
    such a session counts only when it touched the repo, see read_sessions)."""
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return []
    own = encode(repo)
    parents = {encode(str(p)) for p in Path(repo).parents if p != Path(p.anchor)}
    dirs = [d for d in root.iterdir()
            if d.is_dir() and (d.name.startswith(own) or d.name in parents)]
    return [f for d in dirs for f in d.glob("*.jsonl")]


def user_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def clean_prompt(text: str) -> str:
    """Drop what Claude Code adds around a typed prompt; a pasted block becomes [pasted]."""
    text = re.sub(r"<pasted_content\b[^>]*>.*?(?:</pasted_content\b[^>]*>|$)", "[pasted]", text, flags=re.S)
    text = re.sub(r"<(system-reminder|widget_context_hint|[a-z_-]+-hint)\b[^>]*>.*?</\1>", "", text, flags=re.S)
    if text.strip() == "[pasted]" or text.lstrip().startswith(("This session is being continued", "<")):
        return ""
    return text


def inside(path: str, repo: str) -> bool:
    return path == repo or path.startswith(repo + os.sep)


def touches_repo(inp: dict, repo: str, cwd: str) -> bool:
    """A tool call made from a parent directory refers to the repo by absolute or
    cwd-relative path (`talon-one-webhook/src/...`, `cd talon-one-webhook && ...`)."""
    text = json.dumps(inp, ensure_ascii=False)
    rel = os.path.relpath(repo, cwd) if cwd else ""
    return repo in text or bool(rel and re.search(rf"(?:^|[\s\"'/=]){re.escape(rel)}(?:[/\s\"']|$)", text))


def read_sessions(repo: str, start: dt.datetime, end: dt.datetime, max_prompts: int) -> list[dict]:
    sessions = []
    for path in transcript_files(repo):
        if dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone() < start:
            continue  # last written before the day began
        s = {"id": path.stem, "title": "", "branches": [], "start": None, "end": None,
             "prompts": [], "commands": [], "files_edited": [], "todos": None,
             "last_reply": "", "started_in": ""}
        ai_title = custom_title = ""
        touched = False
        try:
            lines = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with lines:
            for line in lines:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = d.get("type")
                if kind == "custom-title":
                    custom_title = d.get("customTitle") or d.get("title") or custom_title
                    continue
                if kind in ("ai-title", "summary"):
                    ai_title = d.get("aiTitle") or d.get("summary") or ai_title
                    continue
                when = local_time(d.get("timestamp", ""))
                if not when or not (start <= when < end) or d.get("isSidechain"):
                    continue
                cwd = d.get("cwd") or ""
                parent = bool(cwd) and inside(repo, cwd) and cwd != repo
                if cwd and not inside(cwd, repo) and not parent:
                    continue
                if parent:
                    s["started_in"] = cwd
                s["start"] = s["start"] or when
                s["end"] = when
                br = d.get("gitBranch")
                if not parent and br and br != "HEAD" and br not in s["branches"]:
                    s["branches"].append(br)
                msg = d.get("message") or {}
                if kind == "user" and msg.get("role") == "user":
                    origin = (d.get("origin") or {}).get("kind")
                    if origin not in (None, "human") or d.get("isMeta") or d.get("isCompactSummary"):
                        continue
                    text = user_text(msg)
                    cmd = re.search(r"<command-name>(/?[\w:.-]+)</command-name>", text)
                    if cmd:
                        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
                        name = "/" + cmd.group(1).lstrip("/")
                        s["commands"].append(clip(f"{name} {args.group(1) if args else ''}", 160))
                    elif len(s["prompts"]) < max_prompts and (text := clean_prompt(text)).strip():
                        s["prompts"].append(clip(text, 300))
                elif kind == "assistant":
                    for b in msg.get("content") or []:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and b.get("text", "").strip():
                            s["last_reply"] = b["text"]
                        elif b.get("type") == "tool_use":
                            inp = b.get("input") or {}
                            if parent and not touched:
                                touched = touches_repo(inp, repo, cwd)
                            if b.get("name") in EDIT_TOOLS:
                                fp = inp.get("file_path") or inp.get("notebook_path") or ""
                                if not inside(fp, repo):
                                    continue  # another repo of the workspace, ~/.claude, ...
                                rel = os.path.relpath(fp, repo)
                                if rel not in s["files_edited"]:
                                    s["files_edited"].append(rel)
                            elif b.get("name") == "TodoWrite" and isinstance(inp.get("todos"), list):
                                s["todos"] = inp["todos"]
        if s["started_in"] and not touched:
            continue  # a parent-directory session that never worked in this repo
        s["title"] = custom_title or ai_title
        if not s["start"]:
            continue
        todos = s.pop("todos") or []
        s["open_todos"] = [clip(t.get("content", ""), 160) for t in todos
                           if isinstance(t, dict) and t.get("status") != "completed"]
        s["done_todos"] = [clip(t.get("content", ""), 160) for t in todos
                           if isinstance(t, dict) and t.get("status") == "completed"]
        s["last_reply"] = clip(s["last_reply"], 700)
        s["files_edited"] = s["files_edited"][:15]
        s["start"], s["end"] = s["start"].strftime("%H:%M"), s["end"].strftime("%H:%M")
        sessions.append(s)
    sessions.sort(key=lambda x: x["start"])
    return sessions


# --------------------------------------------------------------------- tickets

def find_tickets(report: dict, workspace: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = defaultdict(list)

    def scan(text: str, where: str) -> None:
        for prefix, num in TICKET_RE.findall(text or ""):
            if prefix in NOT_TICKETS and prefix != workspace:
                continue
            key = f"{prefix}-{num}"
            if where not in found[key]:
                found[key].append(where)

    def scan_branch(name: str) -> None:
        for prefix, num in BRANCH_KEY_RE.findall(name or ""):
            prefix = prefix.upper()
            if (workspace and prefix != workspace) or (not workspace and prefix in NOT_TICKETS):
                continue
            key = f"{prefix}-{num}"
            if "branch" not in found[key]:
                found[key].append("branch")

    for b in report["git"]["branches_touched"]:
        scan_branch(b)
    for c in report["git"]["commits"]:
        scan(f"{c['subject']} {c['body']} {c['refs']}", "commit")
    for s in report["claude"]["sessions"]:
        scan(s["title"], "title")
        for br in s["branches"]:
            scan_branch(br)
        for p in s["prompts"] + s["commands"]:
            scan(p, "prompt")
        scan(s["last_reply"], "reply")
    return dict(found)


def has_activity(r: dict) -> bool:
    return bool(r["git"]["commits"] or r["claude"]["sessions"]
                or any(not e["action"].startswith("checkout:") for e in r["git"]["reflog"]))


def collect(repo: str, author: str, day: dt.date, max_prompts: int) -> dict:
    start, end = day_bounds(day)
    commits = git_commits(repo, author, start, end)
    reflog = git_reflog(repo, start, end)
    return {"date": day.isoformat(),
            "git": {"commits": commits, "branches_touched": branches_from(reflog, commits),
                    "reflog": reflog[:40]},
            "claude": {"sessions": read_sessions(repo, start, end, max_prompts)}}


def merge_session(into: dict, s: dict, day: str, max_prompts: int) -> None:
    """Fold one day of a session that spans several days into its range entry."""
    into["dates"].append(day)
    into["title"] = s["title"] or into["title"]
    for key in ("branches", "commands", "files_edited"):
        into[key] += [v for v in s[key] if v not in into[key]]
    into["prompts"] += s["prompts"][:max(max_prompts * 3 - len(into["prompts"]), 0)]
    into["done_todos"] += [t for t in s["done_todos"] if t not in into["done_todos"]]
    into["open_todos"] = s["open_todos"]  # the latest day's list is the current one
    into["last_reply"] = s["last_reply"] or into["last_reply"]


def collect_range(repo: str, author: str, first: dt.date, last: dt.date, max_prompts: int) -> dict:
    commits, branches, sessions, active = [], {}, {}, []
    day = first
    while day <= last:
        r, iso = collect(repo, author, day, max_prompts), day.isoformat()
        if r["git"]["commits"] or r["claude"]["sessions"]:
            active.append(iso)
        commits += [{"date": iso, **c} for c in reversed(r["git"]["commits"])]  # oldest first
        branches.update(dict.fromkeys(r["git"]["branches_touched"]))
        for s in r["claude"]["sessions"]:
            if s["id"] in sessions:
                merge_session(sessions[s["id"]], s, iso, max_prompts)
            else:
                sessions[s["id"]] = {**{k: v for k, v in s.items() if k not in ("start", "end")},
                                     "dates": [iso]}
        day += dt.timedelta(days=1)
    return {"from": first.isoformat(), "to": last.isoformat(), "active_days": active,
            "git": {"commits": commits, "branches_touched": list(branches)},
            "claude": {"sessions": list(sessions.values())},
            "totals": {"commits": len(commits), "sessions": len(sessions),
                       **{k: sum(c[k] for c in commits)
                          for k in ("files_changed", "insertions", "deletions")}}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("date", nargs="?")
    ap.add_argument("--from", dest="first")
    ap.add_argument("--to", dest="last")
    ap.add_argument("--repo")
    ap.add_argument("--author")
    ap.add_argument("--lookback", type=int, default=7)
    ap.add_argument("--max-prompts", type=int)
    a = ap.parse_args()
    range_mode = bool(a.first or a.last)
    if range_mode and a.date:
        sys.stderr.write("ERROR: give a DATE or --from/--to, not both\n")
        return 1

    repo = run(["git", "rev-parse", "--show-toplevel"], a.repo or os.getcwd()).strip()
    if not repo:
        sys.stderr.write("ERROR: not inside a git repository (use --repo PATH)\n")
        return 1
    repo = os.path.realpath(repo)
    author = a.author or run(["git", "config", "user.email"], repo).strip() \
        or run(["git", "config", "user.name"], repo).strip()
    today = dt.date.today()
    workspace = os.environ.get("JIRA_WORKSPACE", "").strip().upper()

    if range_mode:
        last = parse_date(a.last or "today", today)
        first = parse_date(a.first, today) if a.first else last - dt.timedelta(days=6)
        if first > last:
            sys.stderr.write(f"ERROR: --from {first} is after --to {last}\n")
            return 1
        out = {"repo": repo, "author": author,
               **collect_range(repo, author, first, last, a.max_prompts or 5)}
        now = git_now(repo, author, day_bounds(last)[1])
        now.pop("since_commits")
        out["now"] = now
        out["tickets"] = find_tickets(out, workspace)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0

    a.max_prompts = a.max_prompts or 15
    requested = parse_date(a.date, today)

    day, report = requested, collect(repo, author, requested, a.max_prompts)
    if a.date is None and not has_activity(report):
        for back in range(1, max(a.lookback, 0) + 1):
            candidate = requested - dt.timedelta(days=back)
            r = collect(repo, author, candidate, a.max_prompts)
            if has_activity(r):
                day, report = candidate, r
                break

    after = day_bounds(day)[1]
    now = git_now(repo, author, after)
    since_sessions = [] if day >= today else [
        {"title": s["title"], "branches": s["branches"], "prompts": s["prompts"][:5],
         "open_todos": s["open_todos"]}
        for s in read_sessions(repo, after, dt.datetime.now().astimezone() + dt.timedelta(minutes=1), 5)]
    now["since"] = {"sessions": since_sessions, "commits": now.pop("since_commits")}

    out = {"repo": repo, "author": author, "requested_date": requested.isoformat(),
           "date": day.isoformat(), "fell_back": day != requested, **report, "now": now}
    out["tickets"] = find_tickets(out, workspace)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
