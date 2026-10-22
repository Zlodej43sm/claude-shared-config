# claude-shared-config

Shared, version-controlled Claude Code setup — skills, subagents, and MCP server
config, linked into every project instead of copy-pasted per repo. Includes
ready-made skills for Jira/Confluence/Notion context-gathering, Bitbucket/GitHub
connection setup, PR review and comment-answering, SonarQube triage, PR-splitting, plan-first
feature implementation, evidence-based repository/service overviews, and
security auditing of this shared config tree itself.

## Quick start

Link this repo into a project — symlinks `skills/`, `agents/`, `tools/`,
`hooks/`, and `workflows/` into the project's `.claude/`, and generates its
`.mcp.json` and `.claude/settings.json`:

```bash
bin/link-project.sh <project_path>
```

Then copy the generated `.claude/.env.example` to `.claude/.env` and fill in
the per-project values. The script is idempotent and non-destructive: it
safely reuses its own existing symlinks, refuses to overwrite an existing
`.mcp.json` that diverges from the template, and leaves an existing, diverged
`.claude/settings.json` alone (a project is expected to customize its
permissions/hooks over time — that's not an error).

## Usage examples

### A GitHub project, end to end

```bash
# 1. Link the project (symlinks + copies mcp.json.template -> .mcp.json)
cd ~/dev/claude-shared-config
bin/link-project.sh ~/dev/my-app

# 2. Credentials: nothing is required for GitHub — sign in once with the GitHub CLI
#    (browser window) and the owner/repo come from the origin remote:
gh auth login
cd ~/dev/my-app
cp .claude/.env.example .claude/.env     # then set JIRA_WORKSPACE / JIRA_BASE_URL
#   (optional) pin explicit values instead:
#   GITHUB_OWNER=my-org   GITHUB_REPO=my-app
#   GITHUB_TOKEN=op://Dev Tooling/github-token/credential   # `op signin` first

# 3. Start Claude Code in the project (first start: sync-env.py enables the
#    `github` server and disables the unused ones; they apply from the next
#    start, so restart once), then:
#   /connect-git               -> host, credentials, live API + MCP check
#   /pr-review 42              -> structured review of PR #42
#   /answer-pr-comments 42 --dry-run
#   "list open issues labelled bug"   -> answered through the github MCP server
```

### A Bitbucket project

Same steps with the Bitbucket block filled in (`BITBUCKET_WORKSPACE`,
`BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`). The `github`
server is disabled for it (there is no Bitbucket MCP server) and the PR skills use the
`tools/bb_*.sh` REST scripts. `/connect-git` reports "REST tools only" for the MCP row
— that is expected.

### Switching a project from Bitbucket to GitHub

```bash
cd ~/dev/my-app && git remote set-url origin git@github.com:my-org/my-app.git
# fill in the GitHub block in .claude/.env, then start Claude Code twice:
# the first start flips the server lists, the second launches `github`.
```

No re-linking and no `.mcp.json` edits — the template already contains every server.

### GitHub Enterprise Server

```bash
# .claude/.env
GIT_HOST=github
GITHUB_API_URL=https://git.example.com/api/v3   # gh_*.sh REST tools
GITHUB_HOST=https://git.example.com             # github MCP server
```

### Connecting Jira / Confluence without an API key

With no usable `JIRA_EMAIL` + `JIRA_API_TOKEN` in `.claude/.env` (only `JIRA_BASE_URL` and
`JIRA_WORKSPACE` are required), the hosted `atlassian-oauth` server is enabled. Start Claude
Code, restart it once, then:

```
/mcp                      -> atlassian-oauth  (shows "needs authentication")
                             choose Authenticate -> the Atlassian authorization window opens
                             in your browser -> pick the site -> done
/get-jira-task MA-22
/get-confluence-page https://acme.atlassian.net/wiki/spaces/ENG/pages/123/Retry-Policy
```

Add `JIRA_EMAIL` + `JIRA_API_TOKEN` and the API-token `atlassian` server takes over at the next
start. The token is still needed for ticket **image attachments**, the REST fallback and the
PR-review Jira preflight — those use the REST API, which browser sign-in doesn't cover.

### Connecting Notion

**No API key (default).** Nothing to configure — the hosted `notion-oauth` server is enabled
automatically. Start Claude Code in the project, restart it once (the first start enables the
server), then:

```
/mcp                      -> notion-oauth  (shows "needs authentication")
                             choose Authenticate -> the Notion authorization window opens in
                             your browser -> pick the workspace/pages to share -> done
/get-notion-page https://www.notion.so/my-ws/Payments-Spec-0123456789abcdef0123456789abcdef
"summarise this spec: <notion url>"      -> the skill triggers on the link
```

**With an API key** (e.g. for CI, or to pin a specific integration):

```bash
# 1. notion.so/profile/integrations -> new internal integration -> copy the secret into 1Password
# 2. On each page Claude should read: page menu > Connections > add the integration
# 3. Uncomment in .claude/.env:
#      NOTION_TOKEN=op://Dev Tooling/notion-token/credential
# 4. Start Claude Code, then restart it once: sync-env.py switches from notion-oauth to the
#    token-based `notion` server.
```

**Not using Notion in a project:** `NOTION_MCP=off` in `.claude/.env`.

### Troubleshooting at a glance

| Symptom | Cause / fix |
| --- | --- |
| A server shows as failed in `/mcp` | Run it by hand: its stderr starts with `[mcp-run]` and names the missing/placeholder/unresolved key (`GITHUB_TOKEN is not set in …/.env`). Fix `.claude/.env`, restart |
| `/connect-git` shows `unresolved_op` | `op` missing or signed out — `op signin`, restart the session |
| `github` not listed in `/mcp` | Disabled by `sync-env.py` (git host isn't GitHub; Bitbucket has no MCP server). Fix `GIT_HOST` / the remote, then start a session and restart once |
| `atlassian-oauth` says "needs authentication" | Expected until you sign in: `/mcp` → `atlassian-oauth` → Authenticate (browser window) |
| `github` fails: `GITHUB_TOKEN is not set` | No token in `.env` and no `gh` session: run `gh auth login` (or set `GITHUB_TOKEN`), restart |
| `notion-oauth` says "needs authentication" | Expected until you sign in: `/mcp` → `notion-oauth` → Authenticate (browser window) |
| Neither Notion server listed | `NOTION_MCP=off` is set in `.claude/.env` |
| `github` fails on first start | The Docker image is being pulled — wait and restart. Docker must be running |
| Server not found / `.mcp.json` has no `github` | The project's `.mcp.json` is an old copy; delete it and re-run `bin/link-project.sh <project>` |
| 401 / 403 / 404 from a PR skill | Run `/connect-git`; it names the failing layer (token, scope, or owner/repo / workspace/slug) |
| Jira/Confluence skills work but `atlassian` is failed in `/mcp` | Expected — they fall back to REST. Test creds: `python3 .claude/tools/atlassian_fetch.py check` |
| Notion 404 on a page that exists | The page isn't shared with the integration (page menu > Connections) |

## What's here

- `skills/`, `agents/`, `tools/`, `hooks/`, `workflows/` — the actual shared content.
  None of it hardcodes a repo path; everything resolves the working project via
  `$CLAUDE_PROJECT_DIR` (set by Claude Code) or `git rev-parse --show-toplevel`.
  `workflows/` holds saved Workflow-tool scripts (e.g. `split-pr-analyze.js`, a hard
  dependency of the `split-pr` skill) — check any skill for `.claude/<dir>`
  references before assuming a new top-level `.claude/` folder is project-specific.
- `mcp.json.template` — copied (not symlinked) into each project's root `.mcp.json`.
  One static file with every MCP server. For each service there is a key-based server and,
  where the service offers it, a hosted server with browser sign-in (no API key):

  | Service | With an API key | Without one |
  | --- | --- | --- |
  | Jira / Confluence | `atlassian` (`JIRA_EMAIL` + `JIRA_API_TOKEN`) | `atlassian-oauth` — hosted `mcp.atlassian.com`, sign in once from `/mcp` |
  | Notion | `notion` (`NOTION_TOKEN`) | `notion-oauth` — hosted `mcp.notion.com`, sign in once from `/mcp` |
  | GitHub | `github` (`GITHUB_TOKEN`) | `github` with the token of your `gh auth login` browser session |
  | SonarQube | `sonarqube` (`SONAR_API_TOKEN`) | — |

  GitHub's hosted server can't do the same browser sign-in as the other two: its authorization
  server has no dynamic client registration, so Claude Code would need a pre-registered OAuth
  app. `gh auth login` is the equivalent — one browser sign-in, no key to create or store.

  Nothing in the template is project-specific and nothing is generated from a project: each
  stdio server is launched through `tools/mcp-run.py`, which reads the project's `.claude/.env`
  at server start and fills in the `{{KEY}}` (required) / `{{KEY|default}}` (optional)
  placeholders, resolving `op://` 1Password references in memory (secrets are never written to
  `.mcp.json`). `--fallback KEY=command` supplies a value when the key has no usable one
  (`GITHUB_TOKEN` ← `gh auth token`).
  Why a launcher: Claude Code expands `${VAR}` in `.mcp.json` only from the real process
  environment — not from `.claude/settings*.json` `env` — and substitutes `${VAR:-default}`
  before anything else sees it, so plain `${...}` can't be filled from `.claude/.env`.
  A real process-env variable still wins over the `.env` value. A missing, placeholder or
  unresolved required key makes that one server exit with a one-line `[mcp-run]` error
  instead of running half-configured.

  Which servers are *used* is decided at session start by `hooks/sync-env.py`: it approves
  the template's servers (`enabledMcpjsonServers`) and disables the ones the project doesn't
  use (`disabledMcpjsonServers`, in the project's `settings.local.json`): the key-based
  server when its credentials are usable, otherwise the hosted one (`atlassian`/`atlassian-oauth`,
  `notion`/`notion-oauth`; `NOTION_MCP=off` disables both Notion servers); `github` only when
  the git host is GitHub (same detection as the PR tools: `GIT_HOST`, then the `origin` URL,
  then `GITHUB_OWNER`) — Bitbucket has no MCP server, the PR skills use `tools/bb_*.sh`. For
  GitHub it also fills a missing `GITHUB_OWNER`/`GITHUB_REPO` from the origin remote and a
  missing `GITHUB_TOKEN` from `gh auth token`. Claude Code reads the lists at startup, so a
  change applies from the *next* session start. Entries you add yourself for other servers
  are left alone.
- `settings.json.template` — generated (copied, not symlinked) into a project's
  `.claude/settings.json` the first time it's linked, the same way as `.mcp.json`
  above. Only generated when no `settings.json` exists yet; once a project has one,
  it's free to diverge (different permissions, extra hooks) and `link-project.sh`
  will never touch it again. Currently wires up `sync-env.py` (SessionStart) and
  `biome-pretooluse.py` (PreToolUse on Write/Edit) — the latter no-ops silently on
  projects without a `node_modules/.bin/biome`, so it's safe as a shared default.
  `biome-pretooluse.py` checks prospective content via a throwaway sibling temp
  file (`.pretooluse-tmp-*`) in the same directory as the file being saved —
  add `**/.pretooluse-tmp-*` to the project's `.gitignore` so it doesn't get
  picked up by VCS-aware tooling if a crash ever leaves one behind.
- `env.example` — template for a project's `.claude/.env`. Secret fields use
  `op://` (1Password) references; see the file header for setup. Includes both
  Bitbucket and GitHub credential blocks — `GIT_HOST` (or `tools/detect_git_host.sh`'s
  auto-detection from `git remote get-url origin`) picks which one the
  PR-related skills use and whether the `github` MCP server is enabled. Notion needs no entry by default
  (hosted OAuth server); the commented `NOTION_TOKEN` / `NOTION_MCP=off` switch to an API key or turn it off.
- `bin/link-project.sh <path>` — wires a project to this repo (symlinks +
  generates `.mcp.json`). It refuses to replace foreign symlinks or an
  existing `.mcp.json` that differs from the template.

## Skills

Invoked as `/<skill-name>` (or by the natural-language triggers noted below), unless marked delegates-only.

| Skill | What it does | When it's used |
| --- | --- | --- |
| `answer-pr-comments` | Answers unanswered human reviewer comments on a Bitbucket or GitHub PR. Default: composes and posts replies via the `comment-responder` agent. With `--fix`: verifies each comment against the code, fixes the valid ones, declines the rest with evidence, runs the project's checks, then commits, pushes and posts after one confirmation. | `/answer-pr-comments <pr-number> [<reviewer-name>] [--dry-run] [--fix]` |
| `caveman` | Token-efficient caveman-mode responses (~75% fewer tokens, full technical accuracy). | `/caveman`, or saying "less tokens" / "be brief"; stays active until "stop caveman" / "normal mode" |
| `connect-git` | Verifies the project's git-hosting connection: resolves Bitbucket vs GitHub, checks the credentials in `.claude/.env`, tests them against the host API, and confirms the matching MCP server (GitHub) is in `.mcp.json` and answers a live read-only call; reports Notion status. Read-only. | `/connect-git`; first-time setup, after switching remotes, or when PR skills return 401/403/404 |
| `create-jira-task` | Creates one or more Jira issues (default type Task), optionally as children of a parent issue such as an Epic. A real **write** operation against Jira Cloud. | `/create-jira-task [--parent=KEY] [--project=KEY] [--issuetype=NAME] [--dry-run]` |
| `feature-doc` | Generates a plain-English feature doc from the current branch's Jira ticket and diff, readable by QA/PMs/tech leads without code knowledge. | `/feature-doc [ticket-key] [output-path]` |
| `get-confluence-page` | Fetches a Confluence page by URL or ID and renders it as Markdown, following embedded links two levels deep. Atlassian MCP first, REST fallback (`tools/atlassian_fetch.py`) if the MCP server is down. | User provides a Confluence URL, or a Jira issue being read links to one |
| `get-jira-task` | Fetches a Jira issue — title, status, description, subtasks, and every linked Confluence page in full (two levels deep, classified by type); delegates to the `jira-context` agent. Atlassian MCP first, automatic REST fallback if the MCP server is down (the output's `Source:` line says which). Also downloads and analyzes the ticket's image attachments (screenshots, mockups, diagrams; `--no-images` / `--max-images=N`). | User references a ticket number, or acceptance-criteria/spec context is needed before starting work; `/get-jira-task <key> [--no-images] [--max-images=N] [-- <repo-path>...]` |
| `get-notion-page` | Fetches a Notion page by URL or ID as Markdown, following linked Notion pages one level deep. Prefers the Notion MCP tools (token-based `notion` server, then the hosted `notion-oauth` server / claude.ai connector — no API key needed, sign in once from `/mcp`) and falls back to a REST script using `NOTION_TOKEN`. Read-only. | User provides a Notion URL, or a ticket/PR links to one; `/get-notion-page --check` verifies the token |
| `implement` | Architect/staff-dev skill: fetches a Jira ticket and linked Confluence docs, reads related repos if provided, and produces a detailed implementation plan in `.claude/plans/` for approval before any code is written. | `/implement <ticket-key> [-- <repo1> [<repo2> ...]]` |
| `pr-review` | Reviews a Bitbucket or GitHub PR (by number, URL, or branch): batch-fetches every linked Jira ticket / Confluence page, asks about cross-service dependencies, then delegates to the `pr-reviewer` agent for a full structured review. | `/pr-review <pr-number \| url \| branch>` |
| `project-blueprint` | Turns a ticket or a free-text feature description into a pre-implementation project blueprint — architecture, service ownership, API inventory, proposed directory tree, phased roadmap — grounded in technologies/patterns already used elsewhere in the org. Reuses `jira-context` for ticket fetching and `project-overview`'s scanner for repo/sibling inspection. Planning documents only, no code. | `/project-blueprint <ticket-key \| free-text description> [-- <repo1> [<repo2> ...]]` |
| `project-overview` | Produces an evidence-based technical/architectural overview of a repo or service — purpose, tech stack, architecture, dependency map, ecosystem relationships, risks/gaps — every claim cited to a file, line, or URL. Read-only. | `/project-overview [<path>] [-- <repo1> [<repo2> ...]]` |
| `security-audit` | Scans a Claude Code config tree (skills/agents/tools/hooks/workflows, `mcp.json`, `settings.json`, env templates) for hardcoded secrets, project-specific identifiers, values that belong in a project-local `.env`, and overly-broad tool/permission scopes. Read-only. | `/security-audit [path]` |
| `sonar-triage` | Fetches and triages SonarQube Cloud issues (PR, branch, or main) and proposes a fix for each, checking a project-local `.claude/sonar-known-issues.md` (if present) for confirmed false positives. Analysis only. | `/sonar-triage [pr <number> \| branch <name> \| main]` |
| `split-pr` | Analyzes a large/complex PR or branch and proposes how to split it into smaller, dependency-ordered (stacked) PRs. Analysis only unless `--apply` is passed. | `/split-pr [<pr-identifier> \| <branch>] [--base=<branch>] [--apply] [--interactive]` |

## Agents

Subagents invoked by the skills above — not called directly by name.

| Agent | What it does | Invoked by |
| --- | --- | --- |
| `comment-responder` | Fetches unanswered PR comments (all pages), reads the current state of each referenced file and any `.claude/reviews/` analysis, composes accurate Fixed/Deferred/Answered replies, and posts them. Also runs as `collect` (fetch only) and `post` (post pre-composed replies, skipping answered ones) for the `--fix` flow. | `answer-pr-comments` |
| `feature-planner` | Architect-level planner: takes a fully-populated Jira context block plus codebase access and produces a concrete implementation plan saved to `.claude/plans/`. Writes no production code. | `implement` |
| `jira-context` | Fetches a Jira ticket and exhaustively pulls every referenced Confluence page (two levels deep), full bodies, classified by type; also reads `CLAUDE.md` from the primary and any related repos. Uses the Atlassian MCP tools, falling back to `tools/atlassian_fetch.py` (REST) when they're unavailable. | `get-jira-task`, `implement`, `pr-review` |
| `pr-reviewer` | Reviews a Bitbucket or GitHub PR end-to-end: fetches diff/commits/comments/Jira context, classifies changed files, reads the working tree, and returns one structured review. Read-only. | `pr-review` |

## What's NOT here (stays per-project, never write project values back into this repo)

`.claude/.env`, `.claude/settings.local.json`, `.claude/plans/`,
`.claude/reviews/`, `.claude/worktrees/`, and any other session/runtime state
are never templated here at all. `.claude/settings.json` and `.mcp.json` are
copied *from* this repo once (see `settings.json.template` / `mcp.json.template`
above), but the copy then belongs to the project — `link-project.sh` never
overwrites either one afterward, so a project's customizations never need to
(and never should) get written back here. Project `.gitignore` must exclude
`.claude/.env`, `.claude/settings.local.json`, `.mcp.json`, and (if the project
uses Biome) `**/.pretooluse-tmp-*` — see the `biome-pretooluse.py` note above.
