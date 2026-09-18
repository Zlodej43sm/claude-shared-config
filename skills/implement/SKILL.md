---
name: implement
description: Architect/staff-dev skill — fetches a Jira ticket and all linked Confluence docs, reads related repos if provided, prepares a detailed implementation plan in .claude/plans/, then asks the user to approve or modify before any code is written.
---

# implement — plan-first feature implementation

You are the entry point. Your job is to gather full context, delegate planning to the `feature-planner` subagent, surface the plan for human review, and then — only after explicit approval — start implementing.

**You write no production code in this skill.** Code writing begins only when the user approves the plan.

## Input

`args` format: `<ticket-key> [-- <repo1> [<repo2> ...]]`

- `<ticket-key>` — Jira issue key, e.g. `$JIRA_WORKSPACE-16` or bare number `16` (prepend `$JIRA_WORKSPACE-`).
- `--` followed by one or more **local repo paths** of related microservices/sibling packages. Optional.

Parse: everything before `--` is the ticket key; everything after is the related_repos list. If no `--`, related_repos is empty.

## Step 0 — Load env and validate

```bash
set -a; . ./.claude/.env; set +a
```

Required: `JIRA_WORKSPACE`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.
Optional: `CONFLUENCE_BASE_URL`.

If any required key is missing or has a placeholder value (`replace-with-...`, `your-...`), tell the user which key to set and stop.

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

## Step 2 — Generate the plan via `feature-planner` agent

Spawn the `feature-planner` subagent. Embed the full context block from Step 1 directly in the prompt.

```
Prepare an implementation plan for the following ticket.

Values:
  plan_dir:      <absolute path>/.claude/plans
  project_root:  <absolute path>

--- BEGIN JIRA CONTEXT ---
<paste the full context block verbatim here>
--- END JIRA CONTEXT ---

Run your full planning procedure (Steps 1–5) and return PLAN_PATH followed by the full plan content.
```

The subagent writes the plan file and returns `PLAN_PATH: <path>` followed by the plan content. Extract the path from the `PLAN_PATH:` line.

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

Read the plan file. Find the **QA commands** table in the plan — it contains the exact type-check, lint, test, and build commands derived from CLAUDE.md for this project. Use those commands verbatim throughout implementation; never substitute generic defaults.

For each `- [ ]` task in the **Step-by-step tasks** section, execute it in order:

1. Create or modify the file(s) named in the task using Edit/Write tools.
2. After each file is written, run the type-checker command from the QA table, then the lint command. Fix any errors before moving to the next task.
3. After all source tasks are done, run the test command from the QA table.
4. Fix failing tests before declaring done. If a build command is listed (not "n/a"), run it last.
5. Mark each task `- [x]` in the plan file as it completes (update the file with Edit).

When all tasks pass: report a completion summary — which files were created/modified, test results, and any open questions that remain unanswered.

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
- **No inventing file paths.** The `feature-planner` agent confirms paths via Read/Glob. Trust its output.
