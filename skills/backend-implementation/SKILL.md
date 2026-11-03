---
name: backend-implementation
description: Coding standards for backend services (Node.js/TypeScript and similar layered backends). Use whenever you implement, plan, fix, refactor or review backend code, prepare a PR or answer review comments. First loads the project's own coding-standards docs (pointed to by the root CLAUDE.md / AGENTS.md), then applies generic rules - layered architecture with the repository pattern (models hold business logic, providers only access data), storage records vs API contracts, upserts and batches, input validation, errors, logging, config, security, unit and functional tests, scope and PR hygiene. Database schema changes - also use a migration skill when the project has one.
---

# backend-implementation — backend coding standards

Generic and reusable: no company, product or project data lives here. Project-specific rules (component types, frameworks, error classes, logger, test tooling, naming, review lessons) live in the project's docs; this skill reads them and applies them first.

## Step 0 — load the project's standards (every time)

1. Read the root `CLAUDE.md` / `AGENTS.md` of the workspace and of the repo you change. Follow their pointer to coding standards (typically `docs/coding-standards*.md`, a conventions doc, or a project-local skill) and read those chunks.
2. Order of authority: repo `CLAUDE.md` → project coding-standards docs → this skill. When a project doc is stricter or names a concrete tool, error class or naming scheme, use it.
3. No project standards found: apply the defaults below and say so in your plan or review.
4. When unsure how something should look, copy the newest repo or module of the same kind in the project, not the older code next to your change.
5. Review lessons: a generic lesson goes here; a project-specific one goes into the project's docs.

## 1. Components and layering

- Respect the project's component types (what each may call, own and publish). Never put domain rules in a component that doesn't own the domain; one component wraps each third-party API.
- Inside a component: **handler** (thin: validate, call one model, map errors) → **model** (business logic) → **provider/repository** (data access) or **client** (outbound calls). A handler never queries; a provider never decides.
- **Provider / repository:** one query against one resource. Plain verbs over full rows: `get<Entity>(filters)`, `get<Entities>(filters)`, `insert<Entity>`, `update<Entity>`, `delete<Entity>`; name a conditional write after its condition (`upsert<Entities>IfNewer`). Not in a provider: `getOrCreate`, single-column getters, `if`/`throw` on results, de-duplication, maps, a second query, calls to other providers, caching. Parameterised queries only.
- **Concurrency exception:** a condition that must hold at write time stays in the SQL statement (`ON CONFLICT … DO UPDATE … WHERE stored < incoming`, insert-or-return-existing). The model must not replace it with read-then-write.
- **Model:** skip empty input, de-duplicate, choose insert vs update, resolve links, check existence, throw domain errors, orchestrate providers/clients, map records to API types. Inline single-use logic; a local helper only when its name states a concept.
- Pre-push check: any provider with an `if`, a `throw`, a map or a second query? Move that part to the model.

## 2. Types and contracts
- Storage record types describe columns; API contract types describe requests/responses. Keep them independent: never alias or derive one from the other. Providers take/return records; models map to API types.
- Type provider inputs inline from the record (`Pick<…>`, `Partial<…> & Pick<…, 'key'>`); don't export one-off input aliases.
- Contract changes go into the project's shared types package and are regenerated/published per its docs. Prefer `type` aliases and `as const` dictionaries over interfaces and enums unless the project says otherwise.

## 3. Entities, upserts, batches
- A concept with its own lifecycle is its own entity (type, table, methods), linked by id.
- Upserts replace the whole entity (PUT): non-partial request schema, required fields enforced by the schema, a missing optional link clears it. Callers never send internal ids: omit the internal key, accept the external one, resolve it in the model.
- Parent may arrive after child: the model reads the parent and, if missing, inserts a placeholder with only the external id; the parent's own upsert fills it.
- Batch methods only when callers send several items: array input, plural name, one statement, keys de-duplicated in the model first (same key twice: newest version wins, ties go to the later item). Empty input returns an empty result without touching the database. Otherwise single-item functions.
- Request schemas omit internal ids and database-managed columns (`updatedTs`, generated uuids); timestamps the caller owns (the source system's created/updated time) stay in the request. An optional link is `.nullish()`, so `null` and absence both clear it.
- Making a schema stricter (partial → full replace, optional → required) is a contract change: check that every caller already sends the fields, and say so in the PR with the release order.

## 4. Validation
- Validate every input at the boundary with the project's schema library, internal callers included. Build request schemas from the entity schema (omit/partial, then extend). Invalid input fails in the schema, not in the model.
- Map input to explicit fields; never spread raw input into records or queries. Cap sizes on public endpoints.

## 5. Errors and logging
- Throw only the project's base error class or its subclasses, with a code and a functional/technical classification; never bare errors or strings. One class per failure mode.
- Re-throw a caught error as is only if it is already a project error; otherwise wrap it, keeping the original as `cause`. Static messages; variable data in structured info.
- Use the project's logger, never `console.log`. Don't log the same failure twice (if the framework logs thrown errors, throw with context instead). Structured fields with the error under the project's key; no whole objects, secrets, tokens or personal data. Levels: debug, info, warn (monitored), error (must be fixed).

## 6. Config, cache, security, dependencies
- Config through the project's config system; secrets only in its secret store, never in code, config files or logs. Constants in a `constants` module; no magic values.
- Cache only where the architecture allows it; every cache has a TTL or size bound.
- Check ownership and permissions on every request, deny by default; allow-list outbound URLs and file paths built from input; no `eval` or shell commands with input.
- Ask before adding a dependency; upgrade majors one at a time, then build and run all tests.

## 7. Readability
- Names carry the meaning: intent-named functions, named booleans, variables naming the situation, response fields naming what they hold.
- No comment restating the code; a one-line comment only for a non-obvious "why". Fix root causes; `async/await`, not promise chains; no lint suppression without reason.

## 8. Tests
- **Unit:** every function with business logic, every path. Mock every dependency (spy on the module first, full module mocks last); assert calls with arguments and the return value; don't re-test callees. Providers and pure forwarding functions get no unit test. Parameterise instead of copying tests.
- **Functional:** cover methods and queries end to end against a real test database (never mocked); mock every outbound HTTP call. A scenario per functional change and per bug fix; reuse the project's shared steps.
- Plain schema validation (type, required, enum, format) needs no functional scenario; rules the schema's types can't express do. If written, name it `Should reject <what is wrong>`.
- Names follow §10.

## 10. Naming and style (reviewer-preferred forms; the project's style doc gives concrete examples)
- **Feature/functional scenarios:** `Feature: <Verb> <domain object>`; `Scenario: Should <verb> <object> [when <condition>]` in domain words, with the condition spelled out (`Should update an existing <entity> when the update timestamp is newer than the stored one`, `Should ignore an update when …older…`, `Should link a new <child> to an existing <parent>`). Invalid input: `Should reject <what is wrong>`. No vague titles, no implementation words (table, column, SQL).
- **Unit tests:** `describe('<functionName>')`; `it('should <outcome> [when|without <condition>]')`, lower-case `should` (`should return no <entities> without querying the database for an empty list`, `should wrap a provider error`). Variants with `it.each(<namedList>)`.
- **Method definitions:** description = one sentence, verb first, what + guarantee (`Upsert <entities>, ensuring older notifications don't overwrite newer data.`). Success response description = `Returns the <past-participle> <entities>`.
- **Response fields** are named after the operation: `upserted<Entities>`, `created<Entity>`, `deleted<Entities>` — not a bare `<entities>` or a synonym the API doesn't use.
- **Schemas and types:** `<entity>Schema` + `type <Entity>`; `<method>RequestSchema` / `<method>ResponseSchema` + `<Method>Request` / `<Method>Response`; batch items `<method>InputSchema` / `<Method>Input`. A field that references another entity reuses that entity's field schema (`<entity>Schema.shape.<key>.nullish()`), never a redeclared primitive.
- **Model / provider names:** find-or-create of a link in a model is `resolve<Entity><Key>`; providers use `get` / `insert` / `update` / `upsert<Entities>If<Condition>`. Entity name constants and error wrappers follow the project's existing pattern.
- **Consistency over invention:** before choosing an edge-case behaviour (empty batch, not found, duplicates), check how sibling methods behave and align (e.g. an empty batch returns an empty array, not an error). Reviewers ask "what do the other methods do?".

## 9. Scope and PRs
- Touch only what the task needs: no drive-by refactors, renames or formatting; open a ticket for unrelated issues. In code the change must touch anyway, bring the touched types and signatures up to the standards (e.g. a record aliased to an API type, an exported one-off input alias); leave untouched statements (such as an old log line) as they are. A migration PR holds only the migration; code using it ships next and names the order.
- Small PRs, one topic, draft until ready; never bypass hooks; tests included. Conventional Commit title with the scope the project uses. Keep the description true after every push.
- In review threads say "done" only for pushed code; link the guideline instead of re-arguing.
