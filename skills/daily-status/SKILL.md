---
name: daily-status
description: Prepare your daily stand-up status from your own git and Claude Code activity in the current repo - per ticket (key, short Jira summary, what was done, what is next), blockers, and a 30-second version to read out. Default day is yesterday (on a day with no activity, the last active day before it); any past day can be asked for. Read-only; posts nothing. Use when asked for a "daily status", "stand-up update", "daily update", "what did I do yesterday" or "what did I do on <day>". Usage: /daily-status [yesterday | today | -N | YYYY-MM-DD | <weekday> | "last friday"] [--repo=<path>]... [--author=<email>] [--no-jira]
---

# daily-status — what I did, what I'll do next

The reader is the team at stand-up. They want tickets and outcomes, not commits, SHAs or file names.

## Input (`args`)

- No date: yesterday. If yesterday has no activity (a weekend, a day off), the collector steps back to the last
  day that has some, up to 7 days.
- A date: `today`, `yesterday`, `-N` (N days ago), `YYYY-MM-DD`, or words such as `friday`, `last tuesday`,
  `20 nov`. Turn words into `YYYY-MM-DD` yourself from today's date (a bare weekday means the most recent past
  one). An explicit date is reported as is, even when empty.
- `--repo=<path>`: report on that repo instead of the current one. Give it more than once to cover several repos
  in one status (for example, repos of one workspace).
- `--author=<email>`: the git author to match. Default `git config user.email` of the repo.
- `--no-jira`: skip the Jira lookup.

## Step 1 — collect the activity

```bash
eval "$(python3 .claude/tools/env_exports.py)"   # JIRA_WORKSPACE, JIRA_BASE_URL; fine if .claude/.env is absent
python3 .claude/tools/daily_activity.py [<YYYY-MM-DD | -N | today>] [--repo <path>] [--author <email>]
```

Pass no date argument when the user gave none, so the fallback to the last active day works. Run the collector once
per `--repo`. The output schema is in the script's header (`tools/daily_activity.py`). In short:

- `git.commits`, `git.branches_touched`, `git.reflog` — your commits on all branches, checkouts, rebases and pulls
  on that day.
- `claude.sessions` — every Claude Code session that day in the repo, including sessions started in a parent
  directory (a workspace root) that worked in the repo (`started_in`). Each has a title, branches, your prompts,
  slash commands, files edited, open and done todos, and the last reply.
- `now` — the current branch, uncommitted files, unpushed commits, recent branches and `.claude/plans/`, and
  `since`: commits and sessions after the reported day, up to now.
- `tickets` — Jira-looking keys and where each was seen (`branch`, `commit`, `title`, `prompt`).

Exit `1` means a bad date or not a git repo: say so in one line and stop. If `fell_back` is true, start the status
with "No activity on <requested_date>; showing <date>, the last active day." If there are sessions but no commits
and the user expected some, mention `--author` (commits may use another email).

## Step 2 — look up the tickets

Skip with `--no-jira`. Take the keys from `tickets`, plus keys in plan file names (`now.recent_plans`) and in
`now.since`, at most 8. A key seen only in a prompt (often a pasted message) counts only when the session clearly
worked on it.

Fetch each key's summary and status in parallel, using the access order in `agents/jira-context.md` → "Access
paths" (hosted Atlassian MCP `getJiraIssue`, then `mcp__atlassian__jira_get_issue`, then
`python3 .claude/tools/atlassian_fetch.py jira <KEY>`). Only the summary and status are needed: no description,
comments or Confluence pages. If no path works, take the short description from the branch name, the commit
subjects or the session title, and add one line at the end: "Jira not reached — ticket titles are guessed from
branches and commits."

## Step 3 — build the picture per ticket

Group all activity under tickets. A session or commit belongs to a ticket when its branch, title, commit text or
plan file names the key, or when it edited the same files as that ticket's commits. Everything else goes under
**Other**, and only if it is worth saying at stand-up (an investigation, a review, a production check, a doc).
Leave out sessions that only tuned tooling or asked a one-line question, and sessions that were themselves a
status request: their reply describes an earlier day.

**Done** — outcomes, in plain words. Commits say what changed. Sessions without commits are still work:
investigation, root cause found, plan written, PR reviewed, job run on UAT, support question answered. Read the
session titles, prompts and `last_reply` to find the outcome ("merged as PR #…", "found the cause…"). One line
per ticket, two at most.

**Next** — use the evidence in this order, and never invent work:

1. `now.since` — what you already started after the reported day (for "yesterday", that is today so far).
2. `open_todos` of the last session on the ticket.
3. Next steps or open questions at the end of `last_reply`.
4. Git state: unpushed commits or uncommitted files on a ticket's branch → "finish and push", "open the PR".
5. A plan in `now.recent_plans` with steps left, and the Jira status (In Review → address review comments;
   In Progress → continue).

A ticket with no evidence of next steps gets no **Next** line. If nothing at all is found, write
"Next: (fill in)".

**Blockers** — only with evidence: a prompt or reply that says waiting for someone, access missing, an environment
down, a failing pipeline that is not yours. Otherwise "none".

## Step 4 — write the status

Plain, short English, first person, past tense for Done and future for Next. No SHAs, file paths, line counts or
branch names. Ticket key first, then the Jira summary cut to about 8 words. Do not quote prompts: they can hold
pasted Slack messages, customer data, names or secrets. Use the outcome only.

```
**Daily status — <Weekday, DD Mon> · <repo name(s)>**

**Done**
- **<KEY>** — <short summary> (<status>): <what was done>.
- **Other**: <what was done>.

**Next**
- **<KEY>** — <short summary>: <next step>.

**Blockers**: <none | the blocker>.

**30 seconds**
> <Yesterday | On <weekday>> I <done, by ticket, in 2–3 sentences>. <Today> I'll <next>. <No blockers | blocker>.
```

The **30 seconds** paragraph is at most 80 words (about 30 seconds read aloud). It names each ticket by key and a
few words, not by its full summary. When the reported day is not yesterday, say "On <weekday>" instead of
"Yesterday". When the reported day is today, Done is "so far today" and Next is "for the rest of the day".

End with one line: `Sources: <n> commits, <m> Claude sessions<, Jira: <oauth|mcp|rest|not reached>>.` If any
**Next** item came from steps 2–5 above rather than from `now.since`, add: "Next is inferred from open todos and
the last session — check it."

## Constraints

- Read-only. The collector runs git read commands and reads `~/.claude/projects/*.jsonl`; Jira is read with GETs
  only. Nothing is written, committed or posted. To share the status, the user copies it.
- Only your activity: commits are filtered by author, sessions are your local Claude Code sessions.
- Sub-agent work (`isSidechain`) is skipped; the main session's prompts and replies already describe it.
