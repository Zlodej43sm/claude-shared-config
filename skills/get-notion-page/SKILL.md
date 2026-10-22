---
name: get-notion-page
description: Fetch a Notion page by URL or ID and render it as Markdown, following linked Notion pages one level deep. Usage: /get-notion-page <notion-url-or-id> | --check
---

# get-notion-page

## Summary

Retrieve a Notion page — title and full body as Markdown — and the Notion pages it links to (one level). Prefers the Notion MCP tools (the project's `notion` server, then the claude.ai connector) and falls back to a REST script. The project server and the script both use `NOTION_TOKEN` (an internal-integration secret, kept in `.claude/.env` as an `op://` reference like the other tokens). Notion is opt-in per project: uncomment `NOTION_TOKEN` in `.claude/.env`, then re-run `bin/link-project.sh` so the `notion` MCP server is added to `.mcp.json`.

## Use When

- The user gives a `notion.so` / `notion.site` URL, or a Jira ticket / PR description links to one.
- The user asks "what does this Notion doc say" or wants spec/acceptance context that lives in Notion.
- `/get-notion-page --check` to verify the token works.

## Do Not Use When

- The URL is Confluence or Jira — use `get-confluence-page` / `get-jira-task`.
- The user wants to create or edit Notion content — this skill is read-only.

## Inputs

- `args`: a Notion page URL (`https://www.notion.so/<workspace>/<Title>-<32-hex-id>`), a bare 32-hex or dashed UUID page ID, or `--check`.

## Examples

```
/get-notion-page https://www.notion.so/my-ws/Payments-Spec-0123456789abcdef0123456789abcdef
/get-notion-page 0123456789abcdef0123456789abcdef
/get-notion-page 01234567-89ab-cdef-0123-456789abcdef
/get-notion-page --check
```

`--check` output:

> Notion: project `notion` MCP server connected (workspace "My Workspace"); claude.ai connector connected; `NOTION_TOKEN` set. Verified via the project server.

Page output (abridged):

```
Payments Spec
URL: https://www.notion.so/...
(via project notion MCP server)

# Goals
...
## Requirements
- [x] Retry policy agreed

---
## Linked Pages

### Retry Policy
URL: https://www.notion.so/...
...
```

Natural language also triggers it: *"what does this say? https://www.notion.so/…"*.

## Workflow

### Step 1 — Pick the access path (MCP first, REST script as fallback)

Use the first path that is available **and** works; on an auth/not-found/tool error fall through to the next one and say which path produced the result. Never print `NOTION_TOKEN`.

1. **Project `notion` MCP server** (`mcp__notion__*` tools, generated into `.mcp.json` when `NOTION_TOKEN` is set) → **Step 2a**. This is the workspace the project is configured for, so it wins.
2. **claude.ai Notion connector** (e.g. `mcp__claude_ai_Notion__notion-fetch`; account-level, may be a different workspace than the project's) → **Step 2b**.
3. **REST script**, when `NOTION_TOKEN` is set but neither MCP path is connected (server failed to start, session not restarted yet) → **Step 2c**.
4. Nothing available → tell the user: add `NOTION_TOKEN=op://<vault>/<item>/<field>` to `.claude/.env`, create an internal integration at notion.so/profile/integrations, share the page with it (page menu → Connections), re-run `bin/link-project.sh`, restart the session. Stop.

Tool names differ by server version — use ToolSearch (`notion`) to get the exact names and schemas before calling.

### Step 2 — Fetch the root page

**2a — project MCP server.** Retrieve the page (title, URL), then walk its block children (`API-retrieve-a-page`, `API-get-block-children`, following `has_children` to depth 4 and `has_more` pagination, cap 500 blocks) and render headings, lists, to-dos, quotes, code and links as Markdown. Collect `notion.so` / `notion.site` URLs and `child_page` / `link_to_page` IDs as `linked_pages`.

**2b — claude.ai connector.** Call its fetch tool on the URL/ID; it returns the page body in one call. Collect linked Notion URLs from the body.

**2c — REST script.**

```bash
.claude/tools/notion_fetch_page.sh "<URL-or-ID>"
```

Output JSON: `title`, `url`, `markdown`, `linked_pages[]` (`{id, url}`), `truncated`.

**`--check`:** report which paths are available (project server connected? connector connected? `NOTION_TOKEN` set?) and verify the best one — MCP "get self"/users-me call, or `.claude/tools/notion_fetch_page.sh --check` → `{ok, bot, workspace}`. Then stop.

Add the root page's `id` to a `seen` set.

### Step 3 — Follow linked pages (depth 1)

Take `linked_pages` not in `seen`, **at most 5**, and fetch each with the same path that worked for the root (in parallel is fine). On an error record the error line and continue — never abort. Note "_(and N more linked pages not fetched)_" if capped. Do not follow links from these pages.

### Step 4 — Present

```
Page Title
URL: https://...

<full Markdown body>

---
## Linked Pages

### Linked Page Title
URL: https://...

<body>
```

Omit **Linked Pages** when there are none. If `truncated` is true, say the page exceeded the 500-block cap and the tail is missing. Unsupported block types (tables, synced blocks, databases) appear as `[unsupported block: …]`, `[child database: …]` or `[child page: …]` markers — mention them if the user's question may depend on that content.

### Step 5 — On error

| Condition                | Action                                                                                                      |
| ------------------------ | ----------------------------------------------------------------------------------------------------------- |
| No path available        | Step 1.4                                                                                                     |
| HTTP 401                 | Token rejected — refresh `NOTION_TOKEN` in `.claude/.env`, restart the session                               |
| HTTP 404                 | Page doesn't exist **or isn't shared with the integration** (the usual cause) — share it via page menu → Connections |
| HTTP 429                 | Rate limited — retry once later                                                                              |
| `no Notion page id found` | The argument isn't a Notion URL/ID — ask for the right link                                                  |

## Constraints

- Read-only — never call create/update/delete/comment Notion tools, even though the connector exposes them.
- Never print or log `NOTION_TOKEN`.
- Only follow links to `notion.so` / `notion.site` pages.
- Maximum pages per invocation: 1 root + 5 linked = **6**; depth 1 only.
