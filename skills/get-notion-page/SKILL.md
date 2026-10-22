---
name: get-notion-page
description: Fetch a Notion page by URL or ID and render it as Markdown, following linked Notion pages one level deep. Usage: /get-notion-page <notion-url-or-id> | --check
---

# get-notion-page

## Summary

Retrieve a Notion page — title and full body as Markdown — and the Notion pages it links to (one level). Prefers the Notion MCP tools and falls back to a REST script. Two ways to connect, chosen automatically at session start by `sync-env.py`:

- **No API key (default):** the hosted `notion-oauth` server (`mcp.notion.com`). Sign in once — `/mcp` → `notion-oauth` → Authenticate opens the browser authorization window; pick the workspace and the pages to share. No `.env` change needed.
- **API key:** set `NOTION_TOKEN` in `.claude/.env` (an internal-integration secret, an `op://` reference like the other tokens) and the `notion` server (token-based) is used instead.

`NOTION_MCP=off` in `.claude/.env` disables both for projects that don't use Notion.

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

1. **Project `notion` MCP server** (`mcp__notion__*`; token-based, enabled when `NOTION_TOKEN` is set) → **Step 2a**. This is the workspace the project is configured for, so it wins.
2. **Hosted Notion MCP** — the project's `notion-oauth` server (`mcp__notion-oauth__*`) or the claude.ai Notion connector (`mcp__claude_ai_Notion__*`; account-level, may be a different workspace than the project's). Both expose `notion-fetch` → **Step 2b**. If `notion-oauth` is listed but its tools are missing, it hasn't been authorized yet — tell the user: run `/mcp`, choose `notion-oauth`, **Authenticate**, finish the browser window, then retry. Don't treat that as a failure of the skill; if `NOTION_TOKEN` is set, continue to path 3 meanwhile.
3. **REST script**, when `NOTION_TOKEN` is set but no MCP path is connected (server failed to start, or the session that first saw the token hasn't been restarted yet) → **Step 2c**.
4. Nothing available → tell the user the quickest fix: **authorize the hosted server** — start a session (the first start enables `notion-oauth`), restart once, then `/mcp` → `notion-oauth` → Authenticate (browser window, no key needed). Or, if they prefer an API key: create an internal integration at notion.so/profile/integrations, add `NOTION_TOKEN=op://<vault>/<item>/<field>` to `.claude/.env`, share the page with it (page menu → Connections), start a session and restart it once. Stop.

Tool names can differ by server version — use ToolSearch (`notion`) to confirm names and schemas before calling.

### Step 2 — Fetch the root page

**2a — project MCP server.** Call `API-retrieve-a-page` (title, URL) and `API-retrieve-page-markdown` with `page_id` as a dashed UUID (e.g. `01234567-89ab-cdef-0123-456789abcdef`) — one call returns the body as Markdown. If the markdown tool is absent in this server version, walk `API-get-block-children` instead (follow `has_children` to depth 4 and `has_more`, cap 500 blocks) and render headings, lists, to-dos, quotes, code and links yourself. Collect `notion.so` / `notion.site` URLs from the body as `linked_pages`.

**2b — hosted Notion MCP (`notion-oauth` server or claude.ai connector).** Call its `notion-fetch` tool on the URL/ID; it returns the page body in one call. Collect linked Notion URLs from the body.

**2c — REST script.**

```bash
.claude/tools/notion_fetch_page.sh "<URL-or-ID>"
```

Output JSON: `title`, `url`, `markdown`, `linked_pages[]` (`{id, url}`), `truncated`.

**`--check`:** report which paths are available (project `notion` server connected? `notion-oauth` authorized or still needs sign-in? claude.ai connector connected? `NOTION_TOKEN` set?) and verify the best one — MCP `API-get-self` call, or `.claude/tools/notion_fetch_page.sh --check` → `{ok, bot, workspace}`. Then stop.

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
| HTTP 404                 | Page doesn't exist **or isn't shared with the integration** (the usual cause) — share it via page menu → Connections. With `notion-oauth`: re-authenticate and grant access to that page |
| HTTP 429                 | Rate limited — retry once later                                                                              |
| `no Notion page id found` | The argument isn't a Notion URL/ID — ask for the right link                                                  |

## Constraints

- Read-only — never call create/update/delete/comment Notion tools, even though the connector exposes them.
- Never print or log `NOTION_TOKEN`.
- Only follow links to `notion.so` / `notion.site` pages.
- Maximum pages per invocation: 1 root + 5 linked = **6**; depth 1 only.
