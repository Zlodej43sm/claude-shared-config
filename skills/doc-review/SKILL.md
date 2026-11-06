---
name: doc-review
description: Review or write technical documents - architecture docs, design docs, plans, specs, ADRs/RFCs, data contracts, runbooks, READMEs - in a PR, a branch, a local file or a Confluence/Notion page. Checks that durable docs hold only the target state (transitory plans live elsewhere), that flows and data models are shown as diagrams and tables instead of prose, that the wording is plain and free of AI-style filler, that every claim about code or other repos is true, that the lifecycle questions a reviewer will ask are answered, and that the design covers its failure modes. Use when asked to review a docs-only or design PR, alone or alongside pr-review, and before opening a PR that adds or changes a doc. Read-only - never posts unless asked.
---

# doc-review — review (or write) a technical document

Generic and reusable: no company or project data lives here. Rules come from:
1. This skill: §A–§G below.
2. The project's docs conventions: follow the root `CLAUDE.md` / `AGENTS.md` (workspace and repo) to its docs layout, glossary (`CONTEXT.md` or similar), writing-style and review docs. Project rules win over this skill.

A finding cites the rule it breaks (`doc-review §X`, or the project doc path + section).

When **writing** a doc, run the same checks on your own draft before you open the PR; fix them instead of reporting them.

## Step 1 — scope
- Get the changed docs (`git diff <base>...<head> -- '*.md' docs/`) and read each one whole, plus the docs it links and the docs that should link to it.
- Read the PR description, the ticket and **all existing review threads**. Don't repeat a point a reviewer already raised; reference it ("already raised by <reviewer>").
- Classify each doc: **durable** (architecture, contract, glossary, runbook, README: describes how the system is) or **transitory** (plan, proposal, migration, RFC: describes a change). The class decides §A.

## Step 2 — check, in this order

**§A Durable vs transitory.**
- A durable doc states only the desired, durable state. Flag "today", "currently", "where things stand", "we will", "after this change", "phase 1", ticket lists, rollout steps and migration notes in it. That text goes to tickets (epic, tasks), a wiki page, or a separate plan doc.
- A plan sits in its own place (e.g. `docs/plans/` or the project's equivalent), says what it changes, and links the durable docs it will update. It never sits among the durable architecture docs.
- If the project has no rule for where plans go, flag it once as a question and propose one; don't invent the layout silently.

**§B Show, don't narrate.**
- A flow, a sequence between services, an ownership or permission model, a lifecycle or state machine → a diagram in the format the project renders (Mermaid by default: `sequenceDiagram`, `stateDiagram-v2`, `flowchart`).
- A data model or schema change → a table per entity (column, type, null, default, key/constraint, index, notes) or an ER diagram; relations and uniqueness shown, not described.
- Endpoints → a table (method, path, caller/role, request, response codes). Config → a table (name, default, meaning). Enumerated states → a list of every value with its meaning and transitions.
- A paragraph that walks through steps or fields is a should-fix; give the diagram or table skeleton in the finding.

**§C Plain wording, no AI-style prose.**
- Short sentences, one idea each, readable by a non-native speaker. Use the project's glossary terms; don't coin new jargon, and define any new term once.
- Flag filler and inflation: "robust", "seamless", "comprehensive", "leverage", "ensures", "it's worth noting", "in order to", stacked adjectives, bold on every other phrase, rhetorical summaries, restating the same point in a list and again in prose.
- Flag vague verbs that hide the mechanism ("handles", "manages", "takes care of") — say what is read, written, sent, and by whom.
- A section that is long but says little is a should-fix: propose the shorter version.

**§D Claims are true.**
- Check every concrete claim against the source: names (topics, routes, env vars, tables, fields, classes), versions, defaults, status codes, "X already does Y", "no service needs to change". Read the sibling repos when available (compare the local checkout with its upstream first); cite `repo/path:line`.
- Use full, real names (full route paths, real env var names), not shorthand.
- A wrong claim that the design depends on is blocking; a wrong side remark is a nit.

**§E Reader questions are answered.** For every actor, credential, resource and entry point the doc introduces, the doc answers:
- **Bootstrap:** how is the first one made (e.g. the first admin key)?
- **Authorization:** who may create, read, update, rotate, revoke it — per operation?
- **Interface:** UI, API, CLI, or manual ops step?
- **Handoff:** how does a secret or credential reach the outside party, and what happens if it is lost or leaked?
- **Lifecycle:** every status, what each status allows, how it ends (expiry, revoke, delete, retention).
Missing answers are findings; phrase them as the question a reviewer would ask.

**§F The design holds up** (for design docs and plans):
- Failure modes: ambiguous failures (timeout after the remote side accepted), crash between two steps, partial success, and what the caller sees in each.
- Retries and idempotency: retry policy and limits, success/terminal conditions, idempotency keys, at-least-once vs exactly-once, duplicate starts.
- Concurrency: several instances, locks or leases, ordering, race between "register" and "done".
- Data: growth and retention, indexes for every lookup the doc describes, every config knob with a default.
- Contracts: what external callers get is an explicit allowlisted shape with a version, never internal payloads passed through; no internal paths, ids or error text leak.
- Security: authn/authz per route, tenant isolation, secrets at rest and their rotation, any user-supplied URL (SSRF), abuse limits.

**§G Fan-out.** List every other canonical doc the change makes stale (topology/service map, glossary, contracts, READMEs in other repos) and whether the doc names the follow-up. Missing fan-out is a should-fix.

## Step 3 — report
- Findings ranked **blocking** (wrong claim the design relies on, a design gap that loses or leaks data, a durable doc mixing in plan content when the project forbids it), **should fix** (§A–§C, §E–§G gaps), **question**, **[nit]**.
- Each finding: `file:line` — what is wrong (rule cited) — why it matters (a concrete case: a timeout, a retry, a second instance, a reader who can't find the answer) — the proposed fix (a ready diagram/table skeleton or replacement text in a `suggestion` block).
- Ask when the intent is unclear instead of asserting.
- Read-only: don't edit, post or resolve threads unless the user asks.

## Learning from reviewers
When a human reviewer's comments on a doc reveal an expectation this skill doesn't cover, add it here as a generic rule in the right § (no names, no project data); project-specific expectations go to the project's own docs-conventions file instead. Keep this file short: merge with an existing bullet before adding a new one.
