---
name: get-jira-task
description: Fetch a Jira issue (e.g. $JIRA_WORKSPACE-1) — title, status, description, subtasks, and all linked Confluence pages fetched in full (two levels deep, classified by type). Delegates to the jira-context agent.
---

# get-jira-task

## Summary

Retrieve a Jira ticket and all referenced Confluence documentation. Delegates to the `jira-context` agent which fetches full page bodies (no truncation), classifies each page as spec / AC / ADR / reference, and follows links two levels deep.

## Use When

- The user references a ticket number (e.g. "look at $JIRA_WORKSPACE-123").
- You need acceptance criteria, description, or spec context before starting work.
- The user asks what a ticket is about.

## Do Not Use When

- The user wants to search or list multiple issues — use `mcp__atlassian__jira_search` directly.
- The Atlassian MCP server is not running — check with `/mcp`; if `atlassian` is absent, restart the session.

## Input

`args`: ticket key (e.g. `$JIRA_WORKSPACE-123`) or bare number (`123`). Optionally followed by `-- <repo-path>` for related service context (passed through to the agent).

## Step 0 — Resolve key and load env

```bash
set -a; . ./.claude/.env; set +a
```

If `args` is only digits, prepend `$JIRA_WORKSPACE-`. Confirm `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` are set — if not, tell the user which key to set and stop.

Parse `--` separator: everything before is the ticket key; everything after is related_repos (pass `"none"` if absent).

## Step 1 — Delegate to `jira-context` agent

Spawn the `jira-context` subagent via the Agent tool with `subagent_type: "jira-context"`:

```
Fetch context for a Jira ticket. Values:

  ticket_key:    <RESOLVED_KEY>
  related_repos: <comma-separated paths, or "none">
  project_root:  <absolute path to the directory containing .claude/.env>

Run your full context-gathering procedure (Steps 1–6) and return the complete context block as your final message.
```

## Step 2 — Surface the output

Surface the agent's returned context block **verbatim**. Do not summarise, paraphrase, or truncate it.

The output format the agent produces is:

```
=== JIRA CONTEXT: <key> ===

## Ticket
...

## Description
...

## Confluence Documents
...

## Project Context
...

=== END JIRA CONTEXT ===
```

## Constraints

- Read-only — never call create/update/delete MCP tools.
- Never log or echo the API token.
- Maximum total Confluence pages fetched: 8 depth-1 + 32 depth-2 = 40 pages.
