# Pre-PR self-review checklist (grouped by the kind of feedback reviewers give)

Generic. Run it before opening a PR and after every push; `backend-review` uses the same groups. Each line is a question; a "no" is a finding. The project's docs add concrete forms per group.

## 1. Architecture and layering
- Business decisions in models, providers run one query against one resource, handlers stay thin?
- No read-then-write in a model; a full-entity upsert is one `ON CONFLICT` statement?
- With a read/write split (replicas), does every read that decides a write, or follows a write in the same request, use the primary?
- Each component does only what its type may do (owns data / orchestrates / consumes / adapts)?
- No one-line wrapper around an existing client call; the handler's flow not split into internal helpers with return-value protocols?
- A new provider or model wrapper on a table that already has one: could the existing `get…` take an optional filter, or the existing `update…` take partial changes, instead?
- A model that needs raw rows reads the providers, not another model's API response (no `Date` → string → `Date` round trip, no second query to recover a value the first model hid)? Queries counted on every path, the fewest kept?
- A security/fraud/eligibility rule enforced by the operation that performs the action (not only a preflight `can…` method), through one shared function, on every entry point that reaches it? Fails closed when its input is missing, and a caller handles "not found" itself rather than forwarding `undefined`?

## 2. Contracts and API design
- Request and response schemas built from the entity schema; cross-entity fields reuse the owning entity's field schema?
- Breaking or stricter change (partial → full, optional → required, removed/renamed field) identified, every caller checked, release order stated? "Caller sends every field" verified by compiling each caller against the new types (a field covered only by a schema default still breaks the caller's types when request types are the schema's output)? The caller compiled against the published package version, not a local build of the provider's branch (the base may have moved and changed transitive pins)?
- A field the caller doesn't send yet: optional now, release order (service → caller → confirm no other caller omits it → required) in the PR, follow-up ticket linked?
- No strict validation against another service's enum unless the pins stay aligned (checking one value → compare a string)?
- Edge cases (empty input, not found, duplicates) behave like the sibling methods? A sibling that reads the same entity checks a flag or end date (`isActive`, `validTo`) this path skips: same rule applied, or the difference stated, or the question asked?
- Response field and description named after the operation, in the project's form, else the SKILL.md §10 default (`upserted<Entities>`, `Returns the upserted <entities>`)?
- Every new response field has a consumer linked in the PR? A nullable field says what `null` means?
- A field newly read from a cached or not-yet-released upstream response: missing normalised once to `null` (or the cache key changed), no `!== null` on a value that can be `undefined`?
- Public API fields named and typed like their sibling types, additive, end inclusion stated? A consumer of a period end uses the provider's boundary rule in its check and in the date it shows?
- No prerelease pin of another component left at merge; recompiled against the released version?
- User-facing sentences one translation key each (ICU `select`/`plural`), dates shown in the owning entity's time zone?

## 3. Data validity and consistency
- Business value ranges encoded in the schema (positive amounts, non-empty names, max lengths)? A deleted model check moved into the schema?
- Ordering keys: their precision known (e.g. timestamps truncated to milliseconds), ties defined, and the same tie rule used in the model and in SQL?
- Late, duplicated and redelivered messages handled idempotently?
- Time-dependent decisions (expiry, windows) taken after the cache read, on raw cached data?
- Period ends: inclusive or exclusive stated, matching the repo's existing pair, compared the same way everywhere (`<` vs `<=`), stored in a form the column's precision can't round across the boundary?
- Sync from an external source: absent key clears, malformed value keeps the stored one and is logged, missing target row logged and skipped, only changed rows written with previous and new values logged? External date strings parsed strictly (ISO 8601 with offset)?
- Schema library used only at the input boundary, with the third party's required fields from its documented model? No defensive check for a state the source's contract forbids?

## 4. Tests (see the `test-design` skill)
- Each test proves one unique behaviour at the lowest level; no duplicates, no implied tests, no schema-library tests at any entry point (methods, API and webhook routes with an invalid payload → 400, consumers)?
- Failure tests assert the reason (error code/message/fields) and nothing unrelated?
- Model-only logic proven by unit tests; functional fixtures clean? Unit tests mock the providers, not a sibling model, and assert results, not the order of `mockResolvedValueOnce` calls?
- No test of a downstream service's validation or of generated API docs? Mocked collaborator responses carry realistic values? One scenario per event type the endpoint handles?
- A date or threshold rule tested on each side of the boundary, with constants named by their side?

## 5. Naming
- Each new or renamed test and scenario title copies the form of the titles already in its file (then sibling files, then the repo's most common form)? `Should …` / `should …` only where there is nothing to copy (test-design Step 3).
- Scenario titles name the condition as the caller sees it and the asserted fields, "stored" not "existing"?
- Unit test titles name the exact outcome and the collaborator, no "fail"/"wrap"/"handle"?
- Function names state everything the function does; provider/model/handler names follow the project's forms?
- Every new column/field name grepped against the repo: same word and pair as the existing concept (`valid_from`/`valid_to`), no new synonym, same boundary semantics (exclusive end)?
- After a rename in review: the old word grepped across all stacked PRs (fields, files, functions, types, constants, log prefixes), only a third party's own keys left?
- Collection names say exactly what they hold (the filter that produced them, no "valid" on a set that keeps invalid entries)? File names short, extending an existing module's family instead of chaining qualifiers?

## 6. Code organisation and readability
- One job per function; pure helpers with their own tests where the project keeps them, else the SKILL.md §10 default (`helpers/`); trivial single-use logic inline?
- No comments for intent or restating code; only DB/library quirks?
- Touched types and signatures brought up to the standards; untouched code left alone; dead code from the change removed?
- Every extracted function or file reused, test-worthy or a named domain conversion (otherwise inlined)? Shared constants and error classes generic, not per route or per flow? No magic literals in conditions; lists and types derived from one `as const` dictionary?
- Lookup maps built only from the rows they are read with, not from merged result sets?
- A rule a sibling module already implements (expiry, eligibility window) moved to one shared helper in `helpers/` with its own test, not copied; a helper used from one place inlined?
- Exported list constants typed `readonly T[]` and copied into responses? Constant names state what the set holds (`COUNTRIES_WITHOUT_<FEATURE>`)?

## 7. Errors and logging (details: `logging.md`)
- Project error classes with `cause`; static messages; one log per failure?
- The logger's error key actually serialises the error (stack, cause)? If the lint rule and the logger disagree, follow lint and raise it centrally?
- No secrets or personal data in new log lines?
- One error path unless the caller needs two? A test-only side effect (CI trigger) never changes the response? Existing log lines kept; new ones log only the needed fields (no whole objects or payloads), and none duplicates a log the framework writes?

## 8. PR and review process
- PR description re-read against the code after every push (defaults for missing fields, test counts, release order)? It says where a new rule is not enforced and lists manual steps before the production release (third-party config with exact values)?
- Every review thread answered; "done" only for pushed code ("in the next push" otherwise)?
- When two reviewers disagree, the choice follows the more specific/newest convention, and both threads say what was done and why?
- Only the events and inputs the ticket needs? Code feeding data other teams rely on kept as is, with type gaps closed at the call site?
