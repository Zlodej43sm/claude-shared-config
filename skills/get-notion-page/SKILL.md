---
name: get-notion-page
description: Fetch a Notion page (or a database / saved view) by URL or ID and render it as Markdown, following linked Notion pages one level deep; diagnoses "not found" as wrong workspace vs. page not shared. Usage: /get-notion-page <notion-url-or-id> | --check
---

# get-notion-page

## Summary

Retrieve a Notion page — title and full body as Markdown — and the Notion pages it links to (one level). Prefers the Notion MCP tools and falls back to a REST script. Two ways to connect, chosen automatically at session start by `sync-env.py`:

- **No API key (default):** the hosted `notion-oauth` server (`mcp.notion.com`). Sign in once — `/mcp` → `notion-oauth` → Authenticate opens the browser authorization window; pick the workspace and the pages to share. No `.env` change needed.
- **API key:** set `NOTION_TOKEN` in `.claude/.env` (an internal-integration secret, an `op://` reference like the other tokens) and the `notion` server (token-based) is used instead.

`NOTION_MCP=off` in `.claude/.env` disables both for projects that don't use Notion.

## Use When

- The user gives a `notion.so`, `app.notion.com` or `*.notion.site` URL, or a Jira ticket / PR description links to one.
- The user asks "what does this Notion doc say" or wants spec/acceptance context that lives in Notion.
- `/get-notion-page --check` to verify the token works.

## Do Not Use When

- The URL is Confluence or Jira — use `get-confluence-page` / `get-jira-task`.
- The user wants to create or edit Notion content — this skill is read-only.

## Inputs

- `args`: a Notion URL — `https://www.notion.so/<workspace>/<Title>-<32-hex-id>`, `https://app.notion.com/p/<workspace>/<Title>-<32-hex-id>`, `https://<workspace>.notion.site/...`, or a database / saved-view URL (`.../<32-hex-db-id>?v=<view-id>`) — a bare 32-hex or dashed UUID ID, or `--check`. The `<workspace>` slug in the URL is the workspace the page lives in; Step 6 uses it.

## Examples

```
/get-notion-page https://www.notion.so/my-ws/Payments-Spec-0123456789abcdef0123456789abcdef
/get-notion-page https://app.notion.com/p/my-ws/Payments-Spec-0123456789abcdef0123456789abcdef
/get-notion-page https://app.notion.com/p/my-ws/0123456789abcdef0123456789abcdef?v=fedcba9876543210fedcba9876543210
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

**Workspace guard.** If `.claude/.env` defines `NOTION_WORKSPACE_ID`, read only that line (`grep -m1 '^NOTION_WORKSPACE_ID=' .claude/.env | cut -d= -f2-`; never print the rest of the file) and, before fetching, confirm the connection's workspace id matches it (hosted path: `notion-get-self`; REST path: `notion_fetch_page.sh --check` → `workspace_match`). On a mismatch don't fetch through that path — use the next one, or go straight to Step 6's *wrong workspace* message.

### Step 2 — Fetch the root page

**2a — project MCP server.** Call `API-retrieve-a-page` (title, URL) and `API-retrieve-page-markdown` with `page_id` as a dashed UUID (e.g. `01234567-89ab-cdef-0123-456789abcdef`) — one call returns the body as Markdown. If the markdown tool is absent in this server version, walk `API-get-block-children` instead (follow `has_children` to depth 4 and `has_more`, cap 500 blocks) and render headings, lists, to-dos, quotes, code and links yourself. Collect `notion.so` / `app.notion.com` / `notion.site` URLs from the body as `linked_pages`.

**2b — hosted Notion MCP (`notion-oauth` server or claude.ai connector).** Call its `notion-fetch` tool on the URL/ID; it returns the page body in one call. Collect linked Notion URLs from the body.

**Databases and saved views (any path).** If the URL carries `?v=` or the fetch returns a database (`<data-source url="collection://…">` on the hosted path, `kind: "database"` from the script), present the database title, its properties and up to 25 rows (title + URL). For a saved view, the hosted fetch returns its filters/sorts; query its rows with the server's data-source query tool in view mode when available (e.g. `notion-query-data-sources`, `mode: "view"`). Don't treat rows as linked pages to follow unless the user asks for a specific row.

**2c — REST script.**

```bash
.claude/tools/notion_fetch_page.sh "<URL-or-ID>"
```

Output JSON: `kind` (`page` | `database`), `title`, `url`, `markdown`, `linked_pages[]` (`{id, url}`), `truncated`; databases also carry `rows[]` (`{id, title, url}`).

**`--check`:** report which paths are available (project `notion` server connected? `notion-oauth` authorized or still needs sign-in? claude.ai connector connected? `NOTION_TOKEN` set?) and verify the best one — MCP `API-get-self` / `notion-get-self` call, or `.claude/tools/notion_fetch_page.sh --check` → `{ok, bot, workspace, workspace_id, workspace_match}`. Always print the connected **workspace name and id** (names can repeat across workspaces) and, when `NOTION_WORKSPACE_ID` is set, whether it matches. Then stop.

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
| HTTP 404 / `object_not_found` | Not visible to this connection — run **Step 6** before advising anything                         |
| HTTP 400 "is a database"  | Re-fetch as a database (Step 2, *Databases and saved views*)                                                 |
| HTTP 429                 | Rate limited — retry once later                                                                              |
| `no Notion page id found` | The argument isn't a Notion URL/ID — ask for the right link                                                  |

### Step 6 — Diagnose a 404 (wrong workspace vs. page not shared)

A 404 has two different causes, and the fixes differ. Find out which before telling the user anything, and never ask them to re-authenticate again without changing something — re-authorizing the same workspace returns the same 404.

1. **Identify the connection.** Hosted path: `notion-get-self` → workspace name **and id**. REST path: `notion_fetch_page.sh --check` → `workspace`, `workspace_id`. Two workspaces can share a display name (e.g. a personal workspace named after the company), so compare ids, never names.
2. **Read the URL's workspace slug**: `notion.so/<slug>/…`, `app.notion.com/p/<slug>/…` or `<slug>.notion.site/…`.
3. **Probe** with `notion-search` for 2–4 distinctive words from the URL's title slug (`Payments-Retry-Spec-<id>` → "payments retry spec"), then look at what the workspace contains.
4. **Conclude and report in one or two lines** (workspace name + id, which case, the fix):
   - **Wrong workspace** — the search returns nothing related, or only starter/template pages ("Getting Started", "To Do List", "Example PRD"), or `NOTION_WORKSPACE_ID` is set and differs. Fix: `/mcp` → `notion-oauth` → Authenticate, and on the consent screen **open the workspace switcher at the top and choose the workspace whose URL is `<slug>`** before approving, then grant the pages/teamspaces. If that workspace isn't offered or approval is blocked, its admins restrict third-party integrations: the user needs admin approval, an admin-created integration token (`NOTION_TOKEN`), or to paste/export the page.
   - **Right workspace, page not shared** — the search returns real pages from that workspace but not this one. Fix: with `notion-oauth`, re-authenticate and add the page or its teamspace in the page picker; with `NOTION_TOKEN`, page menu → Connections → add the integration.
5. After the first successful fetch from the right workspace, suggest pinning it: `NOTION_WORKSPACE_ID=<id>` in `.claude/.env`, so the workspace guard (Step 1) catches the mix-up next time.

## Constraints

- Read-only — never call create/update/delete/comment Notion tools, even though the connector exposes them.
- Never print or log `NOTION_TOKEN`.
- Only follow links to `notion.so` / `app.notion.com` / `notion.site` pages.
- `.claude/.env` holds secrets: read only the `NOTION_WORKSPACE_ID` line from it, never the whole file.
- Maximum pages per invocation: 1 root + 5 linked = **6**; depth 1 only.
