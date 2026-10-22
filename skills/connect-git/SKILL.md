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
| **GitHub**    | `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_TOKEN` (+ `GITHUB_API_URL` for GHES)   | `tools/gh_*.sh` REST scripts **and** the `github` MCP server, generated into `.mcp.json` |

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
6. **`mcp.expected: "github"` and `mcp.configured: false`** — `.mcp.json` predates the host switch. Tell the user to run `bin/link-project.sh <this project>` from the shared-config repo (it regenerates a file it generated itself and refuses to touch a hand-edited one) and restart the session so the `github` server starts. **Do not edit `.mcp.json` yourself.**

When everything passes, say so in one line: host, repo, token permissions (`api.detail`), MCP status. Bitbucket has no MCP row to report — say "REST tools only".

### Step 3 — Confirm the MCP server is live (GitHub only)

If `mcp.configured` is true, use ToolSearch (`github`) to find the `mcp__github__*` tools and make one read-only call (`get_me`). Report: connected as `<login>`, or the failure. If the server is listed but failed, the usual causes are an unresolved `GITHUB_TOKEN` (step 2.4), a session that started before `.mcp.json` was regenerated (restart), or — on GHES — Docker not running (the enterprise variant runs `ghcr.io/github/github-mcp-server` in Docker).

Division of labour: the PR skills (`pr-review`, `answer-pr-comments`, `split-pr`) keep using the `gh_*.sh` / `bb_*.sh` scripts because they return one identical JSON shape for both hosts. The `github` MCP server is for everything else on GitHub — browsing files, searching code, issues, ad-hoc PR questions — and the user can ask for those directly.

### Step 4 — Notion status (one line)

If `NOTION_TOKEN` is set in `.claude/.env`, say whether `.mcp.json` has the `notion` server and whether `mcp__notion__*` tools are present (otherwise: "re-run `bin/link-project.sh`, restart"). Point to `/get-notion-page --check` for a live test. If it isn't set, say Notion is not enabled for this project (opt-in).

## Constraints

- Never print, echo, or write a token value. Report only key *names*.
- Never write to `.claude/.env`, `.mcp.json` or `settings.local.json` — tell the user what to change.
- Do not call any create/update/delete GitHub or Bitbucket API or MCP tool — `get_me` and other reads only.
