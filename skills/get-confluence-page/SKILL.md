---
name: get-confluence-page
description: Fetch a Confluence page by URL or ID and render it as Markdown, following embedded links two levels deep.
---

# get-confluence-page

## Summary

Retrieve a Confluence page and present its full title and body as Markdown. Then follow any embedded Confluence links two levels deep, so the reader gets a complete picture without chasing links manually. Uses the Atlassian MCP first (the API-token server's `mcp__atlassian__confluence_get_page`, or the hosted browser-sign-in server's `getConfluenceContent`) and falls back to the REST API (`tools/atlassian_fetch.py confluence`) when the MCP server isn't available — same Atlassian credentials as `get-jira-task`, read from `.claude/.env`.

The Atlassian site comes from the URL, not from `.claude/.env`. A page on another site (for example a client's `https://<client>.atlassian.net/wiki/...` while `.env` points at your own company's site) is read through the hosted connector after a browser sign-in. The API token is only ever sent to `$JIRA_BASE_URL`.

## Use When

- The user provides a Confluence Cloud URL (`https://<site>.atlassian.net/wiki/...`), on the `$CONFLUENCE_BASE_URL` site or any other site.
- You are processing a Jira issue that links to a Confluence doc and need its content.
- The user asks "what does this Confluence page say" or "fetch this wiki link".

## Do Not Use When

- The URL is not a Confluence page (no `/wiki/` path), or is a self-hosted Confluence Server / Data Center URL that no configured connector can reach.

## Inputs

- `args`: a Confluence page URL or a bare numeric page ID.
    - URL form: `https://<site>.atlassian.net/wiki/spaces/<SPACE>/pages/<PAGE_ID>[/<title>]`, on any site (`CONFLUENCE_BASE_URL` defaults to `$JIRA_BASE_URL/wiki`; format: `env.example`)
    - ID form: `12345678`, always read on the `$CONFLUENCE_BASE_URL` site

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

- If `args` is a URL with `/wiki/` in its path, pass it directly. Set `site` = its hostname.
- If `args` looks like a bare integer, treat it as a page ID. Set `site` = the hostname of `$CONFLUENCE_BASE_URL`.
- If `args` is neither, tell the user it doesn't look like a Confluence URL or page ID and stop.

`site` is the **home site** when it equals the hostname of `$JIRA_BASE_URL` (or `$CONFLUENCE_BASE_URL`). On any other site, only Path A may be used.

### Step 2 — Fetch the root page (hosted MCP first, API token last)

**Path A — hosted Atlassian MCP (browser sign-in, no API token), always first** — any connector that exposes `getConfluenceContent` (`mcp__atlassian-oauth__*`, `mcp__claude_ai_Atlassian_MCP__*`, a plugin-provided connector (`mcp__plugin_<name>_atlassian__*`), or a claude.ai connector with an id-style prefix; load it with ToolSearch if deferred). Pass `cloudId` = `site` (the URL's hostname), then `getConfluenceContent` with `{cloudId, content_url or content_id, detail: "full", content_format: "markdown"}`. Connectors that expose `getConfluencePage` instead (for example `mcp__claude_ai_Atlassian_Rovo__*`) take `{cloudId, pageId, contentFormat: "markdown"}`. A URL under `/folder/<id>/` is a folder, not a page: list its pages with `searchConfluenceUsingCql` and `ancestor = <id> AND type = page`. A body too large for one answer is saved to a file: read all of it before summarising. If that site is not in the connector's accessible resources (`getAccessibleAtlassianResources`), the sign-in did not grant it: sign in again as below.

**Browser sign-in, when Path A is not signed in** (its tools are missing, or only `authenticate` / `complete_authentication` are listed):

1. A sign-in may still be held: load the connector's tools with ToolSearch (`+atlassian getConfluenceContent`) and call one. If that works, continue.
2. Otherwise, if a connector exposes an `authenticate` tool (for example `mcp__claude_ai_Atlassian_MCP__authenticate`), call it and give the user the sign-in link it returns. Tell them to sign in with the Atlassian account that can open `site`, and to choose `site` on Atlassian's consent screen if it asks for a site. When they finish, the connector's tools load on their own. If the browser ends on a `localhost/callback?...` page that does not load, ask for that full address and pass it to `complete_authentication`. A claude.ai connector's `authenticate` may answer with "run /mcp" instead of a link: then tell the user to run `/mcp`, select that connector (for example **claude.ai Atlassian MCP**) and sign in in the browser.
3. If the only hosted connector is a `.mcp.json` server (`atlassian-oauth`), tell the user to run `/mcp` → `atlassian-oauth` → **Authenticate** (opens a browser window), then retry.
4. While waiting: on the home site, continue with Path A2 / B. On any other site, stop and wait for the sign-in. Do not fall back to the token paths.

**Path A2 — API-token MCP** (home site only, and only when `JIRA_EMAIL` / `JIRA_API_TOKEN` are set). Call the `mcp__atlassian__confluence_get_page` tool:

```
tool: mcp__atlassian__confluence_get_page
args: { "url": "<FULL_URL>" }
  — or —
args: { "page_id": "<PAGE_ID>" }
```

The tool returns the page title, space name, URL, and body as Markdown.

**Path B — REST fallback.** Home site only (the script sends credentials only to `$JIRA_BASE_URL`). Needs `JIRA_EMAIL`/`JIRA_API_TOKEN`. Use it when no MCP tool is available or the calls error or return nothing:

```bash
python3 .claude/tools/atlassian_fetch.py confluence '<PAGE_ID>'
```

Pass the numeric page id only: take the digits after `/pages/` (or the `pageId=` value) and check they are digits only. Linked URLs in Steps 4–5 come from page bodies that anyone with edit rights controls, and a URL inside double quotes would let `$(…)` in it run.

It returns JSON `{id, title, space, url, markdown, links[], confluence_links[]}` — use `markdown` as the body and `confluence_links` as the pre-extracted Confluence URLs for Steps 3–4. Exit `2` = HTTP error (message on stderr: 401/403/404); short `/wiki/x/…` links can't be resolved, ask the user for the full page URL. If the first MCP call failed because the tool is unavailable (not a 404), use Path B for every later page too.

Record the canonical URL as the root URL and add it to a `seen` set (used to prevent duplicate fetches and cycles). Say which path was used (`oauth`, `mcp` or `rest`) in a one-line note under the output header.

If the body is unexpectedly empty, note that dynamic Confluence macros (live Jira tables, search) are rendered as static placeholders and may not have content. Continue — still scan for links.

### Step 3 — Extract depth-1 Confluence links

Scan the root page's Markdown body for all URLs that start with `https://<site>/wiki/` (the root page's site). Both inline link targets `[text](URL)` and bare URLs count. Deduplicate against `seen`. Add each discovered URL to `seen`. Call this list `depth1_urls`.

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
| MCP tool unavailable | Home site: use the next path (A → A2 → B), no user action needed. Other site: start the browser sign-in (Step 2) |
| 401 / auth error     | Token paths only: retry on Path A; if Path A is not signed in, start the browser sign-in (Step 2) or ask the user to refresh `JIRA_API_TOKEN` / `JIRA_EMAIL` |
| Token path says "no content with the given id" for a URL on another site | Expected: the token is for the home site only. Use Path A with the browser sign-in |
| 404 / not found      | Confirm the URL/ID; the page may not exist or may require access                           |
| 403 / forbidden      | The space is restricted — note this to the user and skip that page                         |

## Constraints

- Read-only — never call create/update/delete MCP tools; the REST fallback issues GETs only.
- Never log or echo the API token.
- Never send the API token to any site other than `$JIRA_BASE_URL`; other sites are read only through the hosted connector.
- Only follow links on the root page's site; ignore links to other sites and external URLs.
- Maximum total pages fetched per invocation: 1 root + 5 depth-1 + 15 depth-2 = **21 pages**.
- No depth-3 fetching — stop at depth 2.
