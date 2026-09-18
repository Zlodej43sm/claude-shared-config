# claude-shared-config

Shared, version-controlled Claude Code setup — skills, subagents, and MCP server
config, linked into every project instead of copy-pasted per repo. Includes
ready-made skills for Jira/Confluence context-gathering, Bitbucket/GitHub PR
review and comment-answering, SonarQube triage, PR-splitting, and plan-first
feature implementation.

## Quick start

Link this repo into a project — symlinks `skills/`, `agents/`, `tools/`,
`hooks/`, and `workflows/` into the project's `.claude/`, and generates its
`.mcp.json`:

```bash
bin/link-project.sh <project_path>
```

Then copy the generated `.claude/.env.example` to `.claude/.env` and fill in
the per-project values. It safely reuses only its own symlinks and refuses to
overwrite an existing `.mcp.json`.

## What's here

- `skills/`, `agents/`, `tools/`, `hooks/`, `workflows/` — the actual shared content.
  None of it hardcodes a repo path; everything resolves the working project via
  `$CLAUDE_PROJECT_DIR` (set by Claude Code) or `git rev-parse --show-toplevel`.
  `workflows/` holds saved Workflow-tool scripts (e.g. `split-pr-analyze.js`, a hard
  dependency of the `split-pr` skill) — check any skill for `.claude/<dir>`
  references before assuming a new top-level `.claude/` folder is project-specific.
- `mcp.json.template` — generated (copied, not symlinked) into each project's root
  `.mcp.json`. All values are `${VAR}` references resolved from that project's own
  `.claude/.env` — the template itself never changes per project.
- `env.example` — template for a project's `.claude/.env`. Secret fields use
  `op://` (1Password) references; see the file header for setup. Includes both
  Bitbucket and GitHub credential blocks — `GIT_HOST` (or `tools/detect_git_host.sh`'s
  auto-detection from `git remote get-url origin`) picks which one the
  PR-related skills use.
- `bin/link-project.sh <path>` — wires a project to this repo (symlinks +
  generates `.mcp.json`). It refuses to replace foreign symlinks or an
  existing `.mcp.json`.

## Skills

Invoked as `/<skill-name>` (or by the natural-language triggers noted below), unless marked delegates-only.

| Skill | What it does | When it's used |
| --- | --- | --- |
| `answer-pr-comments` | Composes and posts replies to unanswered human reviewer comments on a Bitbucket or GitHub PR; delegates the fetch/research/compose/post cycle to the `comment-responder` agent. | `/answer-pr-comments <pr-number> [<reviewer-name>] [--dry-run]` |
| `caveman` | Token-efficient caveman-mode responses (~75% fewer tokens, full technical accuracy). | `/caveman`, or saying "less tokens" / "be brief"; stays active until "stop caveman" / "normal mode" |
| `create-jira-task` | Creates one or more Jira issues (default type Task), optionally as children of a parent issue such as an Epic. A real **write** operation against Jira Cloud. | `/create-jira-task [--parent=KEY] [--project=KEY] [--issuetype=NAME] [--dry-run]` |
| `feature-doc` | Generates a plain-English feature doc from the current branch's Jira ticket and diff, readable by QA/PMs/tech leads without code knowledge. | `/feature-doc [ticket-key] [output-path]` |
| `get-confluence-page` | Fetches a Confluence page by URL or ID and renders it as Markdown, following embedded links two levels deep. | User provides a Confluence URL, or a Jira issue being read links to one |
| `get-jira-task` | Fetches a Jira issue — title, status, description, subtasks, and every linked Confluence page in full (two levels deep, classified by type); delegates to the `jira-context` agent. | User references a ticket number, or acceptance-criteria/spec context is needed before starting work |
| `implement` | Architect/staff-dev skill: fetches a Jira ticket and linked Confluence docs, reads related repos if provided, and produces a detailed implementation plan in `.claude/plans/` for approval before any code is written. | `/implement <ticket-key> [-- <repo1> [<repo2> ...]]` |
| `pr-review` | Reviews a Bitbucket or GitHub PR (by number, URL, or branch): batch-fetches every linked Jira ticket / Confluence page, asks about cross-service dependencies, then delegates to the `pr-reviewer` agent for a full structured review. | `/pr-review <pr-number \| url \| branch>` |
| `security-audit` | Scans a Claude Code config tree (skills/agents/tools/hooks/workflows, `mcp.json`, `settings.json`, env templates) for hardcoded secrets, project-specific identifiers, values that belong in a project-local `.env`, and overly-broad tool/permission scopes. Read-only. | `/security-audit [path]` |
| `sonar-triage` | Fetches and triages SonarQube Cloud issues (PR, branch, or main) and proposes a fix for each, checking a project-local `.claude/sonar-known-issues.md` (if present) for confirmed false positives. Analysis only. | `/sonar-triage [pr <number> \| branch <name> \| main]` |
| `split-pr` | Analyzes a large/complex PR or branch and proposes how to split it into smaller, dependency-ordered (stacked) PRs. Analysis only unless `--apply` is passed. | `/split-pr [<pr-identifier> \| <branch>] [--base=<branch>] [--apply] [--interactive]` |

## Agents

Subagents invoked by the skills above — not called directly by name.

| Agent | What it does | Invoked by |
| --- | --- | --- |
| `comment-responder` | Fetches unanswered PR comments, reads the current state of each referenced file and any `.claude/reviews/` analysis, composes accurate Fixed/Deferred/Answered replies, and posts them. | `answer-pr-comments` |
| `feature-planner` | Architect-level planner: takes a fully-populated Jira context block plus codebase access and produces a concrete implementation plan saved to `.claude/plans/`. Writes no production code. | `implement` |
| `jira-context` | Fetches a Jira ticket and exhaustively pulls every referenced Confluence page (two levels deep), full bodies, classified by type; also reads `CLAUDE.md` from the primary and any related repos. | `get-jira-task`, `implement`, `pr-review` |
| `pr-reviewer` | Reviews a Bitbucket or GitHub PR end-to-end: fetches diff/commits/comments/Jira context, classifies changed files, reads the working tree, and returns one structured review. Read-only. | `pr-review` |

## What's NOT here (stays per-project, never write project values back into this repo)

`.claude/.env`, `.claude/settings.json`, `.claude/settings.local.json`,
`.claude/plans/`, `.claude/reviews/`, `.claude/worktrees/`, and any other
session/runtime state. Project `.gitignore` must exclude `.claude/.env`,
`.claude/settings.local.json`, and `.mcp.json`.
