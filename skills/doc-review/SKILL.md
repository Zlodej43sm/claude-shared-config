---
name: doc-review
description: Review or write technical documents - architecture docs, design docs, plans, specs, ADRs/RFCs, data contracts, runbooks, READMEs - in a PR, a branch, a local file or a Confluence/Notion page. Checks that durable docs hold only the target state (transitory plans live elsewhere), that flows and data models are shown as diagrams and tables instead of prose, that the wording is plain and free of AI-style filler, that every claim about code or other repos is true on their default branch, that each rule lives in one place at the right level of detail, that docs, comments, tests and config in the change agree, that the lifecycle questions a reviewer will ask are answered, and that the design covers its failure modes. Use when asked to review a docs-only or design PR, alone or alongside pr-review; whenever you write or edit a doc (including fixing review comments on one); and before opening or updating a PR that adds or changes a doc. Read-only - never posts unless asked.
---

# doc-review — review (or write) a technical document

Generic and reusable: no company or project data lives here. Rules come from:
1. This skill: §A–§I below.
2. The project's docs conventions: follow the root `CLAUDE.md` / `AGENTS.md` (workspace and repo) to its docs layout, glossary (`CONTEXT.md` or similar), writing-style and review docs. Project rules win over this skill.

A finding cites the rule it breaks (`doc-review §X`, or the project doc path + section).

When **writing** or editing a doc, or fixing review comments on one, run `references/self-check.md` on every changed doc before each commit and before you open or update the PR. Fix what it finds instead of reporting it. It lists the checks in order of how often reviewers raise them.

## Step 1 — scope
- Get the changed docs (`git diff <base>...<head> -- '*.md' docs/`) and read each one whole, plus the docs it links and the docs that should link to it.
- Read the PR description, the ticket and **all existing review threads**. Don't repeat a point a reviewer already raised; reference it ("already raised by <reviewer>").
- Classify each doc: **durable** (architecture, contract, glossary, runbook, README: describes how the system is) or **transitory** (plan, proposal, migration, RFC: describes a change). The class decides §A.

## Step 2 — check, in this order

**§A Durable vs transitory.**
- A durable doc states only the desired, durable state. Flag "today", "currently", "where things stand", "we will", "after this change", "phase 1", ticket lists, rollout steps and migration notes in it. That text goes to tickets (epic, tasks), a wiki page, or a separate plan doc.
- No history either: "previously 409", "the old/legacy behaviour", rollout and rollback order, ticket keys in headings or text (a heading names the concept, e.g. "Session end"). A live config switch may be named once, with a link to the ADR or runbook that owns its rollout.
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
- The truth is the owning repo's **default branch** (fetch first), not an open PR, a feature branch, a plan doc or a ticket. A durable doc that describes unmerged behaviour (yours or a sibling's) is a finding: that text lands with the code change, or after it merges.
- A behaviour you cannot find in any code is a finding phrased as "where is this implemented?", never assumed true. Plan docs and tickets are not evidence.
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

**§H One home, right altitude.**
- Each rule lives in one canonical section. Other docs link to it instead of restating it: two copies drift and end up contradicting each other. A rule repeated inside one doc (e.g. once per mode) is stated once.
- An architecture or contract doc states the rules and contracts that callers and operators depend on. Implementation detail (TTL and timeout values, log event names, internal keys, storage paths, function names) stays in the code or the owning repo's docs.
- A glossary entry is one short sentence of meaning, with no mechanism. Keep it within the project's length cap if it has one.

**§I The change agrees with itself.**
- Docs, code comments, test names and comments, e2e assertions, config defaults and READMEs in the same change say the same thing. A contradiction is a finding in each place.
- A config default the change turns on matches the rollout order the docs state. If it depends on an unmerged change in another repo, the merge order is written down (PR description, README).
- A test that claims to prove a documented rule fails when the rule breaks. It must not pass because the state is already terminal, a wait returns at once, or the good and bad outcomes look the same.

## Step 3 — report
- Findings ranked **blocking** (wrong claim the design relies on, a design gap that loses or leaks data, a durable doc mixing in plan content when the project forbids it), **should fix** (§A–§C, §E–§I gaps; a durable doc describing unmerged behaviour), **question**, **[nit]**.
- Each finding: `file:line` — what is wrong (rule cited) — why it matters (a concrete case: a timeout, a retry, a second instance, a reader who can't find the answer) — the proposed fix (a ready diagram/table skeleton or replacement text in a `suggestion` block).
- Ask when the intent is unclear instead of asserting.
- A should-fix that needs the author or the doc's owner to choose first (which source is right, should two docs agree) is labelled `should-fix (decision needed)` in the review only. Its comment text is written the way a human reviewer would: short, plain words, only the facts needed to answer, one question, at most one suggested way forward, and no label, emoji, bold or rule citation. When posted, it goes out as that plain text alone. Every other finding keeps its usual label.
- Read-only: don't edit, post or resolve threads unless the user asks.

## Learning from reviewers
When a human reviewer's comments on a doc reveal an expectation this skill doesn't cover, propose a generic rule for the right § (no names, no project data) and add it here only after the user agrees: this file is shared by every linked project. Project-specific expectations go to the project's own docs-conventions file instead. Keep this file short: merge with an existing bullet before adding a new one.
