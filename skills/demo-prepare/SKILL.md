---
name: demo-prepare
description: Prepare a live demo of a finished change (a PR, a branch or a ticket) - a speech plan with timed cues, verified commands, the pictures as a self-contained HTML page (no SVG or PNG files), likely questions with answers and a fallback. Reads the diff, the plan and the ticket's acceptance criteria, picks what can be shown live, dry-runs every command before writing it down, and writes in short, plain English for non-native speakers. Use when asked to "prepare a demo", "demo speech", "demo plan" or "slides/schema for the demo". Generic - project facts come from the repo. Writes only the demo folder; never commits, pushes or posts unless asked. Usage: /demo-prepare [<pr-number | branch | ticket-key>] [--minutes=<n>] [--out=<dir>]
---

# demo-prepare — a demo that runs the first time

The audience is the team and product people: they want to see what changed and why it matters, not the diff.
Every command in the plan has been run once before it is written down.

## Input (`args`)

- Empty: the current branch against its PR destination (or the default branch).
- `<pr-number | branch | ticket-key>`: that change.
- `--minutes=<n>`: speech length (default 4).
- `--out=<dir>`: output folder (default below).

## Step 1 — what changed and what matters

1. Scope: `git diff <base>...HEAD`, the commits, the PR description, the plan in `.claude/plans/` if there is one,
   and the ticket's acceptance criteria (`get-jira-task` when a key is known).
2. List the behaviours a listener can notice. For each, mark how to show it: **live** (a command or a UI action
   with visible output), **test** (a test run whose names read like the rule), **picture** (only a diagram can show
   it), or **skip** (internal, nothing to see).
3. Separate what ships in this change from what comes later (next PRs, follow-up tickets). The pictures show both,
   marked differently.
4. Read the last demo the team gave in this repo or a sibling (a `docs/DEMO.md` or an earlier demo folder), if
   one exists, and follow its layout and tone.

## Step 2 — choose the steps

- 4 to 7 steps, each under a minute, in the order the story needs: context, then the happy path, then the safety
  rules, then the hard part.
- Prefer real output over tests, and tests over slides. Use the project's own scripts (`package.json`, `Makefile`).
  A short helper script goes in the demo folder, never in the product code.
- Each step needs one visible sign of success ("you should see"). Avoid steps that need network access, real
  secrets, or a service that is not running locally.
- Never put a secret value in the plan. When `.env` is missing something, give the command that creates a
  throwaway value.

## Step 3 — dry-run everything

Run every preparation and demo command once, in the order of the plan, on the demo branch. Record what each one
prints. If a command fails, fix the plan (or a missing local setting), not the product code. Stop any server you
started. Note the date of the dry run in the plan.

## Step 4 — the pictures (HTML only)

One self-contained `schema.html` holding one or more slides:

- Plain HTML and inline CSS: boxes in CSS grid or flex, arrows as characters (`&rarr;`, `&darr;`). No SVG, no
  images, no scripts, no external fonts or CDNs. It opens offline from disk.
- One slide is 1280 x 720 CSS pixels, body text at least 17 px, titles at least 30 px.
- Slide 1: the big picture, with this change's parts marked (a legend chip with text, not colour alone) against the
  parts that come later and the other systems.
- Slide 2: what this change adds (data model, states, rules), in boxes with one short sentence each.
- Real text, `lang`, headings per slide, enough contrast. Check the result by rendering it once (headless browser);
  no screenshot is kept.

## Step 5 — write the plan

`DEMO.md` next to `schema.html`, in this shape:

1. Title with the ticket and PR, two sentences on what the audience will see, and how to open the pictures.
2. **Before the demo** (5 minutes before): numbered, copy-paste commands, including one-time setup and the dry run.
3. **Run it**: a table `Step | Terminal | Command | You should see`.
4. **Speech (about N minutes)**: each part starts with a bold cue in brackets naming the slide or the step
   (`**[Step 2: ...]**`), then 2 to 4 short sentences. Say why it matters, not how the code works. Answer, early,
   any question the team already asked during the work.
5. **Questions you may get**: a two-column table with short, true answers.
6. **If something fails live**: the quick fix per step, and the fallback (the pictures and the dry-run output).

Plain English: short sentences, active voice, no filler, no jargon a product person would not know (explain it in
five words or drop it).

## Step 6 — where it goes

- `--out`, else the repo's own demo convention (for example `docs/DEMO.md` with its pictures), else
  `.claude/demos/<ticket-or-branch-slug>/` (local, not part of the PR).
- Report the paths, the dry-run result per step, and anything the presenter must do by hand (a missing `.env`
  value, a service to start).

## What not to do

- No command in the plan that was not run in the dry run.
- No product-code changes to make a demo work; report the gap instead.
- No SVG or PNG files for the pictures, and no screenshots left behind.
- Nothing committed, pushed or posted unless the user asks.
