# claude-shared-config

Shared, version-controlled Claude Code setup — skills, subagents, and MCP server
config, linked into every project instead of copy-pasted per repo. Includes
ready-made skills for Jira/Confluence/Notion context-gathering, Bitbucket/GitHub/Azure DevOps
connection setup, PR review and comment-answering, SonarQube triage, PR-splitting, plan-first
feature implementation, design-to-code (Figma, screenshots or live sites → per-block specs →
pixel-diffed UI), evidence-based repository/service overviews, and
security auditing of application code and of this shared config tree itself.

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
`.mcp.json` that diverges from the template (unless `--refresh-mcp`), and leaves
an existing, diverged `.claude/settings.json` alone (a project is expected to
customize its permissions/hooks over time — that's not an error).

### A project that already has its own `.claude/`

If the project already has a real `.claude/skills` (or `agents`, `tools`, `hooks`,
`workflows`) directory with entries of its own, `link-project.sh` asks what to do
with it, once per directory:

```
The project already has its own .claude/skills: 2 entr(ies) — my-own-skill pr-review
  same name as a shared one: pr-review
  committed to the project's git repo
What should happen with the shared skills?
  1) extend   keep the project's entries and link the shared ones next to them;
              the project's same-named entries win  (default)
  2) rewrite  replace .claude/skills with a link to the shared folder
              (the project's copy is backed up to .backups/<project>/ first)
              committed, so git will then show its files as deleted
  3) skip     leave .claude/skills as it is and link nothing into it
  4) custom   extend, but choose which shared entries to leave out and
              which same-named project entries the shared version replaces
Choice [1-4, Enter = extend]:
```

- **extend** (Enter) never touches the project's files — see the per-entry linking
  described under [Keeping linked projects up to date](#keeping-linked-projects-up-to-date).
- **rewrite** asks for a `y` first, copies the directory to
  `.backups/<project>/claude.<timestamp>/`, then replaces it with a symlink. For a
  committed directory prefer extend: a `git pull` that changes it brings it back.
- **custom** lists the shared entries by number; answer with numbers or names
  (`1 caveman`) to leave some out, then name the same-named entries the shared
  version should replace (each backed up first).

The answer goes to `.link-choices` (local, gitignored), so re-runs and
`bin/sync-projects.sh` don't ask again. To change it, run
`bin/link-project.sh --existing ask <project>`. `--existing extend|rewrite|skip` answers
for every such directory without asking. With no terminal (piped, CI) and no
`--existing`, the default (extend) is used, and `--dry-run` previews extend.

### Keeping linked projects up to date

After pulling changes to this repo (a new shared folder, new MCP servers in
`mcp.json.template`), refresh every linked project at once:

```bash
bin/sync-projects.sh --dry-run   # preview
bin/sync-projects.sh             # apply
bin/sync-projects.sh --verify    # apply, then confirm Claude Code loads every shared skill/agent
```

Run it again after a `git pull` in a project that commits its own `.claude/skills`
(see below) — and whenever a skill you expect is missing from `/` in a project.

It finds the projects from `.linked-projects` (every `link-project.sh` run records
its project there) plus a scan of this repo's parent directory for `.claude/`
symlinks pointing here, then runs `link-project.sh --refresh-mcp` on each:

- adds any missing symlink (a folder added to `LINK_DIRS` in `bin/link-project.sh`
  since the project was linked);
- if the project keeps its **own** `.claude/skills`, `agents` or `hooks` as a real
  directory (typically committed to the project's repo by its team — a `git pull`
  there replaces a whole-folder symlink with the committed folder, hiding every shared
  skill), links each shared skill/agent/hook into that directory one by one instead.
  The project's same-named entries win (reported as "project's own version kept"),
  committed files are never touched, links to entries since removed here are deleted,
  and the new links are git-ignored via `.git/info/exclude` (local, never committed);
- replaces a `.mcp.json` that differs from the template, keeping the old copy in
  `.backups/<project>/mcp.json.<timestamp>` (per-project values belong in
  `.claude/.env`, which the template's `{{VAR}}` placeholders read). `--keep-mcp`
  reports the drift instead;
- reports, without touching, a `.claude/settings.json` that diverges from the template
  and any `env.example` keys the project's `.claude/.env` doesn't mention (names only).

Options: `--scan DIR` (repeatable) searches other directories; naming projects
(`bin/sync-projects.sh ~/dev/a ~/dev/b`) syncs only those. `--verify` starts a minimal
headless session (`claude -p`, one short model call) in each project and compares the
skills and agents Claude Code reports at startup with this repo's, listing any that
aren't loaded; a project that fails verification counts as failed. Projects that no
longer exist are dropped from `.linked-projects`. Skills and agents are picked up by
the next session; restart Claude Code in a project with a refreshed `.mcp.json`
twice — the first start lets `sync-env.py` enable/disable the new servers.

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
#   GITHUB_TOKEN="op://Dev Tooling/github-token/credential"   # `op signin` first

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

### An Azure DevOps project

Nothing to fill in: the host, org, project and repo come from the origin remote
(`dev.azure.com/<org>/<project>/_git/<repo>`). Start Claude Code, then restart it once so
the `azure-devops` server launches. Without a token its first call in a session opens a
browser window for the Microsoft account sign-in; set `AZURE_DEVOPS_PAT` to use a personal
access token instead. It runs through `npx`, so Node.js must be installed.

```bash
/connect-git                                   # host, org/project/repo, live MCP read
/pr-review https://dev.azure.com/my-org/My%20Project/_git/api/pullrequest/42
/answer-pr-comments 42 --dry-run
```

The PR skills read the PR and its threads and post through the `azure-devops` server, and
take diffs and code from the local clone (`skills/pr-review/references/azure-devops.md`).
In a workspace root that is not a repo, paste the project URL into `.claude/.env`
(`AZURE_DEVOPS_URL=https://dev.azure.com/<org>/<project>/_git`) to turn the server on, and
pass PR URLs; the skills find the clone in a subdirectory.

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

Every Jira/Confluence read tries the hosted Atlassian MCP connector first (browser sign-in, no
API key): `atlassian-oauth`, or your claude.ai Atlassian connector. `JIRA_EMAIL` +
`JIRA_API_TOKEN` are only a fallback; no skill stops because they are missing. The order lives
in `agents/jira-context.md` → "Access paths". Sign in once:

```
/mcp                      -> atlassian-oauth  (shows "needs authentication")
                             choose Authenticate -> the Atlassian authorization window opens
                             in your browser -> pick the site -> done
/get-jira-task PROJ-22
/get-confluence-page https://acme.atlassian.net/wiki/spaces/ENG/pages/123/Retry-Policy
```

The token is still needed for ticket **image attachments** (REST download) and for the
REST fallback when no MCP connector is signed in.

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
#      NOTION_TOKEN="op://Dev Tooling/notion-token/credential"
# 4. Start Claude Code, then restart it once: sync-env.py switches from notion-oauth to the
#    token-based `notion` server.
```

**Not using Notion in a project:** `NOTION_MCP=off` in `.claude/.env`.

### Design to code (Figma, screenshots, live sites)

The design servers are off by default. Turn them on in a front-end project:

```
# .claude/.env
DESIGN_MCP=on
```

Start Claude Code, restart it once (the first start enables `figma` and `playwright`), then:

```
/mcp                      -> figma  (shows "needs authentication")
                             choose Authenticate -> allow access in the browser -> done
/design-spec https://www.figma.com/design/<fileKey>/Home?node-id=12-34
                          -> .claude/design/home/: design.md, tokens.json, assets/,
                             blocks/01-header/{spec.md,reference.png}, blocks/02-hero/…
/design-spec https://example.com --block=footer      -> one block of a live page
/design-spec ~/Desktop/checkout.png                  -> blocks measured from a screenshot
/design-build .claude/design/home                    -> plan, then code block by block,
                                                        each diffed against reference.png
```

Figma's read tools are rate-limited per seat and plan; `design-spec` counts the calls it
needs and asks first when the budget is tight.

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
| `figma` / `playwright` not listed in `/mcp` | Off unless `DESIGN_MCP=on` is in `.claude/.env`; set it, then start a session and restart once. Still missing: the project's `.mcp.json` predates them; run `bin/sync-projects.sh` |
| Notion 404 for a page you can open in the browser, even after re-authenticating | `notion-oauth` is signed into another workspace (a personal one can have the same name). `/get-notion-page --check` prints the workspace id; `/mcp` → `notion-oauth` → Authenticate and pick the right workspace in the consent screen's switcher; then set `NOTION_WORKSPACE_ID` in `.claude/.env` |
| `github` fails on first start | The Docker image is being pulled — wait and restart. Docker must be running |
| `azure-devops` not listed in `/mcp` | Disabled by `sync-env.py`: the host isn't Azure DevOps and no org is known. Set `AZURE_DEVOPS_URL` (or `AZURE_DEVOPS_ORG`), start a session and restart once |
| `azure-devops` fails: `AZURE_DEVOPS_ORG is not set` | No org in `AZURE_DEVOPS_ORG`, `AZURE_DEVOPS_URL` or an Azure DevOps origin remote (e.g. a workspace root): set `AZURE_DEVOPS_URL` in `.claude/.env`, restart |
| Shared skills missing from `/` in one project (only a few, project-specific ones show) | The project commits its own `.claude/skills`, and a `git pull` replaced the symlink with that folder. Run `bin/sync-projects.sh --verify` — it links the shared skills into the folder one by one |
| Server not found / `.mcp.json` has no `github` | The project's `.mcp.json` is an old copy; run `bin/sync-projects.sh` (or `bin/link-project.sh --refresh-mcp <project>`) |
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
  | Figma | — | `figma` — hosted `mcp.figma.com`, sign in once from `/mcp` |
  | GitHub | `github` (`GITHUB_TOKEN`) | `github` with the token of your `gh auth login` browser session |
  | Azure DevOps | `azure-devops` (`AZURE_DEVOPS_PAT`) | `azure-devops` — `@azure-devops/mcp`, browser sign-in on its first call in a session |
  | SonarQube | `sonarqube` (`SONAR_API_TOKEN`) | — |

  GitHub's hosted server can't do the same browser sign-in as the other two: its authorization
  server has no dynamic client registration, so Claude Code would need a pre-registered OAuth
  app. `gh auth login` is the equivalent — one browser sign-in, no key to create or store.

  The `github` server runs read-only (`GITHUB_READ_ONLY=1`); the PR skills post over the
  REST API (`tools/gh_post_comment.sh`, the `comment-responder` agent). The Docker images
  are pinned by digest. The `uvx`/`npx` servers pin their package version and resolve its
  dependencies as of a fixed date (`--exclude-newer` / `--before`), so a dependency published
  later never gets in; move the date together with the version. The `notion` and `sonarqube`
  servers can do whatever their token allows; `env.example` says how to limit each token.
  `azure-devops` loads only its `core` and `repositories` tools; `settings.json.template`
  denies its file, branch and PR-state writes and asks before it posts a comment.
  `playwright` (a headless browser for the design skills) needs no credentials; it runs
  with an in-memory profile (`--isolated`), so no cookies or logins persist between sessions.

  Nothing in the template is project-specific and nothing is generated from a project: each
  stdio server is launched through `tools/mcp-run.py`, which reads the project's `.claude/.env`
  at server start and fills in the `{{KEY}}` (required) / `{{KEY|default}}` (optional; the default may
  reference other keys as `{KEY}`, e.g. `{{CONFLUENCE_BASE_URL|{JIRA_BASE_URL}/wiki}}`) / `{{KEY?then:else}}`
  (text chosen by whether the key is set, e.g. `{{AZURE_DEVOPS_PAT?pat:interactive}}`) placeholders, resolving `op://` 1Password references in memory (secrets are never written to
  `.mcp.json`). `--fallback KEY=command` supplies a value when the key has no usable one
  (`GITHUB_TOKEN` ← `gh auth token`, `AZURE_DEVOPS_ORG` ← `azure_repo.py org`); `--env-b64` exports a
  value base64-encoded (the Azure DevOps token).
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
  `notion`/`notion-oauth`; `NOTION_MCP=off` disables both Notion servers); `figma` and
  `playwright` only with `DESIGN_MCP=on`; `github` only when
  the git host is GitHub (same detection as the PR tools: `GIT_HOST`, then the `origin` URL,
  then `GITHUB_OWNER`) — Bitbucket has no MCP server, the PR skills use `tools/bb_*.sh`;
  `azure-devops` when the host is Azure DevOps or an org is known (`AZURE_DEVOPS_ORG`, `AZURE_DEVOPS_URL`). For
  GitHub it also fills a missing `GITHUB_OWNER`/`GITHUB_REPO` from the origin remote and a
  missing `GITHUB_TOKEN` from `gh auth token`; for Azure DevOps a missing
  `AZURE_DEVOPS_ORG`/`_PROJECT`/`_REPO` from `AZURE_DEVOPS_URL`, then the origin remote. Claude Code reads the lists at startup, so a
  change applies from the *next* session start. Entries you add yourself for other servers
  are left alone.

  Where `.claude/.env` values go:

  | Key | This session's Bash calls | `settings.local.json` `env` (next session on) |
  | --- | --- | --- |
  | Non-secret (`GIT_HOST`, `JIRA_BASE_URL`, …) | yes (`CLAUDE_ENV_FILE`) | yes |
  | Secret (an `op://` reference, or a name matching `SECRET_NAME` in `hooks/sync-env.py`, such as `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*_KEY`, `*_PASS`, `*_PAT`, `*WEBHOOK*`, `OP_SESSION_*`) | yes, resolved | never; an earlier synced copy is removed |
  | `ANTHROPIC_API_KEY` | yes, resolved | yes, file kept owner-only (mode 600) |

  Skills and agents load `.claude/.env` with `eval "$(python3 .claude/tools/env_exports.py)"`,
  which parses the file instead of running it as shell; never `. .claude/.env`. A value with a
  space, such as `op://Dev Tooling/...`, would make bash run the text after the space as a
  command. It prints values of non-secret keys only: a secret the session already holds is
  skipped, and any other secret becomes `export K="$(… env_exports.py --value K)"`, resolved
  when the line is eval'd, so no secret value reaches the transcript. Run on its own,
  `--value` prints a secret, so `settings.json.template` asks before it. MCP servers resolve
  their own secrets through `tools/mcp-run.py`, which also drops secret-named variables and
  values with `user:pass@` URLs from the environment it passes to a server.

  It also handles `ANTHROPIC_API_KEY`: a real key in `.claude/.env` is written to
  `settings.local.json` `env` (and exported to the current session's Bash calls), so Claude
  Code authenticates with it from the next session start and skills/agents calling the
  Anthropic API inherit it. An empty, placeholder or unresolved `op://` value is ignored
  (and removed from `settings.local.json` if it was synced earlier) so a bad key never
  shadows your `claude` login. The hook never sets `apiKeyHelper`, and removes a
  `printenv ANTHROPIC_API_KEY` helper it finds: that helper exits 1 whenever the variable is
  missing from the environment Claude Code starts in (`apiKeyHelper failed: exited 1`), which
  blocks authentication instead of falling back to the login. A helper you set yourself is
  left alone. Claude Code asks once whether to use the synced key; if you answered "No", it
  remembers that per key (`customApiKeyResponses.rejected` in `~/.claude.json`) and uses the
  login, so remove the key's entry there to be asked again.
- `settings.json.template` — generated (copied, not symlinked) into a project's
  `.claude/settings.json` the first time it's linked, the same way as `.mcp.json`
  above. Only generated when no `settings.json` exists yet; once a project has one,
  it's free to diverge (different permissions, extra hooks) and `link-project.sh`
  will never touch it again. Its permissions auto-allow git/`gh` commands that only read or
  fetch, and each read-only `.claude/tools/` script by name (in the forms the skills call
  them: `.claude/tools/x`, `bash …`, `python3 …`, `python3 -I …`); any other script prompts.
  `ask` and `deny` rules sit on top (Claude Code checks deny, then ask, then allow, per
  subcommand):

  | Rule | Covers |
  | --- | --- |
  | ask | scripts that post or change something outside the machine (`*_post_comment.sh`, `jira_create_child.sh`), the `azure-devops` comment tool (`repo_pull_request_thread_write`), `mcp-run.py` (runs any command), `env_exports.py --value` (prints a secret), `workspace_docs.py sync` (`git merge`); reading `.env`, `.env.*` and `settings.local.json` |
  | deny | the `azure-devops` tools that commit files, create branches or change a PR (`repo_file_write`, `repo_create_branch`, `repo_pull_request_write`); `..` in a `.claude/tools/` path; git options that write a file, run a command or read a file outside the repo (`--output`, `diff --no-index`, `blame --contents`, `grep -O`/`--open-files-in-pager`, `fetch --upload-pack`; deny patterns use the shortest prefix git accepts); `gh auth --show-token`; credential files under `~` (`.ssh`, `.aws`, `.config/gh`, `.netrc`, `.git-credentials`, `.npmrc`, `.pypirc`, `.docker/config.json`, `.kube`, `.config/gcloud`, `.azure`, `.gnupg`, `.config/op`, `.claude/.credentials.json`) |

  Since an existing `settings.json` is never regenerated, merge template changes into a
  project's copy by hand. Wires up `sync-env.py` (SessionStart) and
  `biome-pretooluse.py` (PreToolUse on Write/Edit) — the latter no-ops silently on
  projects without a `node_modules/.bin/biome`, so it's safe as a shared default.
  `biome-pretooluse.py` checks prospective content via a throwaway sibling temp
  file (`.pretooluse-tmp-*`) in the same directory as the file being saved —
  add `**/.pretooluse-tmp-*` to the project's `.gitignore` so it doesn't get
  picked up by VCS-aware tooling if a crash ever leaves one behind. It skips files
  that resolve into this repo (an edit through the `.claude/skills` symlink), so no
  temp file lands in the shared tree.
- `env.example` — template for a project's `.claude/.env`. Secret fields use
  `op://` (1Password) references; see the file header for setup. Includes both
  Bitbucket, GitHub and Azure DevOps blocks — `GIT_HOST` (or `tools/detect_git_host.sh`'s
  auto-detection from `git remote get-url origin`) picks which one the
  PR-related skills use and which git MCP server is enabled. Notion needs no entry by default
  (hosted OAuth server); the commented `NOTION_TOKEN` / `NOTION_MCP=off` switch to an API key or turn it off.
- `bin/link-project.sh [--refresh-mcp] [--dry-run] [--existing extend|rewrite|skip|ask] <path>` — wires a project to this
  repo (symlinks, or, for a project's own real `.claude/<dir>`, whatever was chosen at the
  prompt — see [A project that already has its own `.claude/`](#a-project-that-already-has-its-own-claude) — and
  generates `.mcp.json`), appends to the project's `.gitignore`
  whichever of `.claude/.env`, `.claude/settings.local.json` and `.mcp.json` git doesn't
  ignore yet, and records the project in `.linked-projects`. It refuses to replace
  foreign symlinks, and an existing `.mcp.json` that differs from the template unless
  `--refresh-mcp` (then the old copy goes to `.backups/`).
- `bin/sync-projects.sh [--dry-run] [--keep-mcp] [--verify] [--scan DIR]... [PROJECT...]` — runs
  `link-project.sh --refresh-mcp` on every linked project; see
  [Keeping linked projects up to date](#keeping-linked-projects-up-to-date).
- `.linked-projects`, `.link-choices`, `.backups/` — local, gitignored: the project list,
  the answers to the existing-`.claude/` prompt, and the `.mcp.json` copies and
  `.claude/` directories or entries replaced by a refresh or a rewrite.

## Skills

Invoked as `/<skill-name>` (or by the natural-language triggers noted below), unless marked delegates-only.

| Skill | What it does | When it's used |
| --- | --- | --- |
| `answer-pr-comments` | Answers unanswered human reviewer comments on a Bitbucket, GitHub or Azure DevOps PR. Default: composes replies via the `comment-responder` agent, shows them and posts after one confirmation. With `--fix`: verifies each comment against the code, fixes the valid ones, declines the rest with evidence, runs the project's checks, then commits, pushes and posts after one confirmation. | `/answer-pr-comments <pr-number \| azure-devops-pr-url> [<reviewer-name>] [--dry-run] [--fix]` |
| `backend-implementation` | Backend coding standards for layered services: loads the project's own coding-standards docs first (pointed to by its root `CLAUDE.md`), then applies generic rules — repository pattern (models hold business logic, providers only access data), records vs API contracts, upserts and batches, validation, errors, logging, config, security, tests, PR hygiene. Holds no project data. | Automatically when implementing, fixing or reviewing backend code; project rules go in the project's `docs/coding-standards*.md` |
| `backend-review` | Reviews backend code (PR, branch or diff) against the same standards used to write it: the `backend-implementation` rules plus the project's coding-standards and style docs. Checks layering, contracts, upserts, validation, errors, logging, security, tests and naming/style; ranks findings and gives ready-to-apply suggestion blocks. Read-only. The `pr-reviewer` agent applies it to backend files. | When reviewing backend code, alone or inside `/pr-review` |
| `frontend-review` | Reviews front-end / UI code (PR, branch or diff) for any UI stack. First detects the stack from `package.json` and config (React, Next.js, Angular, Vue, Nuxt, Svelte, Solid, web components, React Native or plain HTML/CSS/templates; data layer, styling, i18n, test tools). Then applies UI-wide checks (API data contract and release order, loading/empty/error states, accessibility, i18n, SSR/hydration, state and data, performance, XSS, design system, analytics, tests) plus the detected framework's best practices from `references/` (`react.md`, `angular.md`, `vue.md`, `other-ui.md`). Holds no project data. Read-only. The `pr-reviewer` agent applies it to the `frontend` bucket. | When reviewing UI code, alone or inside `/pr-review` |
| `caveman` | Token-efficient caveman-mode responses (~75% fewer tokens, full technical accuracy). | `/caveman`, or saying "less tokens" / "be brief"; stays active until "stop caveman" / "normal mode" |
| `connect-git` | Verifies the project's git-hosting connection: resolves Bitbucket, GitHub or Azure DevOps, checks the credentials in `.claude/.env`, tests them against the host API, and confirms the matching MCP server (GitHub, Azure DevOps) is in `.mcp.json` and answers a live read-only call; reports Notion status. Read-only. | `/connect-git`; first-time setup, after switching remotes, or when PR skills return 401/403/404 |
| `create-jira-task` | Creates one or more Jira issues (default type Task), optionally as children of a parent issue such as an Epic. A real **write** operation against Jira Cloud. | `/create-jira-task [--parent=KEY] [--project=KEY] [--issuetype=NAME] [--dry-run]` |
| `daily-status` | Prepares your stand-up status from your own activity in the repo: git commits, checkouts and rebases (`tools/daily_activity.py`) plus your Claude Code sessions there, including sessions started in a parent workspace directory that worked in the repo. Groups it per ticket (key, short Jira summary and status, done, next), adds blockers and a 30-second version to read out. Default day is yesterday, or the last active day before it; any past day can be asked for. Read-only; posts nothing. | `/daily-status [yesterday \| today \| -N \| YYYY-MM-DD \| <weekday>] [--repo=<path>]... [--author=<email>] [--no-jira]`; "daily status", "stand-up update", "what did I do yesterday" |
| `demo-prepare` | Prepares a live demo of a finished change (PR, branch or ticket): picks what can be shown live, dry-runs every command, and writes `DEMO.md` (preparation, a `Step | Command | You should see` table, a timed speech with cues, likely questions, fallback) plus `schema.html` pictures in plain HTML and CSS (no SVG or PNG). Plain English. Follows the repo's own demo convention, else writes to `.claude/demos/<slug>/`. Never commits. | `/demo-prepare [<pr-number \| branch \| ticket-key>] [--minutes=<n>] [--out=<dir>]`; "prepare a demo", "demo speech", "schema for the demo" |
| `demo-recap` | Prepares a 2–3 minute demo of what you changed over a period (default the last 7 days) from your git commits and Claude Code sessions (`tools/activity_range.py`), plus any extra source you name. Picks 1–3 changes a listener would notice, reads their diffs for how it worked before and how it works now, and writes `DEMO.md` (a timed speech with cues, an optional dry-run local run) plus `schema.html` before/after slides in plain HTML and CSS. No ticket keys. Writes to `.claude/demos/recap-<from>-<to>/`. Never commits. | `/demo-recap [last week \| since <day> \| <from>..<to>] [--repo=<path>]... [--author=<email>] [--source=<file\|url>]... [--minutes=<n>] [--no-live] [--out=<dir>]`; "weekly demo", "demo of last week", "before/after slides" |
| `design-build` | Builds UI from a `design-spec` directory one block at a time. Detects the stack (as `frontend-review` does), maps the spec's tokens to the project's, reuses its components, and aligns a block that already exists instead of rebuilding it. Plans first and waits for approval. Then for each block it writes the code, renders it through the `playwright` server at every spec viewport, and diffs it against `reference.png` (`tools/design_png.py diff`), fixing mismatches until the diff passes or the rounds run out. New tokens, fonts, dependencies and third-party assets each need a yes. | `/design-build <spec-dir> [--block=<name>]... [--preview=<url>] [--threshold=<percent>] [--max-rounds=<n>]` |
| `design-spec` | Turns a design into per-block specs for `design-build`. A Figma link is fetched through the `figma` server. A live page or local HTML file is rendered by the `playwright` server and read from computed styles (`references/dom-extract.js`). A screenshot is measured with `tools/design_png.py`. Splits the page into blocks (header, sections, footer) or takes only `--block`. Each block gets a structure tree with sizes, layout, type, colours, states and responsive changes, plus a 1x `reference.png`; tokens and assets are shared. Format: `references/spec-format.md`. Writes only under `.claude/design/`. | A Figma URL, design screenshot or site/block to copy; `/design-spec <figma-url \| image \| url \| html-file> [--block=<b>]... [--name=<slug>] [--viewports=<w>,<w>]` |
| `doc-review` | Reviews (or self-checks before a PR) technical documents — architecture/design docs, plans, specs, ADRs, data contracts, runbooks, READMEs: durable docs hold only the target state (plans live elsewhere), flows and data models as diagrams and tables, plain wording without AI-style filler, every claim verified against the owning repo's default branch (no unmerged behaviour, no history or ticket keys), reader lifecycle questions (bootstrap, who may call, UI vs API, secret handoff) answered, design failure modes covered, fan-out to other canonical docs, one home per rule at the right level of detail, docs/comments/tests/config in the change agreeing. Writer self-check ranked by reviewer frequency: `references/self-check.md`. Read-only. Also applied by the `pr-reviewer` agent to the `docs` bucket, and run by `pr-description`, `answer-pr-comments --fix` and `backend-implementation` when a change touches docs. Grows from reviewer comments (generic rules only). | "review this doc/design PR", or alongside `/pr-review` on a docs PR; whenever you write or edit a doc; before opening or updating a PR that changes a doc |
| `feature-doc` | Generates a plain-English feature doc from the current branch's Jira ticket and diff, readable by QA/PMs/tech leads without code knowledge. | `/feature-doc [ticket-key] [output-path]` |
| `get-confluence-page` | Fetches a Confluence page by URL or ID and renders it as Markdown, following embedded links two levels deep. Atlassian MCP first, REST fallback (`tools/atlassian_fetch.py`) if the MCP server is down. | User provides a Confluence URL, or a Jira issue being read links to one |
| `get-jira-task` | Fetches a Jira issue — title, status, description, subtasks, and every linked Confluence page in full (two levels deep, classified by type); delegates to the `jira-context` agent. Atlassian MCP first, automatic REST fallback if the MCP server is down (the output's `Source:` line says which). Also downloads and analyzes the ticket's image attachments (screenshots, mockups, diagrams; `--no-images` / `--max-images=N`). | User references a ticket number, or acceptance-criteria/spec context is needed before starting work; `/get-jira-task <key> [--no-images] [--max-images=N] [-- <repo-path>...]` |
| `get-notion-page` | Fetches a Notion page by URL or ID as Markdown, following linked Notion pages one level deep. Prefers the Notion MCP tools (token-based `notion` server, then the hosted `notion-oauth` server / claude.ai connector — no API key needed, sign in once from `/mcp`) and falls back to a REST script using `NOTION_TOKEN`. Read-only. | User provides a Notion URL, or a ticket/PR links to one; `/get-notion-page --check` verifies the token |
| `implement` | Architect/staff-dev skill: fetches a Jira ticket and linked Confluence docs, reads related repos if provided, and produces a detailed implementation plan in `.claude/plans/` for approval before any code is written. | `/implement <ticket-key> [-- <repo1> [<repo2> ...]]` |
| `pr-description` | Writes or rewrites a PR title and description in short, plain English for non-native speakers: what the PR does and why, not a diff tour. Uses the repo's PR template, diff, commits, the `$JIRA_WORKSPACE` ticket and linked PRs. No Jira link in the body (the key is in the title). Drafts first, posts only with `--post`. | `/pr-description [<pr-number \| branch>] [--post]`; every time a PR is created or its description must change |
| `pr-review` | Reviews a Bitbucket, GitHub or Azure DevOps PR (by number, URL, or branch): batch-fetches every linked Jira ticket / Confluence page, asks about cross-service dependencies, then delegates to the `pr-reviewer` agent for a full structured review. Each finding links to its line in the PR's diff view (`tools/pr_line_links.py`). | `/pr-review <pr-number \| url \| branch>` |
| `project-blueprint` | Turns a ticket or a free-text feature description into a pre-implementation project blueprint — architecture, service ownership, API inventory, proposed directory tree, phased roadmap — grounded in technologies/patterns already used elsewhere in the org. Reuses `jira-context` for ticket fetching and `project-overview`'s scanner for repo/sibling inspection. Planning documents only, no code. | `/project-blueprint <ticket-key \| free-text description> [-- <repo1> [<repo2> ...]]` |
| `project-overview` | Produces an evidence-based technical/architectural overview of a repo or service — purpose, tech stack, architecture, dependency map, ecosystem relationships, risks/gaps — every claim cited to a file, line, or URL. Read-only. | `/project-overview [<path>] [-- <repo1> [<repo2> ...]]` |
| `run-job` | Runs a service job or one-off script on a deployed environment, or locally against a third-party API, with the user: loads the project's job-running doc first (pointed to by its root `CLAUDE.md`), checks the job exists in the scheduler, picks the route (scheduler run or local run with a temporary scoped key), then walks dry run → canary → full run → second dry run, reading each log and the written records before the next step. The user runs every write and enters secrets only at a hidden terminal prompt. | `/run-job <repo> <job-name> [<env>]`; "run this job on UAT", "run it manually", "do a canary" |
| `security-audit` | Read-only security audit in two parts. **Config:** scans a Claude Code config tree (skills/agents/tools/hooks/workflows, `mcp.json`, `settings.json`, their templates, env templates; plus `bin/` and `README.md` in this repo) for hardcoded secrets, project-specific identifiers, values that belong in a project-local `.env`, and overly-broad tool/permission scopes. **Code:** audits an app's source in any language for injection, auth/authorization gaps (incl. IDOR), secrets and sensitive data, SSRF, path traversal, unsafe deserialization, XSS/CSRF/CORS/cookies, weak crypto/TLS, and config, dependency and container risks; every finding traces input → sink → missing guard. Mechanical first pass in `tools/security_audit_scan.py --mode=config\|code`. The `pr-reviewer` agent applies the config checks to the `claude-config` bucket and the code checks to every changed file. | `/security-audit [path] [--config\|--code\|--all] [--diff[=<base>]]`; no flag runs config only in a shared config repo, both parts elsewhere; `--diff` limits it to the branch's changes |
| `security-review` | Replaces Claude Code's built-in `/security-review`: runs `security-audit`, with `--diff` when given no arguments, so a bare `/security-review` still reviews the branch's pending changes. Claude itself can't invoke it (`disable-model-invocation`); for a security request it calls `security-audit` directly. | `/security-review [path] [--config\|--code\|--all] [--diff[=<base>]]` |
| `self-review` | Double-checks one change (branch, commit or working tree) for over-engineering and duplication in design, code and tests. Loads the project's rules first (root `CLAUDE.md`, reviewer and pre-push docs, review lessons, the plan's acceptance criteria), compares the change with the simplest design that meets them, scans the whole repo for code, types, constants and text it could reuse or copied, inventories where each behaviour is implemented and proven, and removes repeated validation layers, single-use files, types and helpers, tests repeated across levels or aimed at a fake, a library or a generated artifact, tests that cannot fail and duplicated fixtures. Simplifies code first and shows the unchanged tests still pass, then trims tests, checks each kept rule by breaking it once, and measures flakiness against the base exported with `git archive` (never a stash). Uses the `test-design` and `backend-implementation` §11 rules. Edits the working tree only. | `/self-review [<base-ref> \| <commit>]`, or "double check", "simplify", "remove duplicates" before pushing |
| `sonar-triage` | Fetches and triages SonarQube Cloud issues (PR, branch, or main) and proposes a fix for each, checking a project-local `.claude/sonar-known-issues.md` (if present) for confirmed false positives. Analysis only. | `/sonar-triage [pr <number> \| branch <name> \| main]` |
| `split-pr` | Analyzes a large/complex PR or branch and proposes how to split it into smaller, dependency-ordered (stacked) PRs. Analysis only unless `--apply` is passed. | `/split-pr [<pr-identifier> \| <branch>] [--base=<branch>] [--apply] [--interactive]` |
| `test-design` | Rules for writing and reviewing tests in any language or stack (backend, frontend, infrastructure, scripts): inventory existing tests first, one unique behaviour per test, lowest level that can prove it, no tests of library/tool guarantees, no duplicates or implied tests, parameterise variants, self-check table. Used by `backend-implementation`, `backend-review` and the `pr-reviewer` agent. | Whenever tests are added, changed, planned or reviewed |
| `workspace-docs` | Knowledge library for a workspace root holding a family of independent repos: a lean root `CLAUDE.md` index plus `docs/` chunks ≤4 KB with frontmatter (`summary`, `keywords`, `verified`) in a fixed layout (`services/`, `lookups/`, `connections/`, `recipes/`, `links.md`, commands, conventions, checklist, security, drift). Commands: `init`, `refresh`, `align`, `check`, `status`, `find`, `add-doc` (Confluence/Notion/Jira/web/file → chunk), `add-link` (`--pin` keeps it in `CLAUDE.md`), `add-repo`, `remove-repo`, `note`. Mechanical parts in `tools/workspace_docs.py` (`inventory`, `check`, `status [--fetch]`, `sync`, `changes`, `baseline`, `find`, `audit`, `scaffold`, `link`). Writes `CLAUDE.md` and `docs/` (backed up first) and never records secret values; `refresh` only fetches the repos unless `--pull` fast-forwards their default branches, and edits memory files only after you approve. | `/workspace-docs <command> [args] [--root=<workspace-root>]`; run from the workspace root after `bin/link-project.sh <workspace-root>` |

## Agents

Subagents invoked by the skills above — not called directly by name.

| Agent | What it does | Invoked by |
| --- | --- | --- |
| `comment-responder` | Fetches unanswered PR comments (all pages), reads the current state of each referenced file and any `.claude/reviews/` analysis, composes accurate Fixed/Deferred/Answered replies, and posts them. Also runs as `collect` (fetch only) and `post` (post pre-composed replies, skipping answered ones) for the `--fix` flow. | `answer-pr-comments` |
| `feature-doc-writer` | Writes the feature document from the ticket, Confluence and diff material in its prompt and returns the markdown. Read is its only tool. | `feature-doc` |
| `feature-planner` | Architect-level planner: takes a fully-populated Jira context block plus codebase access and produces a concrete implementation plan saved to `.claude/plans/`. Writes no production code. | `implement` |
| `jira-context` | Fetches a Jira ticket and exhaustively pulls every referenced Confluence page (two levels deep), full bodies, classified by type; also reads `CLAUDE.md` from the primary and any related repos. Uses the Atlassian MCP tools, falling back to `tools/atlassian_fetch.py` (REST) when they're unavailable. Cannot write or edit files. | `get-jira-task`, `implement`, `pr-review` |
| `pr-reviewer` | Reviews a Bitbucket, GitHub or Azure DevOps PR end-to-end (Azure: from the clone and the comments the skill fetched): fetches diff/commits/comments/Jira context, classifies changed files, reads the working tree, and returns one structured review. Read-only. | `pr-review` |

## What's NOT here (stays per-project, never write project values back into this repo)

`.claude/.env`, `.claude/settings.local.json`, `.claude/plans/`, `.claude/design/`,
`.claude/reviews/`, `.claude/worktrees/`, and any other session/runtime state
are never templated here at all. `.claude/settings.json` and `.mcp.json` are
copied *from* this repo once (see `settings.json.template` / `mcp.json.template`
above). `settings.json` then belongs to the project — nothing overwrites it, so
its customizations never need to (and never should) get written back here.
`.mcp.json` is only replaced on request (`--refresh-mcp`, or `bin/sync-projects.sh`),
with a backup; keep per-project values in `.claude/.env`, not in `.mcp.json`. Project `.gitignore` must exclude
`.claude/.env`, `.claude/settings.local.json` and `.mcp.json` (`link-project.sh` adds
any that are missing) and, if the project uses Biome, `**/.pretooluse-tmp-*` — see the
`biome-pretooluse.py` note above.
