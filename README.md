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
# 1. Link (the origin remote is github.com -> the `github` MCP server is generated)
cd ~/dev/claude-shared-config
bin/link-project.sh ~/dev/my-app
#   [render-mcp] git host: github; added: github

# 2. Credentials: copy the template, fill in the GitHub block + Jira block
cd ~/dev/my-app
cp .claude/.env.example .claude/.env
#   GITHUB_OWNER=my-org
#   GITHUB_REPO=my-app
#   GITHUB_TOKEN=op://Dev Tooling/github-token/credential
op signin                      # token fields are 1Password references

# 3. Start Claude Code in the project, then:
#   /connect-git               -> host, credentials, live API + MCP check
#   /pr-review 42              -> structured review of PR #42
#   /answer-pr-comments 42 --dry-run
#   "list open issues labelled bug"   -> answered through the github MCP server
```

### A Bitbucket project

Same steps; the `origin` remote is `bitbucket.org`, so no git MCP server is added
and the PR skills use the `bb_*.sh` REST scripts. Fill in the Bitbucket block
(`BITBUCKET_WORKSPACE`, `BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`).
`/connect-git` reports "REST tools only" for the MCP row — that is expected.

### Switching a project from Bitbucket to GitHub

```bash
cd ~/dev/my-app && git remote set-url origin git@github.com:my-org/my-app.git
# fill in the GitHub block in .claude/.env, then:
cd ~/dev/claude-shared-config && bin/link-project.sh ~/dev/my-app
#   regenerated .../.mcp.json (it was an untouched generated file ...)
# restart the Claude session, then /connect-git
```

If `.mcp.json` was edited by hand, `link-project.sh` refuses and prints the command
that renders the servers to merge in manually
(`python3 bin/render-mcp.py <project>`).

### GitHub Enterprise Server

```bash
# .claude/.env
GIT_HOST=github
GITHUB_API_URL=https://git.example.com/api/v3
```

Re-link; `.mcp.json` gets the Docker `github-mcp-server` pointed at
`https://git.example.com` (Docker must be running).

### Adding Notion to a project

```bash
# 1. notion.so/profile/integrations -> new internal integration -> copy the secret into 1Password
# 2. On each page Claude should read: page menu > Connections > add the integration
# 3. Uncomment in .claude/.env:
#      NOTION_TOKEN=op://Dev Tooling/notion-token/credential
# 4. Re-link and restart the session
cd ~/dev/claude-shared-config && bin/link-project.sh ~/dev/my-app
#   [render-mcp] git host: github; added: github, notion

# In Claude Code:
#   /get-notion-page --check
#   /get-notion-page https://www.notion.so/my-ws/Payments-Spec-0123456789abcdef0123456789abcdef
#   "summarise this spec: <notion url>"      -> the skill triggers on the link
```

### Troubleshooting at a glance

| Symptom | Cause / fix |
| --- | --- |
| `[sync-env] git host is github but .mcp.json has no 'github' MCP server` | Project was linked before it moved to GitHub — re-run `bin/link-project.sh <project>`, restart |
| `[sync-env] NOTION_TOKEN is set but .mcp.json has no 'notion' MCP server` | Token added after linking — re-run `bin/link-project.sh <project>`, restart |
| `/connect-git` shows `unresolved_op` | `op` missing or signed out — `op signin`, restart the session |
| 401 / 403 / 404 from a PR skill | Run `/connect-git`; it names the failing layer (token, scope, or owner/repo / workspace/slug) |
| Notion 404 on a page that exists | The page isn't shared with the integration (page menu > Connections) |
| `github` / `notion` shown as failed in `/mcp` | Token unresolved (see above), or Docker not running (GHES only) |

## What's here

- `skills/`, `agents/`, `tools/`, `hooks/`, `workflows/` — the actual shared content.
  None of it hardcodes a repo path; everything resolves the working project via
  `$CLAUDE_PROJECT_DIR` (set by Claude Code) or `git rev-parse --show-toplevel`.
  `workflows/` holds saved Workflow-tool scripts (e.g. `split-pr-analyze.js`, a hard
  dependency of the `split-pr` skill) — check any skill for `.claude/<dir>`
  references before assuming a new top-level `.claude/` folder is project-specific.
- `mcp.json.template` + `mcp.d/` — rendered by `bin/render-mcp.py` (copied, not
  symlinked) into each project's root `.mcp.json`. The template holds the servers
  every project gets (Atlassian, SonarQube); `mcp.d/` holds the ones that depend on
  what the project uses, picked automatically at link time:
  - **GitHub project** (same host resolution as the PR tools: `GIT_HOST`, then the
    `origin` URL, then `GITHUB_OWNER`) → `github` MCP server using `GITHUB_TOKEN`.
    github.com uses GitHub's hosted endpoint; setting `GITHUB_API_URL` to an
    enterprise endpoint switches to the Docker `github-mcp-server` pointed at that host.
  - **Bitbucket project** → no MCP server (none exists); the PR skills use the
    `tools/bb_*.sh` REST scripts with the Bitbucket credentials.
  - **`NOTION_TOKEN` set in `.claude/.env`** → `notion` MCP server.

  All values are `${VAR}` references resolved from the project's own `.claude/.env`.
  Re-run `bin/link-project.sh` after changing the remote, `GIT_HOST`, or
  `NOTION_TOKEN`: a `.mcp.json` it generated is regenerated (it stamps a hash in
  `.claude/.mcp.generated.sha256` to recognise its own output), a hand-edited one is
  refused. `hooks/sync-env.py` warns at session start when `.mcp.json` is missing the
  server the project's host/env calls for.
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
  PR-related skills use and which git MCP server gets generated. Notion is an
  opt-in commented block (`NOTION_TOKEN`).
- `bin/render-mcp.py <path>` — prints the `.mcp.json` a project should have (template +
  matching `mcp.d/` fragments) to stdout; `link-project.sh` calls it, and you can run it
  directly to see or merge what would be generated.
- `bin/link-project.sh <path>` — wires a project to this repo (symlinks +
  generates `.mcp.json`). It refuses to replace foreign symlinks or a
  hand-edited `.mcp.json`.

## Skills

Invoked as `/<skill-name>` (or by the natural-language triggers noted below), unless marked delegates-only.

| Skill | What it does | When it's used |
| --- | --- | --- |
| `answer-pr-comments` | Answers unanswered human reviewer comments on a Bitbucket or GitHub PR. Default: composes and posts replies via the `comment-responder` agent. With `--fix`: verifies each comment against the code, fixes the valid ones, declines the rest with evidence, runs the project's checks, then commits, pushes and posts after one confirmation. | `/answer-pr-comments <pr-number> [<reviewer-name>] [--dry-run] [--fix]` |
| `caveman` | Token-efficient caveman-mode responses (~75% fewer tokens, full technical accuracy). | `/caveman`, or saying "less tokens" / "be brief"; stays active until "stop caveman" / "normal mode" |
| `connect-git` | Verifies the project's git-hosting connection: resolves Bitbucket vs GitHub, checks the credentials in `.claude/.env`, tests them against the host API, and confirms the matching MCP server (GitHub) is in `.mcp.json` and answers a live read-only call; reports Notion status. Read-only. | `/connect-git`; first-time setup, after switching remotes, or when PR skills return 401/403/404 |
| `create-jira-task` | Creates one or more Jira issues (default type Task), optionally as children of a parent issue such as an Epic. A real **write** operation against Jira Cloud. | `/create-jira-task [--parent=KEY] [--project=KEY] [--issuetype=NAME] [--dry-run]` |
| `feature-doc` | Generates a plain-English feature doc from the current branch's Jira ticket and diff, readable by QA/PMs/tech leads without code knowledge. | `/feature-doc [ticket-key] [output-path]` |
| `get-confluence-page` | Fetches a Confluence page by URL or ID and renders it as Markdown, following embedded links two levels deep. | User provides a Confluence URL, or a Jira issue being read links to one |
| `get-jira-task` | Fetches a Jira issue — title, status, description, subtasks, and every linked Confluence page in full (two levels deep, classified by type); delegates to the `jira-context` agent. | User references a ticket number, or acceptance-criteria/spec context is needed before starting work |
| `get-notion-page` | Fetches a Notion page by URL or ID as Markdown, following linked Notion pages one level deep. Prefers the Notion MCP tools (project `notion` server, then the claude.ai connector) and falls back to a REST script using `NOTION_TOKEN` (the page must be shared with the integration). Read-only. | User provides a Notion URL, or a ticket/PR links to one; `/get-notion-page --check` verifies the token |
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
| `jira-context` | Fetches a Jira ticket and exhaustively pulls every referenced Confluence page (two levels deep), full bodies, classified by type; also reads `CLAUDE.md` from the primary and any related repos. | `get-jira-task`, `implement`, `pr-review` |
| `pr-reviewer` | Reviews a Bitbucket or GitHub PR end-to-end: fetches diff/commits/comments/Jira context, classifies changed files, reads the working tree, and returns one structured review. Read-only. | `pr-review` |

## What's NOT here (stays per-project, never write project values back into this repo)

`.claude/.env`, `.claude/settings.local.json`, `.claude/plans/`,
`.claude/reviews/`, `.claude/worktrees/`, and any other session/runtime state
are never templated here at all. `.claude/settings.json` and `.mcp.json` are
generated *from* this repo (see `settings.json.template` / `mcp.json.template`
and `mcp.d/` above), but the generated file then belongs to the project:
`link-project.sh` never overwrites a customized `settings.json`, and only
regenerates a `.mcp.json` it generated itself and that is still untouched
(recognised by the hash in `.claude/.mcp.generated.sha256`) — so a project's
customizations never need to (and never should) get written back here.
Project `.gitignore` must exclude `.claude/.env`, `.claude/settings.local.json`,
`.mcp.json`, `.claude/.mcp.generated.sha256`, and (if the project uses Biome)
`**/.pretooluse-tmp-*` — see the `biome-pretooluse.py` note above.
