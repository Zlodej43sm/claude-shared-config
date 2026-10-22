---
name: connect-git
description: Verify and set up this project's git-hosting connection (Bitbucket or GitHub) — resolves which host the project uses, checks the credentials in .claude/.env, tests them against the host API, and confirms the matching MCP server is wired into .mcp.json. Usage: /connect-git
---

# connect-git

## Summary

One-shot connection check for the git host the project actually uses. The host is resolved exactly like the PR skills do (`GIT_HOST` → `origin` remote URL → whichever of `BITBUCKET_WORKSPACE`/`GITHUB_OWNER` is set), so nothing needs configuring twice:

| Host          | Credentials (`.claude/.env`)                                                  | How Claude talks to it                                                              |
| ------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **Bitbucket** | `BITBUCKET_WORKSPACE`, `BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN` | `tools/bb_*.sh` REST scripts (no Bitbucket MCP server exists)                       |
| **GitHub**    | `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_TOKEN` (+ `GITHUB_API_URL` for GHES)   | `tools/gh_*.sh` REST scripts **and** the `github` MCP server (in `mcp.json.template`, enabled by `sync-env.py` when the host is GitHub) |

Read-only: one GET against the repo endpoint, no writes, no token ever printed.

## Use When

- Setting up a project for the first time, or after switching its remote between Bitbucket and GitHub.
- `/pr-review`, `/answer-pr-comments` or `/split-pr` fail with 401/403/404.
- The user asks "is GitHub/Bitbucket connected?".

## Examples

```
/connect-git
```

Healthy GitHub project:

> **github** — `my-org/my-app` reachable, token permissions: admin, push, pull. MCP: `github` server connected as `octocat`. Notion: not enabled.

Broken project (token not resolved, MCP missing):

> **github** — ✗ `GITHUB_TOKEN` is an unresolved `op://` reference: run `op signin` and restart the session. ✗ `.mcp.json` has no `github` server: run `bin/link-project.sh <this project>` from the shared-config repo, then restart.

Bitbucket project:

> **bitbucket** — `my-workspace/my-repo` reachable. MCP: REST tools only (expected — no Bitbucket MCP server exists).

## Workflow

### Step 1 — Run the check

```bash
.claude/tools/git_host_check.sh
```

It prints one JSON object (`host`, `env`, `api`, `mcp`) and exits `0` (connected), `1` (a problem — see JSON) or `2` (host undeterminable).

### Step 2 — Report and fix, in this order

Stop at the first failing layer and give the user the exact fix:

1. **Exit 2 / `host: null`** — set `GIT_HOST=bitbucket` or `GIT_HOST=github` in `.claude/.env`, or add an `origin` remote.
2. **`env.missing`** — list the keys; they belong in `.claude/.env` (copy of `.claude/.env.example`). Token fields are 1Password references (`op://vault/item/field`) resolved by `hooks/sync-env.py` at session start.
3. **`env.placeholder`** — the key still holds the template value (`replace-with-…`, `your-…`); ask the user for the real value.
4. **`env.unresolved_op`** — the `op://` reference was not resolved in this session: `op` is missing or signed out (`op signin`), or the session started before `.env` was filled. Restart the session after fixing.
5. **`api.status` 401/403/404** — 401: token (and, for Bitbucket, email) rejected; 403: token lacks scope (GitHub: `repo`, or fine-grained Contents + Pull requests read/write); 404: wrong workspace/slug (Bitbucket) or owner/repo (GitHub).
6. **`mcp.expected: "github"` and `mcp.configured: false`** — the `github` server is either missing from `.mcp.json` or disabled:
    - Missing: `.mcp.json` is an old copy that predates the `github` server. Tell the user to delete it and re-run `bin/link-project.sh <this project>` from the shared-config repo (the script never overwrites an existing, different `.mcp.json`). **Do not edit `.mcp.json` yourself.**
    - Disabled: `hooks/sync-env.py` turned it off because it didn't detect GitHub as the host (e.g. the session started before the remote/`GIT_HOST` was set). Fix the host (step 1) and start a new session — the hook updates `settings.local.json` at session start and it applies from the *next* start.

When everything passes, say so in one line: host, repo, token permissions (`api.detail`), MCP status. Bitbucket has no MCP row to report — say "REST tools only".

### Step 3 — Confirm the MCP server is live (GitHub only)

The GitHub token needs no API key: if `GITHUB_TOKEN` is unset, `sync-env.py` and the MCP launcher use the token of the user's `gh auth login` session (browser sign-in), and `GITHUB_OWNER`/`GITHUB_REPO` default to the origin remote. If neither a token nor a `gh` session exists, tell the user to run `gh auth login` (or set `GITHUB_TOKEN`).

If `mcp.configured` is true, use ToolSearch (`github`) to find the `mcp__github__*` tools and make one read-only call (`get_me`). Report: connected as `<login>`, or the failure. If the server is listed but failed, the usual causes are an unresolved `GITHUB_TOKEN` (step 2.4), or Docker not running — the server runs `ghcr.io/github/github-mcp-server` in Docker (first start pulls the image, which can exceed the connect window; restart once). On GHES / GHE.com set `GITHUB_HOST` in `.claude/.env`.

Division of labour: the PR skills (`pr-review`, `answer-pr-comments`, `split-pr`) keep using the `gh_*.sh` / `bb_*.sh` scripts because they return one identical JSON shape for both hosts. The `github` MCP server is for everything else on GitHub — browsing files, searching code, issues, ad-hoc PR questions — and the user can ask for those directly.

### Step 4 — Atlassian and Notion status (one line each)

**Atlassian:** usable `JIRA_BASE_URL` + `JIRA_EMAIL` + `JIRA_API_TOKEN` → API-token `atlassian` server; otherwise the hosted `atlassian-oauth` server (listed in `/mcp` as "needs authentication" → `/mcp` → `atlassian-oauth` → Authenticate once, browser window). `python3 .claude/tools/atlassian_fetch.py check` tests the token path.

**Notion** — report which connection the project uses: `NOTION_TOKEN` set → token-based `notion` server (are `mcp__notion__*` tools present? if not: `sync-env.py` enables it at session start and it launches on the *next* start — restart once); no token → hosted `notion-oauth` server (listed in `/mcp` as "needs authentication"? tell the user to `/mcp` → `notion-oauth` → Authenticate once; no API key needed); `NOTION_MCP=off` → Notion disabled for this project. Point to `/get-notion-page --check` for a live test.

## Constraints

- Never print, echo, or write a token value. Report only key *names*.
- Never write to `.claude/.env`, `.mcp.json` or `settings.local.json` — tell the user what to change.
- Do not call any create/update/delete GitHub or Bitbucket API or MCP tool — `get_me` and other reads only.
