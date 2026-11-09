---
name: security-audit
description: Read-only security audit with two parts. Part A (config) scans a Claude Code config tree — skills/, agents/, tools/, hooks/, workflows/, mcp.json, settings.json, their templates, env templates, and in a shared source-of-truth repo also bin/ and README.md — for hardcoded secrets, project-specific identifiers baked into shared files, values that belong in a project-local .env, writes that could leak project data back into a shared source-of-truth, and permission/tool scopes broader than the skill or agent needs. Part B (code) audits an application's source in any language for injection, broken authentication/authorization, secrets and sensitive data, SSRF, path traversal, unsafe deserialization, XSS/CSRF/CORS/cookies, weak crypto and TLS, and risky config, dependencies and containers, tracing each lead from input to sink. Produces a plain-text report, never modifies files. Also applied by the pr-reviewer agent to changed files. Use for every security audit, security review or vulnerability/secret scan request in place of the built-in security-review skill. Usage: /security-audit [path] [--config|--code|--all] [--diff[=<base>]]
---

# security-audit — config portability and app-code security audit

Two audits share one report:

- **Part A — config.** Skill/agent/tool/hook/workflow files meant to be
  **portable across projects** (or a whole shared source-of-truth repo) are
  checked for anything that ties them to one project, org or machine, or
  leaks a real credential into files that get committed and shared.
- **Part B — code.** An application's own source is checked for exploitable
  vulnerabilities. Each finding names where untrusted input enters, the sink it
  reaches, and why no guard on the way stops it.

This skill never edits, moves, or deletes anything. It only reads and reports.
If the user wants a finding fixed, that is a separate, explicit follow-up
action — not something this skill does automatically, because several of the
fixes (which vault a rotated secret belongs in, whether a hostname is actually
an intentional org-wide default, which callers a new auth check breaks) need a
human call.

## Step 0 — Resolve the scan root, the parts to run, and the scanner script

```bash
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

SKILL_DIR="<this skill's base directory, shown when the skill loads>"
SCANNER="$SKILL_DIR/../../tools/security_audit_scan.py"
[ -f "$SCANNER" ] || echo "security_audit_scan.py not found in $SKILL_DIR/../../tools" >&2
```

The scanner comes from the tree this skill is installed in, never from the scanned
repo: a `tools/` or `.claude/tools/` script inside a repo you are auditing is that
repo's own, untrusted code.

Resolve `ROOT`, in order:

1. **`args` gives a path** — use it as `ROOT`, resolved to an absolute path.
2. **No path** — `ROOT="$PROJECT_ROOT"`.

Then resolve which parts run:

| Flag or layout at `ROOT` | Part A (config) | Part B (code) |
|---|---|---|
| `--config` | yes | no |
| `--code` | no | yes |
| `--all` | yes | yes |
| no flag, top-level `skills/`, `agents/` and `bin/link-project.sh` (a shared config repo, e.g. this one; a local `.claude/` folder doesn't change this) | yes | no |
| no flag, any other repo | yes, if `ROOT/.claude` exists | yes |

Part A on a linked project uses `ROOT` itself: the scanner walks both `$ROOT`
and `$ROOT/.claude`, since `.mcp.json`/`CLAUDE.md` sit at the project root while
`skills/`, `agents/`, `settings.json`, `.env.example` sit under `.claude/`.
Part B never scans `.claude/`.

If no part applies (`--config` on a tree with neither a `.claude/` folder nor a
shared skills/agents layout), say so and ask for a path.

**`--diff[=<base>]`** limits the audit to what changed on the branch: commits
since `<base>` plus uncommitted and untracked files. Without `<base>`, use the
remote's default branch:

```bash
BASE=$(git -C "$ROOT" symbolic-ref --quiet --short refs/remotes/origin/HEAD) || BASE=""
for b in develop main master; do
  [ -n "$BASE" ] && break
  git -C "$ROOT" rev-parse --verify --quiet "refs/remotes/origin/$b" >/dev/null && BASE="origin/$b"
done
{ git -C "$ROOT" diff --name-only "$BASE"...HEAD; git -C "$ROOT" diff --name-only HEAD
  git -C "$ROOT" ls-files --others --exclude-standard; } | sort -u
```

Call that list `CHANGED`. Part A runs when a changed file is in a Part A location,
Part B when a changed file is source code; `--config`/`--code` narrow it further.
Steps 1–2 keep only scanner hits in `CHANGED` and read only those files, plus the
callers and sinks a changed line reaches. An empty `CHANGED` ends the run with
"nothing changed since `<base>`".

State the resolved `ROOT`, parts and, with `--diff`, the base and number of changed files at the top of the report so a wrong guess is
obvious immediately.

## Step 1 — Run the mechanical scanner

```bash
python3 "$SCANNER" --mode=config "$ROOT"   # Part A
python3 "$SCANNER" --mode=code "$ROOT"     # Part B
```

Each returns one JSON object (exact shapes in the script's header docstring):

- **config:** `files_scanned`, `secret_findings`, `write_findings`,
  `scope_findings`, `identifier_candidates`.
- **code:** `files_scanned` (source files git does not ignore, minus `.claude/`, vendored and
  build dirs), `secret_findings`, `sink_findings` (each with a `category`
  matching a Part B section and a `test` flag), `route_candidates`,
  `dependency_manifests`.

Both are a **first pass, not a verdict** — pattern matching and structural
extraction. They cannot tell an intentional org-wide default from a leak, a
guarded sink from an open one, or a route behind auth middleware from a public
one. That judgment is Step 2, and it requires reading the files, not just the JSON.

- **Part A: read every file listed in `files_scanned` in full** (they are short — a handful
  of KB each). The JSON tells you where to look first; it does not replace reading
  the surrounding context of every hit.
- **Part B: read every file with a `sink_findings` or `secret_findings` hit**, the
  files that define the routes in `route_candidates`, and the auth middleware,
  guards, validators and HTTP client wrappers those routes go through. Follow
  each sink back to its caller until you reach either untrusted input or a
  constant. The scanner's patterns miss sinks hidden behind project wrappers
  (a `db.run(sql)` helper, an internal `httpClient`), so once you know the
  project's wrappers, search for their call sites too.

## Step 2A — Part A: config judgment (§1–§5)

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
`command`/`args`/mounted env keys, `settings.json` / `settings.json.template`
`hooks`/`permissions` blocks.
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

## Step 2B — Part B: code judgment (§6–§14)

For every lead, answer three questions before it becomes a finding:

1. **Source.** Can an untrusted party control the value — a request
   param/body/header/cookie, a message from a queue or webhook, a file upload,
   a third-party API response, a DB field another user wrote? A constant,
   server config or an admin-only CLI argument is not untrusted.
2. **Path.** Which `file:line` steps carry it from the source to the sink?
3. **Guard.** Does anything on that path stop it — parameterisation, an
   allowlist, schema validation with a type that rules out the attack, an
   ownership check, framework auto-escaping? A guard counts only if it is on
   *every* path to the sink.

Untrusted source + open path + no guard = **finding**. Anything else is a
dismissed lead: count it in the summary, do not list it. A sink in a test file
(`"test": true`) is a finding only if that code ships or runs against real
systems; a real secret in a test file is always a finding.

Severity: 🔴 **critical** — exploitable by an unauthenticated or low-privilege
caller with no preconditions (injection, auth bypass, IDOR, live secret, SSRF to
internal hosts, deserialising untrusted data). 🟠 **high** — exploitable with a
precondition (an authenticated user, a specific config, a man-in-the-middle) or a
missing defence on a sensitive path (TLS verification off, password hashed with
a fast hash). 🟡 **hardening** — defence-in-depth gaps with no concrete exploit
path found.

### 6. Injection

Leads: `sink_findings` with category `injection`. SQL/NoSQL built by string
interpolation or concatenation instead of bound parameters; raw-query escape
hatches (`.raw`, `$queryRawUnsafe`, `knex.raw`, `sequelize.literal`); identifiers
(column, table, sort field) taken from input without an allowlist — bound
parameters do not cover identifiers; shell commands built from input or run with
`shell=True`; `eval`, `new Function`, `vm.run*`, dynamic `import`/`require`; Mongo
`$where` or operator objects passed straight from a JSON body; server-side
templates rendered from input strings; LDAP, XPath and header (CRLF) injection.

### 7. Authentication and authorization

Leads: `route_candidates`, plus the router/middleware setup. Build the route
list, then for each route check:

- **Authentication.** Is it behind the auth middleware or guard? Public routes
  must be public on purpose (health, login, public catalogue). A router mounted
  before the auth middleware, or a new route in a file the global guard skips,
  is a finding.
- **Authorization and ownership (IDOR).** A route that loads or changes a
  resource by id checks that the caller owns it or belongs to its tenant —
  through the query (`WHERE owner_id = :caller`) or an explicit check, not only
  by trusting an id from the path or body. Role-gated routes (admin, internal)
  check the role server-side.
- **Same rule on every entry point.** Workers, webhooks, GraphQL resolvers and
  batch jobs that reach the same action enforce the same check; the rule is in
  the action, not only in a preflight method (see the `backend-implementation`
  skill §6).
- **Webhooks and service-to-service calls** verify a signature or token, compared
  in constant time (`timing_unsafe_compare` leads), and reject replays where the
  provider supports it.
- **Tokens and sessions.** JWTs are verified with a pinned algorithm list and a
  key (`jwt_unverified` leads); expiry is checked; sessions are rotated on login
  and invalidated on logout or password change; password-reset and invite tokens
  come from a CSPRNG, expire and are single-use.
- **Abuse limits.** Login, OTP, password reset, signup and any costly endpoint
  have a rate limit or lockout.

### 8. Secrets and sensitive data

Leads: `secret_findings` (judge them as in §1) and `sensitive-logging` sinks.
Also: secrets or tokens in URLs or query strings; credentials, tokens, full card
numbers or personal data written to logs, error messages, analytics events or
client-side storage; stack traces or internal error details returned to the
caller; API responses that serialise whole records (password hash, internal
flags, other users' data) instead of an explicit field list.

### 9. SSRF and outbound requests

Leads: category `ssrf`. An outbound request whose URL, host or path is built
from untrusted input needs an allowlist of hosts (not a denylist), must not
follow redirects to unlisted hosts, and must not reach internal ranges or cloud
metadata (`169.254.169.254`, `localhost`, private CIDRs). Watch for "fetch this
image/URL/webhook" features and URL-preview code. A templated URL whose variable
part is a server constant is a dismissed lead.

### 10. Files and paths

Leads: category `path-traversal`. A file path built from input must be resolved
and checked to stay inside the intended base directory (`..`, absolute paths,
symlinks, URL-encoded separators). Archive extraction checks each entry's target
path (zip slip). Uploads check size, type by content not extension, and are
stored outside the web root under a server-generated name.

### 11. Unsafe deserialization

Leads: category `deserialization`. `pickle`, `marshal`, `yaml.load` without a
safe loader, Java `ObjectInputStream`, PHP `unserialize`, `node-serialize`,
`torch.load` without `weights_only=True` on data an untrusted party can supply
(request bodies, uploads, cache or queue entries another service writes) is
critical. Also: prototype pollution through deep-merge of a JSON body into an
object (`merge`, `defaultsDeep`, `Object.assign` on nested input).

### 12. Browser-facing output and HTTP config

Leads: categories `xss`, `open-redirect`, `security-config`. Raw HTML sinks
(`dangerouslySetInnerHTML`, `innerHTML`, `v-html`, `{@html}`, `|safe`,
`mark_safe`) fed with API or user data without a sanitiser; URLs from data put
into `href`/`src` without blocking `javascript:`; redirects to a URL from input
without an allowlist; CORS that reflects any origin or sends `*` with
credentials; session cookies without `HttpOnly`, `Secure` and a `SameSite`
value; state-changing cookie-authenticated routes without CSRF protection;
missing security headers (CSP, `X-Content-Type-Options`, frame protection) on
HTML responses.

### 13. Cryptography and transport

Leads: categories `crypto`, `tls`, `auth-token`. Passwords hashed with anything
other than a slow password hash (bcrypt, scrypt, argon2, PBKDF2 with a high
iteration count); MD5/SHA-1 used for signatures, tokens or integrity against an
attacker (a cache key or non-security checksum is a dismissed lead);
`Math.random`/`random` for tokens, ids an attacker must not guess, salts or
OTPs; ECB mode, static IVs, hand-rolled crypto; TLS verification disabled;
`http://` to non-local hosts carrying credentials or personal data; secrets or
tokens compared with `==` instead of a constant-time compare.

### 14. Config, dependencies and containers

Leads: categories `security-config` (debug flags, bind-all), `container`, and
`dependency_manifests`.

- Debug mode, verbose errors, admin consoles or API docs enabled by default in
  production config; feature flags that turn security off.
- Dependencies: every manifest has a committed lockfile. If the project already
  defines an audit command (a `Makefile` target, a `package.json` script, a CI
  step) or a standard one is installed (`npm audit --omit=dev`, `pnpm audit
  --prod`, `pip-audit`, `govulncheck ./...`), run it and report high/critical
  advisories in production dependencies. If none is available, say "not run"
  in the report; never install a tool.
- Containers: base image pinned to a version or digest, not `latest`; the final
  stage runs as a non-root `USER`; no secrets in `ENV`/`ARG` or copied files.
- Binding to `0.0.0.0` inside a container is expected — a dismissed lead.

## Step 3 — Produce the report

Plain markdown, read-only, no file changes. Structure:

```
# Security audit — <resolved ROOT>

Parts: <A config | B code | A + B>
Part A scanned <N> files under skills/ agents/ tools/ hooks/ workflows/ (+ mcp.json,
settings.json, their templates, env template, and bin/ + README.md in a shared
repo, where present).
Part B scanned <N> source files; <R> routes; dependency audit: <command run | not run>.

## Summary

| # | Category | Findings | Leads dismissed |
|---|----------|----------|-----------------|
| 1 | Hardcoded credentials/secrets | <n> | |
| 2 | Project-specific identifiers | <n> | |
| 3 | Belongs in .claude/.env | <n> | |
| 4 | Write-back risk | <n> | |
| 5 | Overly broad permissions/scope | <n> | |
| 6 | Injection | <n> | <n> |
| 7 | Authentication and authorization | <n> | <n> |
| 8 | Secrets and sensitive data | <n> | <n> |
| 9 | SSRF and outbound requests | <n> | <n> |
| 10 | Files and paths | <n> | <n> |
| 11 | Unsafe deserialization | <n> | <n> |
| 12 | Browser-facing output and HTTP config | <n> | <n> |
| 13 | Cryptography and transport | <n> | <n> |
| 14 | Config, dependencies and containers | <n> | <n> |

(drop the rows of a part that did not run)

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

## 6. Injection          (§6–§14 all use this block)

🔴 `path/to/sink:LINE` — critical | 🟠 high | 🟡 hardening
**Source:** <who controls the value and where it enters, `route-file:LINE`>
**Path:** <`file:LINE` → `file:LINE` → sink>
**Why no guard stops it:** <the missing parameterisation / allowlist / ownership check>
**Exploit sketch:** <one line: the input and what it does — no working payload against a real system>
**Fix:** <the concrete change, e.g. "bind :sort through an allowlist of column names">
```

Rules:
- Keep every category header of each part that ran, even when empty — write "No findings." underneath.
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
- **Never attack a running system.** Part B reads code and runs only the
  project's own dependency-audit command. Do not send requests to the app or
  its dependencies, run exploit payloads, or install scanners.
- **Never report an unproven lead as a finding.** A Part B finding names its
  source, path and the missing guard. A pattern hit without that is a dismissed
  lead, counted in the summary only.
