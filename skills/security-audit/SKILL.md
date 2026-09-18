---
name: security-audit
description: Scans a Claude Code config tree — skills/, agents/, tools/, hooks/, workflows/, mcp.json, settings.json, env templates — for hardcoded secrets, project-specific identifiers baked into shared files, values that belong in a project-local .env instead, writes that could leak project data back into a shared source-of-truth, and permission/tool scopes broader than what the skill or agent actually does. Read-only: produces a plain-text report, never modifies files. Works against any project's `.claude/` folder or directly against a shared skills/agents source-of-truth repo. Usage: /security-audit [path]
---

# security-audit — portability & secret-leak audit for shared Claude config

Audits skill/agent/tool/hook/workflow files that are meant to be **portable across
projects** (or across an entire shared source-of-truth repo) for anything that
quietly ties them to one specific project, org, or machine — or leaks a real
credential into files that get committed and shared.

This skill never edits, moves, or deletes anything. It only reads and reports.
If the user wants a finding fixed, that is a separate, explicit follow-up
action — not something this skill does automatically, because several of the
fixes (which vault a rotated secret belongs in, whether a hostname is actually
an intentional org-wide default) need a human call.

## Step 0 — Resolve the scan root and the scanner script

```bash
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

SCANNER="$PROJECT_ROOT/.claude/tools/security_audit_scan.py"
[ -f "$SCANNER" ] || SCANNER="$PROJECT_ROOT/tools/security_audit_scan.py"
[ -f "$SCANNER" ] || { echo "security_audit_scan.py not found under .claude/tools or tools/" >&2; }
```

Then resolve what to scan, in order:

1. **`args` gives a path** — use it as `ROOT`, resolved to an absolute path.
2. **No `args`, and `$PROJECT_ROOT/.claude` exists** — this is a linked project. `ROOT="$PROJECT_ROOT"` (the scanner itself walks both `$ROOT` and `$ROOT/.claude`, since `.mcp.json`/`CLAUDE.md` sit at the project root while `skills/`, `agents/`, `settings.json`, `.env.example` sit under `.claude/`).
3. **No `args`, no `.claude/`, but `$PROJECT_ROOT` has top-level `skills/` and `agents/` directories** — this is a shared source-of-truth repo being audited directly (e.g. this very repo). `ROOT="$PROJECT_ROOT"`.
4. **Neither** — tell the user you couldn't find a `.claude/` folder or a shared skills/agents layout at `$PROJECT_ROOT`, and ask them to pass a path explicitly.

State the resolved `ROOT` at the top of your eventual report so a wrong guess is obvious immediately.

## Step 1 — Run the mechanical scanner

```bash
python3 "$SCANNER" "$ROOT"
```

This returns one JSON object: `files_scanned`, `secret_findings`, `write_findings`,
`scope_findings`, `identifier_candidates` (see the script's header docstring for
the exact shape). It is a **first pass, not a verdict** — it does high-confidence
pattern matching and structural extraction, but it cannot tell an intentional
org-wide default from an accidental leak, or a safe project-local write path from
an unsafe one. That judgment is Steps 2–3, and it requires reading the files, not
just the JSON.

**Read every file listed in `files_scanned` in full** (they are short — a handful
of KB each). The JSON tells you where to look first; it does not replace reading
the surrounding context of every hit.

## Step 2 — Apply judgment per category

### 1. Hardcoded credentials or secrets

Start from `secret_findings`. Each entry already survived placeholder filtering
(it skips `${VAR}`, `$VAR`, `<placeholder>`, `op://...` references, and obvious
dummy strings like `xxxxxxxx` or `replace-with-...`), so treat every entry as a
real candidate, not noise.

- Never reproduce the full secret value in your report — reuse the script's
  `redacted` form (or redact it yourself the same way: first 4 / last 4 chars).
- Also skim every file yourself once more for shapes the regex won't catch:
  a secret split across a multi-line string, a base64 blob with no recognizable
  prefix, a value pasted into a comment or example output block that looks real
  rather than illustrative.
- A private-key block, a live API key, or credentials embedded in a URL are
  **critical** — they mean the secret is sitting in a file that gets committed
  and shared across every project/person that links this config.

### 2. Project-specific identifiers baked into shared files

Start from `identifier_candidates`, but the real signal is in full-file reading:
narrative prose (a "known false positive" writeup naming one specific repo, a
runbook note about one team's pipeline) won't show up as a URL or email match.

Judge each candidate against three buckets:

- **Fine — already externalized.** Any value built from `${VAR}`, `$VAR`, or an
  angle-bracket placeholder (`<ticket_key>`, `$JIRA_WORKSPACE-123`) is doing
  exactly what a shared file should do. Not a finding.
- **Fine — well-known public infrastructure.** Generic SaaS/public hosts the
  skill legitimately talks to as a class of service, not a specific tenant:
  `github.com`, `bitbucket.org`, `sonarcloud.io`, `sonarqube.us`, `slack.com`
  and `hooks.slack.com`, `atlassian.com`, `1password.com`, `npmjs.com`,
  `pypi.org`, `docker.com`, `anthropic.com`/`claude.ai`, `googleapis.com`,
  `localhost`/`127.0.0.1`. Not a finding.
- **A finding.** A literal that only makes sense for one project, one org, or
  one machine: a specific `org.atlassian.net` tenant hardcoded instead of
  `$JIRA_BASE_URL`, a specific repo/branch/PR named in prose instead of spoken
  of generically, a real ticket key used as a *default* rather than an
  *example*, an absolute local filesystem path (`/Users/name/...`,
  `/home/name/...`), a client or company name, an internal-only hostname.

  Distinguish severity within this bucket: a value the file's own comments
  already document as an intentional, shared org-wide default (check the
  surrounding prose and any README/header comment first) is a lower-severity
  **portability note** — it still blocks reuse outside that org, so it's worth
  reporting, but it's a design choice, not an accident. A value that has no
  such documentation, or that clearly leaked in from one project's specifics
  into a file that's supposed to generalize, is a real **non-portable** finding.

### 3. Values that should come from a project-local `.claude/.env`

Check every `env.example`/`.env.example` and `mcp.json`/`mcp.json.template` field:
does it hold a literal value, or `${VAR}` / `op://vault/item/field` / a documented
placeholder? Then check every `SKILL.md`, agent `.md`, and script under
`tools/`/`hooks/`/`workflows/` for the same question — is there a credential-,
hostname-, or org-shaped literal sitting directly in the file instead of being
read from `.env` via `$VAR`/`${VAR}`? This overlaps with categories 1 and 2 by
value-shape, but the fix is specific: it belongs in the project's `.env`, not
scattered as a literal, so it can vary per project without editing the shared file.

### 4. Writes that could land project-specific data in the shared tree

Start from `write_findings`. For each, resolve where the write actually targets:

- **Fine.** The target is project-local runtime state: under `.claude/reviews/`,
  `.claude/plans/`, `.claude/worktrees/`, `/tmp/`, or anything built from
  `$CLAUDE_PROJECT_DIR`/`$PROJECT_ROOT` outside the shared directories. This is
  the pattern this repo's own skills already use (e.g. `pr-review` writing to
  `.claude/reviews/pr-<id>.md`) — not a finding.
- **A finding.** The target is inside `skills/`, `agents/`, `tools/`, `hooks/`,
  or `workflows/` themselves — i.e. the same tree that's symlinked into every
  project — or is a hardcoded absolute path. Writing there means one project's
  run pollutes the shared source every other project reads from.

### 5. Overly broad permissions or scope

Start from `scope_findings`: agent frontmatter `tools:` lists, MCP server
`command`/`args`/mounted env keys, `settings.json` `hooks`/`permissions` blocks.
Read the skill/agent's own description and procedure, then ask: does the
declared access match what it actually does?

Flags worth raising:
- An agent whose job is a narrow, read-only fetch (e.g. "reads Jira/Confluence
  via curl") declaring unrestricted `Bash` or `tools: '*'` instead of the
  specific tools it calls.
- An MCP server command with container flags wider than needed:
  `--privileged`, `--network=host`, a bind mount like `-v /:...` or `-v $HOME:...`
  when the server only needs one narrow path.
- A `permissions.allow` entry like `Bash(*)` where the skill/agent only ever
  runs a handful of specific commands.
- A hook matcher/trigger scoped to `*` when it only needs to react to one tool
  or one file pattern.

Compare against a skill in this same tree that gets it right as your baseline
(e.g. `pr-reviewer`'s agent frontmatter scopes `tools` to exactly `Bash, Read,
Grep, Glob` for a read-only reviewer) — that's the bar for "justified by what it
actually does."

## Step 3 — Produce the report

Plain markdown, read-only, no file changes. Structure:

```
# Security audit — <resolved ROOT>

Scanned <N> files under skills/ agents/ tools/ hooks/ workflows/ (+ mcp.json,
settings.json, env template where present).

## Summary

| # | Category | Findings |
|---|----------|----------|
| 1 | Hardcoded credentials/secrets | <n> |
| 2 | Project-specific identifiers | <n> |
| 3 | Belongs in .claude/.env | <n> |
| 4 | Write-back risk | <n> |
| 5 | Overly broad permissions/scope | <n> |

## 1. Hardcoded credentials or secrets

🔴 `path/to/file:LINE`
**Found:** <what — pattern name / redacted shape, never the real value>
**Why it's a problem:** <secret leak — this file is committed/shared, so the credential is exposed to everyone who links this config, not just this project>
**Fix:** <e.g. "move to .claude/.env as SOME_TOKEN (op://vault/item/field like the existing BITBUCKET_API_TOKEN), reference it here as ${SOME_TOKEN}">

---

(one block per finding; "No findings." if none)

## 2. Project-specific identifiers baked into shared files

🟠 `path:LINE` (non-portable) — or 🟡 (portability note, documented org default)
**Found:** ...
**Why it's a problem:** non-portable, not a secret — <who this breaks: reuse outside this project/org>
**Fix:** <e.g. "replace with ${JIRA_BASE_URL} / a placeholder, and document the expected format in SKILL.md">

## 3. Values that should come from .claude/.env

🟡 `path:LINE`
**Found / Why / Fix** — fix is always some form of "move to .claude/.env, reference via $VAR / ${VAR}".

## 4. Write-back risk

🟠 `path:LINE`
**Found:** <the write call and its target>
**Why it's a problem:** <writes project-specific data into the shared source tree that every linked project reads from>
**Fix:** <redirect to a project-local path, e.g. .claude/reviews/, $CLAUDE_PROJECT_DIR-relative, or /tmp>

## 5. Overly broad permissions or scope

🟡 `path` (section, not always a line)
**Found:** <declared tools/args/permissions>
**Why it's a problem:** <wider than the skill/agent's stated job — bigger blast radius than justified>
**Fix:** <narrow to the specific tools/commands/mount actually used>
```

Rules:
- Keep every category header even when empty — write "No findings." underneath.
Don't silently drop a clean category; the user should see it was checked.
- Order findings within a category most-severe/most-confident first.
- Never paste a full secret value anywhere in the report, even redacted forms
  should stay redacted (reuse the script's `redacted` field or apply the same
  first-4/last-4 masking yourself).
- If `args` or context makes it ambiguous whether a flagged org-wide default
  (category 2) is intentional, say so explicitly rather than guessing — e.g.
  "flagged as a portability note; if every project sharing this repo is
  expected to be under the same Bitbucket workspace, this may be an
  intentional default — confirm before changing."

## What NOT to do

- **Never edit, move, or delete a file.** This skill only reads and reports.
  If asked to apply a fix, treat that as a distinct follow-up action outside
  this skill's scope, not something to do automatically after the report.
- **Never reproduce a full secret value** in the report, in a commit message,
  or in any tool call argument — always redact.
- **Never scan or report on `.env` or `settings.local.json` contents.** Those
  are project-local by design and expected to hold real resolved values; the
  scanner already excludes them. If one is missing entirely, that's normal,
  not a finding.
- **Never flag a value that's already parameterized** (`${VAR}`, `$VAR`,
  `<placeholder>`, `op://...`) just because it *looks* like it could hold a
  real secret shape — that's the correct pattern, not a leak.
- **Never treat a project-local runtime write** (`.claude/reviews/`,
  `.claude/plans/`, `.claude/worktrees/`, `/tmp/`) as a category-4 finding —
  only writes into the shared `skills/agents/tools/hooks/workflows` tree itself
  count.
