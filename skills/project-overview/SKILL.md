---
name: project-overview
description: Produce an evidence-based technical and architectural overview of a software repository or service — purpose, technology profile, architecture, dependency map, ecosystem relationships, and risks/gaps — every claim grounded in a cited file, line, or URL. Read-only, analysis-only. Usage: /project-overview [<path>] [-- <repo1> [<repo2> ...]]
---

# project-overview — evidence-based repository & service analysis

Produces a grounded technical overview of a repository or service: what it is,
what it's built with, how it's put together, what it depends on, how it fits
into the surrounding ecosystem, and where the gaps are. Every claim traces to
a concrete file, line, or URL — inference is allowed but must be labelled as
inference, never presented as fact.

**This skill is analysis-only.** It reads and reports. It never edits,
creates, or deletes anything in the analyzed repository — the only write is
its own report file (Step 11).

## Use When

- The user asks for an overview, architecture summary, onboarding doc, or
  "what does this do" for a repo, service, or codebase.
- Before a large cross-cutting task (big refactor, security review, migration,
  dependency upgrade) where a grounded map of the codebase would help scope it.
- The user asks what a service depends on, what depends on it, or how it fits
  into a larger system/monorepo/microservice ecosystem.

## Do Not Use When

- The user wants a review of a specific diff/PR — use `pr-review` or the
  `code-review` skill instead.
- The user wants this *shared Claude config repo* (`skills/`, `agents/`,
  `tools/`) audited for leaked secrets or portability — use `security-audit`.
  That skill scans this repo's own tooling; this skill scans an arbitrary
  target project.
- The user wants a plain-English doc for one ticket/branch's changes — use
  `feature-doc`.
- The user wants SonarQube issues triaged — use `sonar-triage`.

## Input

```
[<path>] [-- <repo1> [<repo2> ...]]
```

- `<path>` — root of the repository/service to analyze. Defaults to the
  current project root (`$CLAUDE_PROJECT_DIR`, else `git rev-parse
  --show-toplevel`, else cwd).
- `-- <repo1> ...` — optional local paths to related repos/services (a
  sibling in a workspace, a shared library, an infra repo) to cross-reference
  in Step 6. Omit if none are known — Step 6 still searches nearby directories
  on its own.

## Step 0 — Resolve root, scope, and the scanner script's location

Resolve `ROOT` per Input. Confirm it exists and is readable; if empty or
inaccessible, tell the user and stop.

Resolve the scanner script's own location — this is **independent of
`ROOT`**: the script lives wherever the *current* session's `.claude/tools/`
is linked from, which may differ from `ROOT` (e.g. `ROOT` can be an unrelated
sibling repo passed as `<path>`, while the session's own project is where
this skill's `tools/` actually lives):

```bash
SCANNER="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}/.claude/tools/project_overview_scan.py"
[ -f "$SCANNER" ] || SCANNER="${CLAUDE_PROJECT_DIR:-$(pwd)}/tools/project_overview_scan.py"
[ -f "$SCANNER" ] || SCANNER=""
```

If `$SCANNER` is empty, Step 1 falls back to manual Glob/Grep — see below.

State the resolved `ROOT` and any `related_repos` at the top of the eventual
report, so a wrong guess is obvious immediately.

## Step 1 — Inventory pass (mechanical evidence gathering)

Run the scanner **once** instead of issuing many separate Glob/Grep calls —
it does the entire mechanical classification pass (metadata files, manifests
parsed per ecosystem, entry-point candidates, CI/CD, infra/deploy files,
config files with declared *key names only*, source layout, test
directories, workspace/monorepo signals, git remotes/branches, and — only if
installed locally, best-effort — a language/LOC breakdown and a
cross-ecosystem dependency+license summary) in one pass and hands back
structured JSON:

```bash
[ -n "$SCANNER" ] && python3 "$SCANNER" "$ROOT" \
  ${related_repos:+--related="$related_repos"} \
  ${check_siblings:+--siblings}
```

Pass `--related=<repo1>,<repo2>` with the `related_repos` from Input, if any,
so Step 6 gets each one's existence/remote checked for free. Pass
`--siblings` only when Step 6's "only when relevant" judgment call says
nearby-repo evidence is worth gathering for *this* repo (e.g. it looks like
one service in a multi-repo system) — it's off by default; scanning the
parent directory isn't relevant for most repos.

Read the script's own header docstring
(`tools/project_overview_scan.py`) for the exact JSON schema. **Steps 2–7
below consume this JSON directly — do not re-Glob/re-Grep for anything the
scanner's output already covers.** Read a file's *content* only when a step
needs more than the scanner extracted (e.g. actual framework usage inside a
source file, actual HTTP route definitions, a `build.gradle` dependency the
parser doesn't cover — `manifests[].parsed` is `null` wherever the scanner
recognized a file but has no parser for its format).

**If `$SCANNER` was empty, or the script exits non-zero,** fall back to
Glob/Grep directly for the same categories, without assuming any are present:

- **Metadata:** `README*`, `CONTRIBUTING*`, `CHANGELOG*`, `LICENSE`,
  `CODEOWNERS`, `.editorconfig`
- **Manifests/lockfiles:** `package.json`+lockfile, `pyproject.toml` /
  `requirements*.txt` / `poetry.lock`, `go.mod`/`go.sum`, `Cargo.toml`/
  `Cargo.lock`, `pom.xml`/`build.gradle*`, `Gemfile`/`Gemfile.lock`,
  `composer.json`, `*.csproj`/`*.sln`
- **Entry points:** manifest `main`/`bin`/`scripts` fields, `Dockerfile`
  `ENTRYPOINT`/`CMD`, `Procfile`, framework-conventional entry files
  (`main.*`, `index.*`, `app.*`, `server.*`, `cmd/*/main.go`)
- **CI/CD:** `.github/workflows/*`, `.gitlab-ci.yml`, `bitbucket-pipelines.yml`,
  `Jenkinsfile`, `azure-pipelines.yml`, `.circleci/config.yml`
- **Infra/deploy:** `Dockerfile*`, `docker-compose*.yml`, Kubernetes manifests
  (`k8s/`, `deploy/`, Helm charts), Terraform (`*.tf`), CDK/Pulumi/Serverless
  configs, `Procfile`, systemd units
- **Config:** `.env.example`/`.env.template`, `config/*`,
  `application.yml`/`.properties`, `appsettings*.json` — note which keys they
  *declare*; never read the real `.env`, `.env.local`, or any
  `settings.local.json` (project-local by design — see Step 8)
- **Source layout:** top 2–3 directory levels, module/package boundaries
- **Tests:** test directories and the frameworks referenced by manifests/CI

Either way: read manifests and entry-point files in full when the scanner's
`parsed` field is `null` for them. Skim the rest of the source tree for
structure rather than reading every file — depth comes from Steps 2–7 reading
the *specific* files each section needs, not from reading everything up
front.

## Step 2 — Project purpose (report section 1)

From README/docs/manifest `description` fields/CLI `--help` output and how
entry points wire together, determine:

- **Problem solved** — paraphrase or quote source text; never fabricate a
  motivation that isn't written down anywhere.
- **Primary output** — API / application / library / worker / CLI / data
  pipeline / infrastructure — inferred from entry points, manifest
  `bin`/`main` fields, framework markers, and the `Dockerfile`'s role.
- **Main users/consumers** — only when evidence exists (README "who this is
  for," API consumer lists, calling-service names in docs). Otherwise state
  "Not documented — no evidence found," don't guess.

## Step 3 — Technology profile (report section 2)

Start from Step 1's `manifests[].ecosystem`/`.parsed` and `loc_breakdown`
(populated only if `tokei`/`scc`/`cloc` happened to be installed) — this
gives languages, package managers, and framework-hinting dependency names
directly, without re-reading each manifest. Read a manifest's raw content
only when its `parsed` field is `null`.

From manifests, lockfiles, CI, and infra files, tabulate: languages,
frameworks, runtime + version constraints, package manager, build tool,
databases/caches/queues referenced in dependencies, cloud/infra tooling, test
framework, deployment tooling.

Mark every row **Confirmed** (present literally in a manifest/lockfile/config)
or **Inferred** (deduced from code patterns/imports with no manifest entry) —
never blur the two into one unlabelled claim.

## Step 4 — Architecture and operation (report section 3)

- **Entry points and execution flow** — trace from the process entry
  (main/index/cmd) through top-level wiring (router setup, worker loop, CLI
  dispatch).
- **Modules/layers** — one line per major module/directory naming its actual
  responsibility, grounded in real directory/module names, not a generic
  layered-architecture guess.
- **Data flow and externally exposed interfaces** — HTTP routes, RPC/gRPC
  services, message topics/queues produced or consumed, CLI commands,
  exported library API — cite the file defining each.
- **Local dev/build/test/deploy paths** — pull the actual commands from
  `package.json` scripts / `Makefile` / CI config / README. Never invent
  generic commands (`npm test` as a guess) when the project defines its own —
  same rule the `implement` skill in this repo already follows for QA
  commands.

## Step 5 — Dependency map (report section 4)

Start from Step 1's `manifests[].parsed.dependencies`/`.require`/`.gems`/etc.
for external libraries, and `dependency_summary.components` (populated only
if `syft` happened to be installed) for a cross-ecosystem view that includes
license data. The scanner lists names and versions — it does not classify
*runtime role* (which of these is a database vs. a cache vs. an auth
provider); that classification is still your judgment call, cross-referenced
against `config_files[].declared_keys` and `infra_deploy_files` content.

- **Internal** — modules/packages and their import relationships (workspace
  config for a monorepo; top-level module graph for a single package).
- **External libraries** — name + declared version range, from the manifest.
- **Runtime dependencies** — databases, queues, caches, object storage, auth
  providers, third-party APIs, observability/logging/metrics backends —
  found via config keys, client-library imports, `docker-compose` service
  names, or infra manifests. Every entry needs a file citation; no entry
  without one.

Render as a compact table (`Dependency | Type | Evidence (path[:line])`); add
a short text/mermaid diagram only if it adds clarity beyond the table.

## Step 6 — Service and ecosystem relationships (report section 5)

Step 1's `git.remotes`, `related_repos` (populated from `--related`), and
`sibling_repos` (populated only if `--siblings` was passed) fields give this
section's local-repository evidence directly — no separate `git remote -v`
calls needed. `workspace_signals` gives direct evidence for ecosystem type
(monorepo/workspace vs. standalone).

- **Ecosystem type** — monorepo, microservice, shared platform, larger
  delivery chain, or standalone — state the evidence (workspace manifest,
  multiple independently-versioned packages, a platform-wide CI template).
- **Upstream callers / downstream services** — only from evidence: OpenAPI/
  proto/GraphQL contracts naming a consumer, `docker-compose` service links,
  Kubernetes `Service`/`Ingress` references to other service names, README/ADR
  mentions of calling services.
- **Related local repositories** — `related_repos`/`sibling_repos` from
  Step 1 already cover this (existence, git-repo check, remote URLs); only
  fall back to a manual look one directory level up/sideways from `ROOT` if
  `$SCANNER` was unavailable in Step 1. Don't crawl the whole filesystem.
- **Related service definitions, contracts, and deployment manifests** —
  service-definition files (`docker-compose` service blocks, Kubernetes
  manifests, Helm charts), API contracts (OpenAPI/proto/GraphQL schemas), and
  environment configuration (`.env.example` keys, config files) that name or
  imply another service — cite the file for each; this overlaps with Step 1's
  inventory and Step 5's dependency evidence, but surface it here explicitly
  as its own linked artifact, not just as input to another claim.
- **Related docs/contracts** — links to Confluence/Jira/wiki/API-contract
  repos found in README/docs/ADRs. If `.claude/.env` exists with Jira/
  Confluence credentials, you may use the `get-confluence-page` or
  `get-jira-task` skill to fetch a linked page for corroborating context —
  optional enrichment only, never a requirement, and never a blocker if
  credentials are absent.
- Label every relationship **Confirmed** (concrete reference found),
  **Likely** (strong circumstantial evidence — name it), or **Unverified**
  (mentioned but unconfirmed). Never state an integration exists without one
  of these three labels. Never invent one that isn't backed by at least
  circumstantial evidence.

## Step 7 — Risks and gaps (report section 6)

Call out, with citations: missing README/docs, unclear ownership (no
`CODEOWNERS`, no maintainer contact), dependencies used in code but absent
from the manifest (or declared but unused), dead/unused config, config keys
with no corresponding code reference, architectural ambiguities (e.g. two
competing entry points), and any assumption made elsewhere in the report that
still needs human confirmation.

## Step 8 — Secrets discipline (applies throughout every step)

Never quote a credential, token, private key, or connection string with
embedded credentials — not in the report, not in a code block, not even
truncated-but-recognizable. If one is found while reading a file: report only
its location, kind, and a redacted form (first 4 / last 4 characters — the
same convention the `security-audit` skill in this repo uses), never the full
value. Never read the real `.env`, `.env.local`, or `settings.local.json` of
the analyzed repo — only `.env.example`/`.env.template` (key names, not
values) are fair game for Step 3/5 evidence.

## Step 9 — Scaling to repo size (fan-out trades tokens for latency, not the reverse)

For a small-to-medium repo, Step 1's single scanner call plus Steps 2–7's
reasoning is enough — run them directly. For a large monorepo or a repo with
many independent services/packages, fan out one `Agent` call per top-level
module/service/package to gather that unit's Steps 3–6 evidence in parallel,
then synthesize into the single report below — this mirrors the per-group
`Workflow` fan-out already used by this repo's `split-pr` skill.

Be clear about the tradeoff before reaching for this: fan-out reduces
**wall-clock time**, it does not reduce **total tokens** — each fan-out agent
adds its own reasoning cost on top of Step 1's evidence. Use it when latency
matters more than token spend (a repo large enough that serial Steps 2–7
would be slow), not as a token-saving measure.

When fan-out does happen, don't have each unit's agent re-run the scanner
against the whole repo from scratch: either pass it the relevant slice of the
already-gathered root-level scan (git info, workspace signals, root docs), or
re-invoke the scanner scoped to just that unit's subdirectory as its own
`ROOT` (`python3 "$SCANNER" "$ROOT/packages/<unit>"`) so each fan-out agent
still gets one structured JSON call instead of its own round of Glob/Grep.

Cap fan-out at a sensible number of units (merge the smallest into neighbors
past ~10) and record in the report's "Confidence and open questions" section
how many units were sampled vs. merged, so scale-driven omissions are visible
rather than silent.

## Step 10 — Handling incomplete or sparse repos

If a section has no evidence (no manifest found, no CI config, no docs), say
so explicitly inside that section — e.g. "No manifest found; language
inferred from file extensions only" — rather than omitting the section or
guessing to fill it. A near-empty repo (bare scaffold, prototype) still gets
the full template, with most sections stating "insufficient evidence" plus
whatever was actually found. A thin repo should never produce a thin
*investigation* — exhaust Step 1's inventory list before concluding evidence
is absent.

## Step 11 — Write and present the report

Write the full report (template below) to
`.claude/reviews/project-overview/<repo-slug>-<YYYY-MM-DD>.md`, where
`repo-slug` is `ROOT`'s directory name, lowercased, non-alphanumeric
characters replaced with `-`, and the date comes from `date +%F` (never
guessed). `mkdir -p` the directory first.

Present the **executive summary** (from the template) plus the top 2–3 risks
directly in chat, then point at the file path for full detail — do not paste
the entire report into chat, matching this repo's `split-pr`/`pr-review`
convention.

## Output template

```markdown
# Project overview: <repo name> (<ROOT>)

_Generated <YYYY-MM-DD> · related repos: <list, or "none provided">_

## Executive summary
2-4 sentences: what this is, what it's for, its primary output type, and the
single biggest risk or gap.

## 1. Project purpose
- **Problem solved:** ...
- **Primary output:** API | application | library | worker | CLI | data pipeline | infrastructure — <evidence>
- **Main users/consumers:** ... (or "Not documented — no evidence found.")

## 2. Technology profile
| Category | Value | Version | Confirmed/Inferred | Evidence |
|---|---|---|---|---|
| Language | ... | ... | Confirmed | `path` |

## 3. Architecture and operation
### Entry points and execution flow
...
### Modules and layers
| Module/dir | Responsibility | Evidence |
|---|---|---|
### Data flow / externally exposed interfaces
...
### Local dev / build / test / deploy
| Action | Command | Source |
|---|---|---|

## 4. Dependency map
### Internal
...
### External libraries
| Library | Version range | Evidence |
|---|---|---|
### Runtime dependencies
| Dependency | Type | Evidence |
|---|---|---|

## 5. Service and ecosystem relationships
- **Ecosystem type:** monorepo | microservice | shared platform | larger delivery chain | standalone — <evidence>
- **Upstream callers:** ... (Confirmed/Likely/Unverified)
- **Downstream services:** ... (Confirmed/Likely/Unverified)
- **Related local repositories:** ...
- **Related service definitions / API contracts / deployment manifests / environment configuration:** ... (file citations)
- **Related docs/contracts:** ...

## 6. Risks and gaps
- ...

## Confidence and open questions
- **High confidence:** ...
- **Low confidence / inferred:** ...
- **Open questions for a human:** ...
- **Sections with insufficient evidence:** ...
- **Fan-out coverage (if Step 9 ran):** <N> units sampled, <M> merged — <why>
```

## Constraints / What NOT to do

- **Read-only.** Never edit, create, or delete anything inside the analyzed
  repository. The only write this skill makes is its own report file
  (Step 11).
- **No fabricated integrations.** Never state a dependency, relationship, or
  integration exists without a citation; use the Confirmed/Likely/Unverified
  scale from Step 6 rather than guessing.
- **No secret exposure.** Never print a full secret value, even a
  redacted-looking one — always mask per Step 8.
- **No reading project-local runtime secrets.** Never open the target repo's
  real `.env`, `.env.local`, or `settings.local.json` — only `.example`/
  `.template` variants, for key names only.
- **No git or file mutations** in the analyzed repo — no `git commit`,
  `checkout`, `add`, or config edits, ever, regardless of what's found.
- **No silent scope-narrowing.** If Step 9's fan-out merges or drops units for
  scale, say so in "Confidence and open questions" — never let a partial scan
  read as a complete one.
- **No filename-only reasoning when content is available.** Read entry points
  and manifests directly rather than inferring architecture from directory
  names alone.
