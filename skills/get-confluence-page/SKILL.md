---
name: get-confluence-page
description: Fetch a Confluence page by URL or ID and render it as Markdown, following embedded links two levels deep.
---

# get-confluence-page

## Summary

Retrieve a Confluence page and present its full title and body as Markdown. Then follow any embedded Confluence links two levels deep, so the reader gets a complete picture without chasing links manually. Uses the Atlassian MCP first (the API-token server's `mcp__atlassian__confluence_get_page`, or the hosted browser-sign-in server's `getConfluenceContent`) and falls back to the REST API (`tools/atlassian_fetch.py confluence`) when the MCP server isn't available — same Atlassian credentials as `get-jira-task`, read from `.claude/.env`.

## Use When

- The user provides a Confluence URL starting with `$CONFLUENCE_BASE_URL`.
- You are processing a Jira issue that links to a Confluence doc and need its content.
- The user asks "what does this Confluence page say" or "fetch this wiki link".

## Do Not Use When

- Atlassian is not connected at all (no hosted Atlassian MCP connector signed in and no API token).
- The URL is not on the same tenant as `$CONFLUENCE_BASE_URL`.

## Inputs

- `args`: a Confluence page URL or a bare numeric page ID.
    - URL form: `$CONFLUENCE_BASE_URL/<SPACE>/pages/<PAGE_ID>[/<title>]`
    - ID form: `12345678`

## Expected Output

```
[Space Name] › Page Title
URL: https://...

<full Markdown body>

---
## Linked Pages

### [Space] › [Depth-1 Title]
URL: https://...

<full body of depth-1 page>

  #### [Space] › [Depth-2 Title]
  URL: https://...
  <body truncated to ~400 chars, or "(empty)" if blank>
  …

### [Space] › [another depth-1 title]
…
```

Omit the **Linked Pages** section entirely when no Confluence links are found in the root page body.

## Workflow

### Step 1 — Resolve input to URL or ID

- If `args` is a full URL starting with `$CONFLUENCE_BASE_URL`, pass it directly.
- If `args` looks like a bare integer, treat it as a page ID.
- If `args` is neither, tell the user it doesn't look like a Confluence URL or page ID and stop.

### Step 2 — Fetch the root page (hosted MCP first, API token last)

**Path A — hosted Atlassian MCP (browser sign-in, no API token), always first** — any connector that exposes `getConfluenceContent` (`mcp__atlassian-oauth__*`, `mcp__claude_ai_Atlassian_MCP__*`, `mcp__plugin_meta_atlassian__*`, or a claude.ai connector with an id-style prefix; load it with ToolSearch if deferred). Pass `cloudId` = the hostname of `$CONFLUENCE_BASE_URL` / `$JIRA_BASE_URL`, then `getConfluenceContent` with `{cloudId, content_url or content_id, detail: "full", content_format: "markdown"}`. If the server is listed but its tools are missing, the user hasn't signed in: tell them `/mcp` → `atlassian-oauth` → **Authenticate** (browser window), then retry — and continue with Path B meanwhile if an API token is configured.

**Path A2 — API-token MCP** (only when `JIRA_EMAIL` / `JIRA_API_TOKEN` are set). Call the `mcp__atlassian__confluence_get_page` tool:

```
tool: mcp__atlassian__confluence_get_page
args: { "url": "<FULL_URL>" }
  — or —
args: { "page_id": "<PAGE_ID>" }
```

The tool returns the page title, space name, URL, and body as Markdown.

**Path B — REST fallback.** Needs `JIRA_EMAIL`/`JIRA_API_TOKEN`. Use it when no MCP tool is available or the calls error or return nothing:

```bash
python3 .claude/tools/atlassian_fetch.py confluence '<PAGE_ID>'
```

Pass the numeric page id only: take the digits after `/pages/` (or the `pageId=` value) and check they are digits only. Linked URLs in Steps 4–5 come from page bodies that anyone with edit rights controls, and a URL inside double quotes would let `$(…)` in it run.

It returns JSON `{id, title, space, url, markdown, links[], confluence_links[]}` — use `markdown` as the body and `confluence_links` as the pre-extracted Confluence URLs for Steps 3–4. Exit `2` = HTTP error (message on stderr: 401/403/404); short `/wiki/x/…` links can't be resolved, ask the user for the full page URL. If the first MCP call failed because the tool is unavailable (not a 404), use Path B for every later page too.

Record the canonical URL as the root URL and add it to a `seen` set (used to prevent duplicate fetches and cycles). Say which path was used (`oauth`, `mcp` or `rest`) in a one-line note under the output header.

If the body is unexpectedly empty, note that dynamic Confluence macros (live Jira tables, search) are rendered as static placeholders and may not have content. Continue — still scan for links.

### Step 3 — Extract depth-1 Confluence links

Scan the root page's Markdown body for all URLs that start with `$CONFLUENCE_BASE_URL`. Both inline link targets `[text](URL)` and bare URLs count. Deduplicate against `seen`. Add each discovered URL to `seen`. Call this list `depth1_urls`.

Cap: take at most **5** depth-1 URLs. If more exist, note "_(and N more linked pages not fetched)_" in the output.

### Step 4 — Fetch depth-1 pages

For each URL in `depth1_urls`, fetch it with the same path as Step 2. On error (403/404/network), record the URL with the error note and continue — do not abort.

For each successfully fetched depth-1 page:

- Extract all Confluence URLs from its body not already in `seen`. Add them to `seen`. Call this list `depth2_urls` for that page.
- Cap: take at most **3** depth-2 URLs per depth-1 page. Note extras if truncated.

### Step 5 — Fetch depth-2 pages

For each depth-1 page's `depth2_urls`, fetch it with the same path as Step 2. On error, record the error and continue.

Depth-2 body is truncated to ~400 chars in the output to keep the response readable. Show a "…" ellipsis when truncated.

### Step 6 — Present output

Render the full structure:

1. **Root page** — full body, no truncation.
2. **Linked Pages section** — only if `depth1_urls` is non-empty.
    - Each depth-1 page at `###` heading level with full body.
    - Each depth-2 page at `####` heading level, indented, body truncated to ~400 chars.
3. After the last depth-1 block, if any extras were skipped at depth 1, append the "and N more" note.

### Step 7 — On error

| Condition            | Action                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------ |
| MCP tool unavailable | Use the next path (A → A2 → B) — no user action needed |
| 401 / auth error     | Token paths only: retry on Path A; if Path A is not signed in, tell the user to sign in to the Atlassian connector or refresh `JIRA_API_TOKEN` / `JIRA_EMAIL` |
| 404 / not found      | Confirm the URL/ID; the page may not exist or may require access                           |
| 403 / forbidden      | The space is restricted — note this to the user and skip that page                         |

## Constraints

- Read-only — never call create/update/delete MCP tools; the REST fallback issues GETs only.
- Never log or echo the API token.
- Only follow links within the same `$CONFLUENCE_BASE_URL` tenant — ignore external URLs.
- Maximum total pages fetched per invocation: 1 root + 5 depth-1 + 15 depth-2 = **21 pages**.
- No depth-3 fetching — stop at depth 2.
