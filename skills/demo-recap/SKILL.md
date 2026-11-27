---
name: demo-recap
description: Prepare a short demo (2-3 minutes) of what you changed over a period - default the last 7 days - from your git and Claude Code activity, plus any extra source you name. Picks the 1-3 changes a listener would notice, reads their diffs to learn how it worked before and how it works now, and writes a timed speech, before/after pictures as one self-contained HTML page, and, only when it is cheap, a verified local run that shows it working. No ticket numbers. Use when asked for a "weekly demo", "demo of last week", "recap demo", "what did I ship this week as a demo", or "before/after slides" for a period. Writes only the demo folder; never commits or posts. Usage: /demo-recap [last week | since <day> | <from>..<to>] [--repo=<path>]... [--author=<email>] [--source=<file|url>]... [--minutes=<n>] [--no-live] [--out=<dir>]
---

# demo-recap — before, what changed, after

The audience is the team and product people. They want to see what works differently now and why it matters,
not the commits. One demo covers one period; for a single PR or branch use `demo-prepare` instead.

## Input (`args`)

- No range: the last 7 days, today included.
- A range in words or dates: `last week` (the previous Monday to Sunday), `this week`, `since monday`,
  `2026-11-01..2026-11-14`, `november`. Turn it into `--from`/`--to` dates (`YYYY-MM-DD`) yourself from today's
  date.
- `--repo=<path>`: report on that repo; give it more than once to cover several repos.
- `--author=<email>`: the git author to match. Default `git config user.email` of the repo.
- `--source=<file|url>`: extra material for the same period, such as release notes, a changelog or meeting notes.
  Read it as evidence, like the commits. Git and Claude Code activity stay the base.
- `--minutes=<n>`: speech length, 2 or 3 (default 3).
- `--no-live`: skip the live run; the pictures carry the demo.
- `--out=<dir>`: output folder (default below).

## Step 1 — collect

```bash
python3 .claude/tools/activity_range.py [--from <YYYY-MM-DD>] [--to <YYYY-MM-DD>] [--repo <path>] [--author <email>]
```

Run it once per `--repo`. The output schema is in the script's header (`tools/activity_range.py`): your commits
(oldest first, with date and size), the branches touched, and the Claude Code sessions with their dates, titles,
files edited, done and open todos, and last reply. Exit `1` means a bad date or not a git repo: say so in one line
and stop. If `totals.commits` and `totals.sessions` are both `0`, say the period is empty, suggest a wider range
or `--author`, and stop.

Prompts and replies are evidence only. Never quote them: they can hold pasted messages, customer data or secrets.

## Step 2 — pick the highlights

1. Group the commits and sessions into changes: same branch, same files, or one session title.
2. Keep 1 to 3 changes a listener would notice, in this order: a new capability, then changed behaviour, then a
   fix someone felt. Drop formatting, renames, dependency bumps, tooling-only work and one-off questions. Three
   minutes holds three highlights at most; with fewer, give each more time.
3. For each highlight, read the real diff (`git show <sha>` per commit, or
   `git diff <first-sha>^ <last-sha> -- <paths>`) and the code just before it. Write down:
   - **Before**: how it worked, as a flow of 3 to 5 steps, taken from the old code. For something new, the before
     is what people did without it (a manual step, a missing check). If the code does not show it, write "not
     there" rather than guessing.
   - **What changed**: one sentence.
   - **After**: the new flow of 3 to 5 steps, with the steps that are new or different marked.
   - **Why it matters**: one sentence, from the user's side.
4. Leave out ticket keys, SHAs, branch names and file paths everywhere: in the speech, the pictures and the
   plan.

## Step 3 — the pictures (HTML only)

One self-contained `schema.html`, built to the format rules in `demo-prepare` → Step 4 (plain HTML and inline
CSS, no SVG, images or scripts, slide size, font sizes, render check). The slides:

1. **Title**: the period and the highlights as a short list, one line each.
2. **One slide per highlight**: two columns, **Before** and **After**, each a top-down flow of boxes joined by
   `&darr;`, one short phrase per box. In the After column, mark each new or changed box with a text chip
   (`NEW`, `CHANGED`) as well as a colour. A band under both columns holds "What changed" and "Why it matters".
3. **Live run** (only when Step 5 found one): the commands and what to look for, as two short columns.

## Step 4 — the speech

At about 130 words a minute: 3 minutes is at most 390 words, 2 minutes at most 260. Each part starts with a
bold cue in brackets naming the slide or the live step (`**[Slide 2: Before / after]**`), then short sentences.

- **Opening** (15 seconds): the period and what the audience will see.
- **Per highlight**: how it worked before, what changed, how it works now, why it matters. Point at the boxes.
- **Close** (15 seconds): what comes next, only from evidence (open todos, unpushed work); else leave it out.

Plain English for non-native speakers: short sentences, active voice, no jargon a product person would not know.

## Step 5 — live run (optional)

Skip it with `--no-live`, or when no highlight can be shown in at most 3 local commands without network access,
real secrets or a service that is not running. Keep it small: one highlight, the project's own scripts, one
visible sign of success. When the contrast is the point, run the same command on the old code from a temporary
worktree (`git worktree add <scratch-dir> <first-sha>^`) and on the current code, and remove the worktree after.

Dry-run every command before writing it down, with the rules in `demo-prepare` → Step 3. If nothing qualifies,
write "No live run: the before/after slides show the change." and stop here.

## Step 6 — write it down

`DEMO.md` next to `schema.html`, in this shape:

1. Title with the period, one sentence on what the audience will see, and how to open `schema.html`.
2. **Speech (about N minutes)** from Step 4.
3. **Live run**: a table `Step | Command | You should see`, with the dry-run date; or the "No live run" line.
4. **If something fails live**: go back to the slides; one quick fix per step.
5. One last line: `Sources: <n> commits, <m> Claude sessions<, extra sources>, <from> to <to>.`

Output folder: `--out`, else `.claude/demos/recap-<from>-<to>/`. Report the paths, the highlights picked (and
the ones dropped, in one line), and the dry-run result.

## What not to do

- No ticket keys, SHAs, branch names or file paths in the speech, the slides or the plan.
- No "before" that the old code does not show.
- No command in the plan that was not run in the dry run.
- No product-code changes to make the demo work; report the gap instead.
- Nothing committed, pushed or posted unless the user asks.
