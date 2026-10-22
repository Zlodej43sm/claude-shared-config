---
name: get-jira-task
description: Fetch a Jira issue (e.g. $JIRA_WORKSPACE-1) — title, status, description, subtasks, all linked Confluence pages fetched in full (two levels deep, classified by type), and the image attachments, downloaded and analyzed. Delegates to the jira-context agent. Usage: /get-jira-task <key> [--no-images] [--max-images=N] [-- <repo-path>...]
---

# get-jira-task

## Summary

Retrieve a Jira ticket and all referenced Confluence documentation. Delegates to the `jira-context` agent which fetches full page bodies (no truncation), classifies each page as spec / AC / ADR / reference, and follows links two levels deep. Uses the Atlassian MCP first — the API-token server, or the hosted browser-sign-in server when no API key is configured — and falls back automatically to the REST API (`tools/atlassian_fetch.py`, needs the API token) when neither MCP server is available; the output block says which was used (`Source:`).

Image attachments (screenshots, mockups, diagrams, error captures) are downloaded through the Jira REST API (`tools/atlassian_fetch.py attachments`, same `JIRA_*` credentials, whichever path the text came from) and then **viewed and analyzed by this session** in Step 3 — the agent returns text only, so the analysis happens here where the images can actually be seen.

## Use When

- The user references a ticket number (e.g. "look at $JIRA_WORKSPACE-123").
- You need acceptance criteria, description, or spec context before starting work.
- The user asks what a ticket is about.

## Do Not Use When

- The user wants to search or list multiple issues — use the Atlassian MCP search tool (`mcp__atlassian__jira_search`, or `searchJiraIssuesUsingJql` on the hosted server) directly.
- Atlassian is not connected at all (no API token and the hosted server isn't signed in) — run `python3 .claude/tools/atlassian_fetch.py check` to test them.

## Input

`args`: ticket key (e.g. `$JIRA_WORKSPACE-123`) or bare number (`123`). Optionally:

- `--no-images` — skip the attachment step entirely.
- `--max-images=N` — analyze at most N images (default 8; oldest first).
- `-- <repo-path>...` — related service context (passed through to the agent).

## Step 0 — Resolve key and load env

```bash
set -a; . ./.claude/.env; set +a
```

If `args` is only digits, prepend `$JIRA_WORKSPACE-`. Confirm `JIRA_BASE_URL` is set — if not, tell the user and stop. `JIRA_EMAIL` / `JIRA_API_TOKEN` are optional: without them the agent uses the hosted browser-sign-in MCP server (`/mcp` → `atlassian-oauth` → Authenticate, once).

Parse `--` separator: everything before is the ticket key plus the optional `--no-images` / `--max-images=N` flags; everything after is related_repos (pass `"none"` if absent).

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

## Step 3 — Fetch and analyze the image attachments

Skip this step if `--no-images` was passed. Attachments are downloaded over REST, so this step needs `JIRA_EMAIL` + `JIRA_API_TOKEN`; without them say once "Image attachments need an API token (JIRA_EMAIL/JIRA_API_TOKEN) — skipped" and finish.

```bash
IMG_DIR=$(mktemp -d)
python3 .claude/tools/atlassian_fetch.py attachments <RESOLVED_KEY> --dir "$IMG_DIR" --max <N or 8>
```

It prints JSON `{key, dir, images[], skipped[]}`: `images[]` are downloaded PNG/JPEG/GIF/WebP files (oldest first, each ≤ 5 MB) with `filename`, `author`, `created`, `path`; `skipped[]` are attachments it did not download, with a reason (not an image, SVG/PDF/log, too large, over the limit, HTTP error).

- Exit `2` (HTTP error) or `1` (credentials) → one line: "Could not fetch attachments: <message>". The context block is already delivered; do not retry or fail the skill.
- `images` empty → one line: "No image attachments." (mention `skipped` names, if any, so the user knows other files exist).

Otherwise **view every image with the Read tool** (pass each `path`) and analyze it in the context of the ticket you just surfaced. For each image say:

- what it shows (UI screen/state, error dialog or stack trace, diagram, data table, photo of a whiteboard…);
- any text you can read in it, quoted exactly when it matters (error messages, labels, IDs, numbers, URLs);
- how it relates to the description / acceptance criteria — and anything that contradicts or is missing from the ticket text (a mockup state not covered by the AC, an error the description doesn't mention);
- anything unreadable or ambiguous — say so instead of guessing.

Present after the context block:

```
## Attached Images (<n> analyzed)

### <filename> — <author>, <created>
<analysis>

### <filename> — …

Not analyzed: <filename> (<reason>), …
```

Finally remove the temp directory: `rm -rf "$IMG_DIR"`.

Attachments are downloaded only for this analysis; nothing is kept in the project. When the `jira-context` agent is used on its own by another skill (`implement`, `pr-review`), images are **not** included — only this skill does the image step.

## If the MCP server is down

Nothing to do — the agent falls back to REST by itself and reports `Source: REST fallback`; the image step always uses REST (API token required). To see why the MCP server is failing, run `/mcp` or start it by hand (`python3 .claude/tools/mcp-run.py … -- uvx mcp-atlassian`; its `[mcp-run]` stderr line names a missing key). To test the credentials directly: `python3 .claude/tools/atlassian_fetch.py check`.

## Constraints

- Read-only — never call create/update/delete MCP tools; the REST fallback and the attachment download issue GETs only.
- Never log or echo the API token. The tool sends the Jira credentials only to `JIRA_BASE_URL` and follows Atlassian's media-host redirect without them.
- Maximum total Confluence pages fetched: 8 depth-1 + 32 depth-2 = 40 pages.
- Images: raster formats only, ≤ 5 MB each, default cap 8 per ticket. Each image costs context — use `--max-images=N` or `--no-images` for attachment-heavy tickets.
