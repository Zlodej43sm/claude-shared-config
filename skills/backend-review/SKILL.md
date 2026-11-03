---
name: backend-review
description: Review backend code (a PR, a branch or a local diff) against the same standards used to write it - the generic rules of the backend-implementation skill plus the project's own coding-standards and style docs (pointed to by its root CLAUDE.md / AGENTS.md). Checks layering (business logic in models, providers only access data), contracts, upserts, validation, errors, logging, security, tests, and naming/style (scenario and test names, method descriptions, response fields, schema names). Use when asked to review backend code or a backend PR, alone or alongside pr-review. Read-only - never posts unless asked.
---

# backend-review — review backend code against the house standards

Generic and reusable: no company or project data lives here. The rules come from two places, read every time:
1. `backend-implementation` skill (`../backend-implementation/SKILL.md`): the generic rules, §1–§10.
2. The project's standards: follow the root `CLAUDE.md` / `AGENTS.md` (workspace and repo) to its coding-standards, style and review docs (typically `docs/coding-standards*.md`, a `--review` doc per repo) and any project-local review skill (e.g. a migration checklist).

Order of authority: repo `CLAUDE.md` → project docs → generic rules. A finding cites the rule it breaks (doc path + section, or skill §).

## Step 1 — scope
- Get the diff against the base (`git diff <base>...<head>`), the PR description and existing review threads. Read the changed files whole, plus the callers and sibling modules they touch (same layer, same domain).
- Note the component type (service, composite, worker, API, webhook…) from the project docs: it decides which rules apply.

## Step 2 — check, in this order
1. **Contract and behaviour:** request/response schemas, breaking changes (stricter schema, renamed field, removed field) and whether every caller was checked; edge cases aligned with sibling methods (empty input, not found, duplicates).
2. **Layering:** no query in a handler; no read-then-write in a model (full-entity upsert = one `ON CONFLICT` statement; replica lag and parallel calls); providers run one query with no `if`/`throw`/maps/second query/`getOrCreate`; models hold the decisions; write-time concurrency conditions stay in SQL; no cross-provider calls.
3. **Types:** storage records independent of API types; inline provider input types; references reuse the owning entity's field schema.
4. **Data rules:** upsert = full replace; a deleted model check moved into the schema; the same tie rule in the model and in SQL; internal ids and DB-managed columns not accepted from callers; optional links `.nullish()`; batches de-duplicated in the model; placeholders for parent-after-child.
5. **Errors and logging:** project error classes with cause; no double logging; no whole payloads, secrets or personal data in new log lines.
6. **Security and config:** parameterised queries, permission checks, no secrets, bounded caches.
7. **Tests:** unit tests for every model branch (dependencies mocked, calls and results asserted); no provider unit tests; functional scenarios for every behaviour change and bug fix against the real test DB; outbound HTTP mocked; affected `select *` features updated; test-table cleanup order. Flag: scenarios that only test the schema library (types, integers, required fields); failure scenarios that don't assert the error message/code or error data; scenarios already covered by a combination of others; model-only logic (dedup, normalisation) tested functionally or fed dirty fixtures.
8. **Naming and style** (backend-implementation §10 + the project's style doc): `Feature: <Verb> <object>`; `Scenario: Should <verb> <object> [when <condition>]`; `it('should …')`; method description = verb-first sentence with the guarantee; response description `Returns the <past-participle> <entities>`; response field named after the operation (`upserted<Entities>`); schema/type names; `resolve<Entity><Key>` and `get`/`insert`/`update`/`upsert…If…` provider names; cross-entity fields (uuid or external id) taken from the owning entity's schema; pure helpers under `helpers/`.
9. **Scope and readability:** no drive-by changes; no intent comments (only DB/library quirks); one job per function, matching its name; names carry meaning; PR title and description true.

## Step 3 — report
- Findings ranked: **blocking** (wrong behaviour, broken contract, layering or security), **should fix** (standards), **suggestion** / **[nit]** (style and naming). Each finding: `file:line` — what is wrong (rule cited) — **How it can fail** (a concrete input or timing, e.g. two parallel calls, a redelivery, a lagging replica, a 0 value) — **Solution proposal** (code or exact title).
- For a naming or wording fix, give a ready-to-apply suggestion block, the way reviewers do:
  ````
  ```suggestion
    Scenario: Should ignore an update when the update timestamp is older than the existing one
  ```
  ````
- Ask a question instead of asserting when the intent is unclear ("What do the other batch methods return for an empty list? Could we align?").
- Don't flag what the project docs mark as accepted, and don't re-raise points already answered in the threads.
- Read-only: don't edit code, don't post comments, don't resolve threads unless the user asks.
