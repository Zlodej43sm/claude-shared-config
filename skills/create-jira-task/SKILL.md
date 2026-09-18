---
name: create-jira-task
description: Create one or more Jira issues (default type Task), optionally as children of a parent issue such as an Epic. Backed by .claude/tools/jira_create_child.sh and .claude/.env credentials. Usage — /create-jira-task [--parent=KEY] [--project=KEY] [--issuetype=NAME] [--dry-run]
---

# create-jira-task

Create one or more Jira issues directly via the Jira Cloud REST API (v3), using credentials from `.claude/.env`. This is a **write** operation — created issues are real, visible to the whole team, and generally cannot be hard-deleted without Jira admin rights. Treat every non-dry-run invocation as effectively permanent.

## Use When

- The user asks to file, open, or create Jira ticket(s) — including subtasks/children of an existing issue or Epic.

## Do Not Use When

- The user only wants to read or search existing issues — use `mcp__atlassian__jira_get_issue` / `mcp__atlassian__jira_search`, or the `get-jira-task` skill, instead.
- You have not yet shown the user the exact list of summaries/descriptions you're about to create and gotten explicit go-ahead in the current conversation — creation is not easily reversible, so confirm before Step 2 unless the user has already reviewed and approved the list.

## Input

```
[--parent=KEY] [--project=KEY] [--issuetype=NAME] [--dry-run]
```

- `--parent=KEY` — optional. Issue key to set as `parent` on every created item (e.g. `TASK-123`). Omit for top-level issues.
- `--project=KEY` — optional. Defaults to `$JIRA_WORKSPACE`.
- `--issuetype=NAME` — optional. Defaults to `Task`. Must be a valid issue type name for the target project (if unsure, cross-check an existing sibling issue's `issuetype.name` via `mcp__atlassian__jira_get_issue` first).
- `--dry-run` — print the built payload for every item without creating anything.

The actual items (one `{summary, description}` pair per issue) come from the current conversation, not from `args` — gather and finalize them there before invoking this skill.

## Step 0 — Load credentials and validate

```bash
set -a; . .claude/.env; set +a
```

Required: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, and either `--project=` or `JIRA_WORKSPACE`. If any is missing or still a placeholder value, tell the user which key to fix and **stop** — do not attempt any call.

## Step 1 — Resolve reporter once

```bash
REPORTER=$(curl -sS --fail-with-body -u "$JIRA_EMAIL:$JIRA_API_TOKEN" "$JIRA_BASE_URL/rest/api/3/myself" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["accountId"])')
```

Reuse this `$REPORTER` value for every item in Step 2 — never re-fetch per item.

## Step 2 — Create each item

For every `{summary, description}` item, call the tool script:

```bash
.claude/tools/jira_create_child.sh \
  --summary="<summary>" \
  --description="<description>" \
  --parent="<PARENT, or omit entirely>" \
  --issuetype="<ISSUETYPE, default Task>" \
  --project="<PROJECT, default $JIRA_WORKSPACE>" \
  --reporter="$REPORTER" \
  # append --dry-run only when the invocation requested it
```

Run items **sequentially, not in parallel** (avoid bursting the Jira API), with `sleep 0.3` between calls. Per item:

- Success → the script prints `{"key": "...", "self": "..."}` on stdout; record `OK <key> <summary>`.
- Failure → the script prints an error to stderr and exits non-zero; record `FAIL <summary>: <first line of stderr>`; **continue with the remaining items** rather than aborting the whole batch.

## Step 3 — Report

Print one line per item (`OK <key> <summary>` / `FAIL <summary>: <reason>`) plus a final count, e.g. `Created 9/9 issues under TASK-123.` Surface every failure with its reason so the user can retry just those.

## Constraints

- **No token leaks.** Never echo, log, or print `JIRA_API_TOKEN` or the `Authorization` header — including in `--dry-run` output.
- **Confirm before posting.** Always show the user the exact summaries (and a short description excerpt) you're about to create, in normal chat, before running Step 2 without `--dry-run` — unless they already reviewed and approved that exact list earlier in the conversation.
- **No idempotency.** Re-running this skill with the same items creates duplicate issues; there is no dedupe key. Never re-invoke on a batch that already succeeded.
- **Env-driven.** Never hardcode a project key, workspace, or issue-type name — always `$JIRA_WORKSPACE` / explicit `--project=` and `--issuetype=` overrides.
- **Sequential, not parallel.**
