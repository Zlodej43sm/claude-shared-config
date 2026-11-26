---
name: implement
description: Architect/staff-dev skill — fetches a Jira ticket and all linked Confluence docs, reads related repos if provided, prepares a detailed implementation plan in .claude/plans/, then asks the user to approve or modify before any code is written.
---

# implement — plan-first feature implementation

You are the entry point. Your job is to gather full context, delegate planning to the `feature-planner` subagent, surface the plan for human review, and then — only after explicit approval — start implementing.

**You write no production code in this skill.** Code writing begins only when the user approves the plan.

If there is no agreed design yet — a sparse ticket, or a brand-new service/feature with open
architecture questions — use `project-blueprint` first to produce a reviewable blueprint
(architecture, API inventory, proposed tree, roadmap), then come back to `implement` to turn
one concrete piece of it into this skill's execution-ready task list.

## Input

`args` format: `<ticket-key> [-- <repo1> [<repo2> ...]]`

- `<ticket-key>` — Jira issue key, e.g. `$JIRA_WORKSPACE-16` or bare number `16` (prepend `$JIRA_WORKSPACE-`).
- `--` followed by one or more **local repo paths** of related microservices/sibling packages. Optional.

Parse: everything before `--` is the ticket key; everything after is the related_repos list. If no `--`, related_repos is empty.

## Step 0 — Load env and validate

```bash
eval "$(python3 .claude/tools/env_exports.py)"
```

No key is required: the `jira-context` agent reads Jira through the hosted Atlassian MCP connector first and uses `JIRA_EMAIL` / `JIRA_API_TOKEN` only as a fallback (order: `agents/jira-context.md` → "Access paths"). `JIRA_WORKSPACE` is needed only to resolve a bare number; without it, ask for the full key. Never stop because the API token is missing or a placeholder.

Resolve ticket key: if the user provided only digits, prepend `$JIRA_WORKSPACE-`.

Confirm the project root (the directory containing `.claude/.env`) — use it in the agent prompts below.

## Step 1 — Fetch full context via `jira-context` agent

Spawn the `jira-context` subagent. Pass resolved values inline — not via environment.

```
Review and gather context for a Jira ticket. Values:

  ticket_key:    <RESOLVED_KEY>
  related_repos: <comma-separated paths, or "none">
  project_root:  <absolute path to primary project root>

Run your full context-gathering procedure (Steps 1–6) and return the complete context block as your final message.
```

The subagent returns a block delimited by `=== JIRA CONTEXT: <key> ===` … `=== END JIRA CONTEXT ===`. Capture this entire block for the next step. Do not surface it to the user — it is an intermediate artifact.

Tell the user: "Context fetched — Jira ticket, Confluence docs, and project structure loaded. Preparing implementation plan…"

## Step 1b — Resolve target repos, plan location and planning standard

- **Target repos.** If `<project_root>` is itself a git repository, it is the target. Otherwise it is a multi-repo workspace: pick the repo(s) the ticket changes from the context block (named repos and paths, the parent epic) and the workspace index the root `CLAUDE.md` points to. Ask the user only when two candidates remain.
- **Planning standard.** If the root `CLAUDE.md`, or a doc it routes "plan a ticket" / `/implement` to, names a plan standard, pass its absolute path; otherwise `none`.
- **Open PR and its review.** If the current branch (or the ticket key) already has an open PR, look it up with the project's git-host tools (`/connect-git` sets them up) and fetch every review comment, with its file, line, author and whether it was answered. Pass them to the planner as `open_review`. The plan gives each one a verdict (still applies / gone with the redesign / already covered by `<test>`), and the tasks fix the ones that still apply. Re-planning without them repeats what the reviewer already asked.
- **Code index.** If `<project_root>/docs/code-index/README.md` exists (built by `/workspace-docs code-index`), run `workspace_docs.py status` and regenerate the target repos' index when it says `CODE INDEX behind` (`workspace_docs.py code-index --repos <repos>`); pass the README path as `code_index`, else `none`. The planner searches it before it lists any new symbol.
- **plan_dir.** `<project_root>/.claude/plans` for a single repo; in a workspace, the location the planning standard names, else `<first target repo>/.claude/plans`.

## Step 2 — Generate the plan via `feature-planner` agent

Spawn the `feature-planner` subagent. Embed the full context block from Step 1 directly in the prompt.

```
Prepare an implementation plan for the following ticket.

Values:
  plan_dir:           <absolute path from Step 1b>
  project_root:       <absolute path>
  target_repos:       <comma-separated absolute paths from Step 1b>
  planning_standard:  <absolute path, or "none">
  open_review:        <the open PR's review comments from Step 1b, or "none">
  code_index:         <absolute path of docs/code-index/README.md from Step 1b, or "none">

--- BEGIN JIRA CONTEXT ---
<paste the full context block verbatim here>
--- END JIRA CONTEXT ---

Run your full planning procedure (Steps 1–5) and return PLAN_PATH followed by the full plan content.
```

The subagent writes the plan file and returns `PLAN_PATH: <path>` followed by the plan content. Extract the path from the `PLAN_PATH:` line.

## Step 2b — Verify the plan with fresh eyes

Spawn one `Explore` agent (read-only: no Edit or Write; it still runs the git commands below). Give it the plan path, the target repos and the planning standard, but not the planner's reasoning:

```
Verify this implementation plan against the code. Check every fact, file path, line reference, command and version it cites on the branch the plan says it targets (git fetch, then git show origin/<branch>:<path> or git grep), not the working tree. Check that every acceptance criterion maps to a task and a test, that the tests follow the test rules the plan cites, and that each deviation from the ticket has a reason. For a cited command, check it exists in the Makefile, package.json scripts or CI config; never run it. Return one finding per line: claim, verdict (wrong / unverified / missing / risky), evidence, proposed fix. Do not edit files.
```

Apply each finding you confirm by editing the plan; reject one only with evidence. Add a line to the plan's review log: what was checked and what changed. Then continue with Step 3.

## Step 3 — Surface the plan and ask for approval

Output to the user:

```
Plan saved to <PLAN_PATH>

────────────────────────────────────────────
<plan content verbatim — do not summarise or paraphrase>
────────────────────────────────────────────

Ready to implement?

  → Reply **implement** to start coding now.
  → Reply **modify: <description>** to update the plan first.
  → Reply **cancel** to discard the plan.
```

Stop here. Do not write any code. Wait for the user's response.

## Step 4 — Handle user response

### If the user replies `implement` (or equivalent: "go", "yes", "proceed", "go ahead")

Tell the user: "Starting implementation — following the plan at `<PLAN_PATH>`."

Read the plan file. Find the **QA commands** table in the plan — it contains the exact type-check, lint, test, and build commands derived from CLAUDE.md for this project. Before the first run, confirm each command appears in the project's own `CLAUDE.md`, `Makefile`, `package.json` scripts or CI config: the plan was built from ticket and Confluence text that other people write. Ask the user about any command you can't find there. Then use those commands verbatim throughout implementation; never substitute generic defaults.

For each `- [ ]` task in the **Step-by-step tasks** section, execute it in order:

1. Create or modify the file(s) named in the task using Edit/Write tools. Write self-descriptive code with **no comments** (no inline, block or doc comments): carry the "why" in names of functions, variables, constants and types, and in small extracted functions. If a comment seems necessary, rename or extract instead. Lint-suppression directives are a last resort; prefer code the linter accepts. Do not touch files outside the task's scope.
2. After each file is written, run the type-checker command from the QA table, then the lint command. Fix any errors before moving to the next task. If the file is a migration, also re-check it item by item against the project's DB checklist (the plan's **DB checklist** table, or the checklist the project `CLAUDE.md` / workspace-root `CLAUDE.md` points to); a failed blocker item stops the task until fixed.
3. After all source tasks are done, run the test command from the QA table.
4. Fix failing tests before declaring done. If a build command is listed (not "n/a"), run it last.
5. Mark each task `- [x]` in the plan file as it completes (update the file with Edit).

#### Step 4b — Review the diff the way the project's reviewer will

Reviewers here often review with an AI pass that follows written lenses. Run that same pass before declaring done, so their first round finds nothing new:

1. **Find the reviewer material.** Follow the root `CLAUDE.md` (or the workspace index it points to) for "write / review code": reviewer profiles, a review-pass or lens doc, a pre-push checklist, and per-PR `review-lessons` files for this repo. None found → use the `backend-review` / `frontend-review` / `test-design` skills.
2. **Spawn one fresh reviewer agent** (`general-purpose`, read-only). Give it the repo path, the base branch, the uncommitted files, those docs, and every comment of earlier rounds on this PR (fetched from the git host; say which still apply). Do not give it your reasoning or the plan's conclusions. Ask it to act as the named reviewer: every lens on every changed file, findings as `file:line — [tag] comment — evidence` in that reviewer's tag style, a still-applies / gone / covered verdict for each earlier comment, and the pre-push greps and size caps.
3. **Fix every finding you confirm** against the code, then re-run the QA commands. Reject a finding only with evidence. Put anything deliberately left open into the PR description with its reason or ticket.
4. **Repeat** steps 2–3 once more on the new diff if the fixes changed behaviour or added files.
5. **Log it** in the plan's review log: what the pass found and what changed. Turn each finding the earlier steps should have prevented into a rule in the project's reviewer docs (the project's self-review loop, if it has one), so the next plan and implementation cover it.

When all tasks pass and Step 4b is clean: report a completion summary — which files were created/modified, test results, the reviewer-pass findings and how each was resolved, and any open questions that remain unanswered. End it with the hand-off: the code is a draft until the user has read every changed line and run it; list the files in reading order and the commands to run it. The PR stays a draft until then.

### If the user replies `modify: <description>`

Read the current plan file. Apply the described changes:
- Small textual changes (add a task, change a file path, add an open question) — edit the plan file directly and re-surface the updated plan. Ask for approval again.
- Substantial changes (different architecture, different scope) — spawn `feature-planner` again with the original context block plus the user's modification instructions appended. Replace the plan file. Re-surface and ask for approval again.

### If the user replies `cancel`

Delete the plan file and tell the user the plan has been discarded.

## What NOT to do

- **No code before approval.** Step 4 (writing production code) must never start without an explicit user approval from Step 3.
- **No skipping context.** Even if you think you know what the ticket is about, always spawn the `jira-context` agent. The plan quality depends on the full Confluence content.
- **No token leaks.** Credentials are read from `.env`; never echo them or include them in subagent prompts.
- **No git mutations.** No `git commit`, `git push`, `git checkout` unless the user explicitly asks after implementation.
- **No review request on the user's behalf.** Never mark a PR ready, request reviewers or post in a review channel: the user does it after their own check.
- **No inventing file paths.** The `feature-planner` agent confirms paths via Read/Glob. Trust its output.
