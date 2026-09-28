---
name: project-blueprint
description: Turn a ticket, project description, or feature proposal into an implementation-ready project blueprint — architecture, service ownership, API inventory, proposed directory tree, and a phased roadmap — grounded in technologies and patterns the organization already uses. Fetches ticket/Confluence context via the jira-context agent, inspects the target repo and relevant sibling services (reusing project-overview's scanner), and writes planning documents only — no production code. Usage: /project-blueprint <ticket-key | free-text description> [-- <repo1> [<repo2> ...]]
---

# project-blueprint — pre-implementation project & feature blueprint

Turns a ticket (or a plain-text feature description, if there is no ticket yet) into a
blueprint a manager, an architect, a developer, and a QA engineer can each read and get what
they need from — before any implementation plan or code exists. It sits **before**
`implement` in the lifecycle: `project-blueprint` decides and documents *what* should be
built and *how*, grounded in what the organization already has; `implement` then turns one
concrete piece of an approved blueprint into an execution-ready task list.

**You write no production code in this skill, ever, unless the user explicitly asks you to
go further than the blueprint in the same request.** Even then, hand off to `implement` for
the actual execution plan rather than improvising it inline here.

## Use When

- Starting a brand-new service or a substantial feature and a shared, reviewable design is
  needed before an implementation plan or code exists.
- The ticket only sketches a goal (sparse description, no acceptance criteria) and someone
  needs a concrete, best-practices-grounded design before work can be scoped.
- A manager, an architect, a developer, and QA all need to work from one document instead of
  separate walkthroughs or tribal knowledge.
- The user gives you a plain-language feature idea with no ticket at all and wants it turned
  into something implementation-ready.

## Do Not Use When

- A design is already agreed and you just need an execution-ready task list → use `implement`.
- You want to analyze what an **existing** repo already does, with no forward-looking
  proposal → use `project-overview` (this skill's Step 3 reuses its scanner, but its own
  report is a different artifact for a different question).
- You want a plain-English doc of an **already-implemented** branch's changes → use
  `feature-doc`.
- You just need to read a ticket's content, nothing more → use `get-jira-task`.
- You're auditing this shared config tree itself for secrets/portability → use
  `security-audit`.

## Input

```
<ticket-key | free-text description> [-- <repo1> [<repo2> ...]]
```

- If the first token matches a Jira issue key (`^[A-Z][A-Z0-9_]+-\d+$`), treat it as a ticket
  key and fetch it in Step 1.
- Otherwise, treat everything before a literal ` -- ` as a free-text project/feature
  description and skip Step 1's Jira fetch — use the text directly as the requirements
  source in Step 2.
- `-- <repo1> ...` — optional local paths to related/sibling repos to inspect in Step 3. If
  omitted, Step 3 discovers likely siblings itself.
- If invoked with no input at all, ask the user for a ticket key or a short description
  before proceeding — don't guess at scope.

## Step 0 — Load env, resolve the target repo

```bash
set -a; . ./.claude/.env; set +a
```

Required only if a ticket key was given: `JIRA_WORKSPACE`, `JIRA_BASE_URL`, `JIRA_EMAIL`,
`JIRA_API_TOKEN`. Not required for free-text input — don't block on Jira credentials for a
request that never needs Jira.

Resolve the target repository as `$CLAUDE_PROJECT_DIR`, else `git rev-parse
--show-toplevel`, else cwd — the same resolution `project-overview` uses. State the resolved
target repo at the top of the eventual blueprint, so a wrong guess is obvious immediately.

## Step 1 — Read the ticket, description, and linked docs

Skip this step entirely for free-text input.

For a ticket key, spawn the `jira-context` subagent exactly as `implement`'s Step 1 does:

```
Review and gather context for a Jira ticket. Values:

  ticket_key:    <RESOLVED_KEY>
  related_repos: <comma-separated paths, or "none">
  project_root:  <absolute path to target repo>

Run your full context-gathering procedure (Steps 1-6) and return the complete context block as your final message.
```

Capture the full `=== JIRA CONTEXT: <key> === ... === END JIRA CONTEXT ===` block. Do not
summarize or drop content here — Step 2 needs the full text, including anything sparse or
ambiguous.

## Step 2 — Extract requirements and confirm the target repository

From the context block (or the free-text input), extract:

- The feature/service name and a one-line statement of what it's for.
- Every discrete requirement as its own bullet — don't merge related-but-distinct asks into
  one bullet, they need to be individually traceable in Step 10.
- Acceptance criteria, if any.
- Anything unclear, missing, or contradictory — flag it now as an assumption candidate; it
  either gets resolved with evidence in Steps 3-7 or lands in the blueprint's open-questions
  section (§13). Never silently resolve an ambiguity the ticket didn't actually resolve.

Confirm which repository this blueprint targets. Usually the current project (Step 0); if
the ticket/description clearly names a different repo, or if it's genuinely ambiguous, ask
the user rather than guessing — this decision anchors everything else.

## Step 3 — Inspect the target repo and relevant sibling services

Reuse `project-overview`'s scanner rather than re-implementing repository inspection. Resolve
it the same way that skill does — this is independent of the target repo, since the scanner
lives wherever the *current* session's `.claude/tools/` is linked from:

```bash
SCANNER="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}/.claude/tools/project_overview_scan.py"
[ -f "$SCANNER" ] || SCANNER="${CLAUDE_PROJECT_DIR:-$(pwd)}/tools/project_overview_scan.py"
[ -f "$SCANNER" ] || SCANNER=""
```

Run it against the target repo, and always pass `--siblings` — unlike in `project-overview`
(where sibling scanning is optional, off-by-default enrichment), sibling discovery is central
to this skill:

```bash
[ -n "$SCANNER" ] && python3 "$SCANNER" "$TARGET_REPO" --siblings \
  ${related_repos:+--related="$related_repos"}
```

If `$SCANNER` is empty or exits non-zero, fall back to Glob/Grep for the same categories
`project-overview`'s Step 1 fallback list covers (metadata, manifests, entry points, CI/CD,
infra/deploy, config, source layout, tests) — don't duplicate that list here, use it
verbatim.

(The scanner's `source_layout` is depth-limited and does not include a nested directory
breakdown — for a multi-module or deeply-nested repo where Step 8's tree needs more structure
than that, follow up with a targeted Glob rather than treating `source_layout` as the complete
picture.)

**Sibling services**, unlike in `project-overview` (where they're optional enrichment), are
central to this skill — the blueprint needs to know what already exists before proposing
anything new:

- If `-- repo1 repo2 ...` was given, they're already covered by `--related=` above — read each
  one's own manifest/entry-point content the same way the target repo's was read.
- Otherwise, shortlist candidates from the scanner's `sibling_repos` output (real, `.git`-
  confirmed repos next to the target) — never re-list the parent directory by hand instead;
  it surfaces IDE folders, archives, stray data files, and ambiguously-named non-git duplicates
  that `sibling_repos` already filters out for you. Shortlist by name, README, or other
  top-level index/overview doc plausibly relating to the requirements from Step 2
  (domain-keyword match, or an explicit mention in the ticket/description) — don't assume a
  sibling exists just because the requirements *could* relate to one; confirm the repo exists
  and looks relevant before including it.
- Before concluding, anywhere in Steps 5-7, that a capability has **no organizational
  precedent**, make sure the search actually reached source code for the shortlisted siblings,
  not just their names/READMEs — a sibling can implement a pattern (e.g. header-based API-key
  auth checked against a DB) without that pattern being mentioned by name in its README at all.
  A quick source-level grep for the requirement's domain keywords across shortlisted siblings
  is cheap insurance against declaring a false gap.
- For more than ~3 siblings, fan out one `Agent` call per sibling to scan it (scanner call)
  and then read whatever entry points/route files Step 4-5 actually need beyond what the
  scanner extracts — mirrors `project-overview`'s Step 9 fan-out guidance. Cap at ~10; merge
  or drop the least-relevant beyond that and say so explicitly in §13, never silently.
- Each sibling agent should report back: confirmed tech stack, confirmed HTTP/RPC routes
  relevant to the requirements (method, path, purpose, auth, source file — this is the raw
  material for §9/the API inventory), and any pattern (auth, DB, error handling, testing,
  deploy) worth citing as a reference.

## Step 4 — Discover technologies and conventions already in use

Synthesize Step 3's scan output into a tech profile for the target repo (and, more lightly,
each sibling): language, framework, package manager, DB/ORM, validation library, auth
mechanism, error-handling shape, logging/observability setup, test framework, Docker/CI/CD
setup. Label every entry **Confirmed** (present literally in a manifest/lockfile/config/
source file) or **Inferred** (deduced with no direct manifest entry) — the same discipline
`project-overview` uses. Never blur the two into one unlabelled claim.

## Step 5 — Identify reusable services, APIs, and patterns

Against the requirements from Step 2, go through Step 4's findings and identify, for each
relevant capability (auth, database, testing, deployment, and any specific API a sibling
already exposes):

- A **service or route the target can call directly at runtime** — cite the exact route
  (method, path, source file).
- A **pattern worth porting** (a design/schema/approach to copy, not a live dependency) —
  cite the source file the pattern comes from, and say explicitly that it's a pattern, not a
  callable dependency.
- Where the organization's own tooling doesn't cover a requirement at all (no existing DB
  pattern fits, no existing auth model fits) — say so plainly; that's a real gap, not
  something to paper over with a strained "closest match."

**Do not introduce a new framework, ORM, validation library, authentication model, or
architectural style if an existing, suitable pattern was found in Step 3-4.** If none exists
for a given concern, recommend the best practice you'd genuinely stand behind, and say
explicitly that no organizational precedent exists for it — state the gap plainly rather than
forcing a strained fit to an unrelated existing pattern, but only make that claim after Step
3's search actually reached sibling source code, not just names/READMEs (see Step 3). Never
treat an unverified "no precedent exists" claim in another document as proof this run's own
search was thorough — each run must re-establish it from that run's own Step 3 evidence.

## Step 6 — Separate confirmed facts from assumptions and recommendations

Before drafting anything, tag every non-trivial claim gathered so far as one of exactly six
labels — reuse these consistently through the rest of this skill and in the output documents:

| Label | Meaning |
|---|---|
| `Existing` | Runs today, in this repo or a sibling — reference only, cite the file |
| `Reusable` | An existing route/service the target can call directly at runtime |
| `Missing` | A capability the requirements need, with no existing route or pattern |
| `Proposed` | A new component this blueprint recommends building, with a stated contract |
| `Assumed` | A judgment call made where the ticket/description didn't specify — must be justified and listed in §13 |
| `Undecided` | A genuine open question this blueprint cannot resolve on its own — must be listed in §13, never silently defaulted |

Never present an `Assumed` or `Undecided` item as if it were `Existing` or a settled
`Proposed` decision.

Give the label a concrete place to live rather than just a shared understanding while writing:
prefix each row or bullet in README §4/§8/§9/§13 and each row of the API-inventory table
(Step 9) with its label, e.g. `[Existing]`, `[Undecided]`. A labelling discipline that exists
only in this step's prose and never actually reaches the documents is not "used throughout,"
per the Completion checklist.

## Step 7 — Identify existing vs. missing capabilities

Build a capability-by-capability table: for each requirement from Step 2, does it map to an
`Existing`/`Reusable` capability (Step 5), or is it `Missing`? This table is the direct input
to both §8/§9 of the README template and to the API inventory document — don't derive it
twice.

## Step 8 — Propose the initial project directory tree

Rules:

- The tree must follow the target repo's **existing** structure if it has one (extend real
  observed directories/naming from Step 3-4, don't invent a generic layout). If the repo is
  empty/green-field, follow the closest sibling's structure found in Step 3, and say which
  sibling it's modeled on. If no sibling shares the stack Step 5 actually recommends (this is
  expected whenever that recommendation itself had no organizational precedent), don't
  force-fit an unrelated sibling's layout — follow that framework/language's own standard
  project-layout convention instead, and say explicitly that no sibling was modeled on and why,
  mirroring Step 5's Missing-capability disclosure.
- For every proposed directory or file of consequence, state: its responsibility, why it's
  needed, which existing pattern it follows (cite the sibling/file), and whether it belongs
  to the initial implementation or a later phase.
- No empty placeholder folders, no speculative abstractions for hypothetical future needs.

## Step 9 — Prepare the documents

Write two documents (fewer if the ticket is small enough that a separate API-inventory doc
would be empty; never more without a clear reason):

**1. The README** (`<target-repo>/README.md`). If a README already exists with unrelated
content, preserve it and add a clearly separated, well-labelled section for this blueprint
rather than overwriting; if the whole repo is dedicated to this feature (a genuinely
green-field service, as in the `art-public-api`/MA-225 precedent), the README *is* the
blueprint — no separate wrapper section is needed. Structure:

```markdown
# <project/feature name>

## 1. Executive summary
One short paragraph, no jargon — what this is, why it's needed, current status.

## 2. Goal and business value
What problem this solves and for whom; link the ticket if one exists.

## 3. Scope and non-goals
What's explicitly in and out of scope for this iteration.

## 4. Current state
What exists today that's relevant (Existing/Reusable, from Steps 5-7) — condensed, tables
over prose, link the API inventory (below) for route-level detail rather than repeating it.

## 5. Proposed solution
The technical design: what gets built, the key decisions, and why — cite the pattern each
decision follows (Step 5) or state plainly that none exists and this is a best-practice call.

## 6. Architecture and data flow
A Mermaid architecture diagram and a Mermaid request/data-flow sequence diagram. Keep each
diagram small enough to read at a glance; every diagram must match exactly what the
surrounding text says — no invented components.

## 7. Services and ownership
Which services/teams own which piece; one line each.

## 8. Existing capabilities to reuse
Pulled from Step 5/7 — only `Reusable`/`Existing`-and-directly-applicable items, each cited.

## 9. Missing capabilities
Pulled from Step 7 — the concrete gaps this blueprint's "Proposed solution" (§5) addresses.

## 10. Proposed project tree
From Step 8 — the tree plus the responsibility/rationale/pattern/phase notes.

## 11. Implementation phases
A short Mermaid roadmap diagram plus a phases table (phase | scope | key deliverables).

## 12. Testing and rollout
Test scenarios derived from the requirements (a short table: scenario | expected result —
enough for QA to start from, not a full test plan), plus a rollout/migration approach. If the
ticket gives no acceptance criteria, don't leave this table thin — derive at least one scenario
per error/status code introduced in the Proposed routes table (e.g. each 401/404/409 case),
plus one per non-trivial behavior called out in §5 (e.g. "revoke takes effect within one cache
TTL").

## 13. Decisions and open questions
Two tables: decisions made (with rationale) and open questions/risks (with why it matters
and the current default, if any) — every `Assumed`/`Undecided` item from Step 6 must appear
here. End with a short **Definition of done** checklist tied to the requirements from Step 2 —
at minimum one item per Step 2 requirement bullet, plus one per `Assumed`/`Undecided` item that
must be resolved before ship. Don't skip this: nothing else in this skill re-verifies it except
the Completion checklist below.
```

**2. The API inventory** (`docs/<SLUG>_API_INVENTORY.md`, `SLUG` = the ticket key with
non-alphanumerics as `_`, or a short slug of the feature name for free-text input). One
compact table per service — existing, reusable, missing, and proposed routes together,
labelled with the Step 6 vocabulary:

```markdown
| Label | Method & Path | Description | Auth | Request | Response | Errors | Status | Source |
|---|---|---|---|---|---|---|---|---|
```

`Label` is one of Step 6's six values, one per row — this is the column the mandatory
vocabulary actually lives in; without it, an `Existing` row and a `Proposed` row (or an
`Undecided` row and a settled one) are indistinguishable at a glance. The remaining columns are
a minimum, not a rigid literal requirement — Auth and Status may fold into the adjacent
Request/Errors columns instead of standing alone when a route's auth or status is simple
enough to state inline.

Link the two documents to each other. Detailed route/schema content belongs in the
inventory; the README stays at decision/architecture altitude and points there instead of
repeating tables — this is not optional polish, a README that re-embeds full route tables
defeats the purpose of having a separate inventory. This applies most directly to
**sibling/reference** routes (other services' current, already-live contracts) — keep those
out of the README entirely. A green-field target's **own proposed** routes may stay inline in
the README instead of the inventory only when there is no pre-existing inventory doc to
preserve them in and no separately-tracked contract exists elsewhere for the ticket — state
explicitly that this is why, rather than defaulting to it.

Use tables, short lists, and diagrams over long paragraphs throughout both documents. Keep
terminology and route names identical across both documents.

## Step 10 — Validate every proposed component maps to a requirement

Before presenting anything, check:

- Every `Proposed` item (Step 6) traces to a specific requirement bullet from Step 2 — no
  orphaned proposals.
- Every `Existing`/`Reusable` claim has a repo-relative file citation.
- Every `Assumed`/`Undecided` item appears in §13, none were silently resolved.
- The proposed tree (§10/Step 8) actually matches the technologies discovered in Step 4 (no
  Express-repo tree proposing a Django-style `models.py`, etc.).
- Both documents use the same terminology, route names, and Step 6 labels throughout.
- The README's §6 diagrams match exactly what §5/§7 say in prose.
- The README links to the API inventory, and vice versa where useful.
- A manager could understand §1-2 alone; a developer could start from §5-10-11 alone; QA
  could start from §12 alone — if any of the three would have to read the whole document to
  get their piece, restructure rather than ship it as-is.

If any check fails, fix the documents now — don't present a blueprint you know has a gap.

## Step 11 — Present to the user

Give the executive summary, the target repo, the technology/pattern choices and why, the
count of reusable vs. missing capabilities, and the full open-questions list directly in
chat. Point at the two file paths for full detail — do not paste either document in full
into chat, matching this repo's `project-overview`/`split-pr` convention.

If the user wants to proceed to an execution-ready task list for a specific piece of the
blueprint, tell them to run `/implement <ticket-key>` next — don't produce that plan inline
here.

## What NOT to do

- **Planning and scaffolding documents only, by default.** Never write production code
  unless the user explicitly asks for it in the same request — and even then, hand off to
  `implement` for the actual execution plan rather than improvising one here.
- **No unrelated file changes.** Only the README, the API inventory doc, and (if proposing
  it) empty directory placeholders described in §10 of the README are ever touched.
- **Never overwrite an existing README's unrelated content** — preserve and clearly append,
  per Step 9.
- **No secrets or real credentials** in either document, ever.
- **No copying large code blocks from sibling services** — cite and describe the pattern,
  don't paste implementations.
- **No presenting an assumption as a confirmed decision** — Step 6's labels are mandatory,
  not optional polish.
- **No inventing a route, schema, or infrastructure component without evidence** — every
  `Existing`/`Reusable` row needs a citation; every `Proposed` row needs a requirement it
  satisfies.
- **No silent scope-narrowing** in Step 3's sibling fan-out — if siblings were merged or
  dropped for scale, say so in §13.

## Completion checklist

Do not finish until all of these hold:

- [ ] The original requirements (Step 2) are each covered somewhere in the blueprint.
- [ ] A proposed directory tree (§10) was actually produced — not merely consistent with
      Step 4's tech *if* it existed, but genuinely present, including in the empty/green-field,
      no-matching-sibling case (Step 8's fallback).
- [ ] The proposed tree (Step 8) matches the detected technology (Step 4).
- [ ] Existing and missing capabilities are clearly separated (Step 6 labels used throughout —
      each row/bullet in §4/§8/§9/§13 and each inventory-table row carries its `Label`, not
      just a shared understanding left in prose).
- [ ] Every proposed API/component maps to a specific requirement (Step 10).
- [ ] Authentication and database recommendations reference a proven existing pattern, or
      explicitly say none exists and this is a best-practice recommendation — confirmed
      against actual sibling source (Step 3), not just names/READMEs.
- [ ] Diagrams match the written design.
- [ ] The README links to the API inventory (and any other supporting doc produced).
- [ ] §12's scenario table was actually produced, including derived scenarios if the ticket
      gave no acceptance criteria.
- [ ] A Definition of done checklist (§13) is present and traces to Step 2's requirements.
- [ ] A manager, a developer, and a QA engineer can each find what they need without reading
      the whole document.
- [ ] No important technical detail was lost while keeping the documents concise.
- [ ] No equivalent skill already covered this request (see `Do Not Use When`) — if one did,
      this run should not have happened.
