# Pre-PR self-review checklist (grouped by the kind of feedback reviewers give)

Generic. Run it before opening a PR and after every push; `backend-review` uses the same groups. Each line is a question; a "no" is a finding. The project's docs add concrete forms per group.

## 1. Architecture and layering
- Business decisions in models, providers run one query against one resource, handlers stay thin?
- No read-then-write in a model; a full-entity upsert is one `ON CONFLICT` statement?
- With a read/write split (replicas), does every read that decides a write, or follows a write in the same request, use the primary?
- Each component does only what its type may do (owns data / orchestrates / consumes / adapts)?

## 2. Contracts and API design
- Request and response schemas built from the entity schema; cross-entity fields reuse the owning entity's field schema?
- Breaking or stricter change (partial → full, optional → required, removed/renamed field) identified, every caller checked, release order stated?
- Edge cases (empty input, not found, duplicates) behave like the sibling methods?
- Response field and description named after the operation (`upserted<Entities>`, `Returns the upserted <entities>`)?

## 3. Data validity and consistency
- Business value ranges encoded in the schema (positive amounts, non-empty names, max lengths)? A deleted model check moved into the schema?
- Ordering keys: their precision known (e.g. timestamps truncated to milliseconds), ties defined, and the same tie rule used in the model and in SQL?
- Late, duplicated and redelivered messages handled idempotently?

## 4. Tests (see the `test-design` skill)
- Each test proves one unique behaviour at the lowest level; no duplicates, no implied tests, no schema-library tests?
- Failure tests assert the reason (error code/message/fields) and nothing unrelated?
- Model-only logic proven by unit tests; functional fixtures clean?

## 5. Naming
- Scenario titles: `Should <verb> <object> when <condition as the caller sees it>`, naming the asserted fields, "stored" not "existing"?
- Unit tests: `should <exact outcome> when <collaborator/condition>`, no "fail"/"wrap"/"handle"?
- Function names state everything the function does; provider/model/handler names follow the project's forms?

## 6. Code organisation and readability
- One job per function; pure helpers with their own tests in `helpers/`, trivial single-use logic inline?
- No comments for intent or restating code; only DB/library quirks?
- Touched types and signatures brought up to the standards; untouched code left alone; dead code from the change removed?

## 7. Errors and logging
- Project error classes with `cause`; static messages; one log per failure?
- The logger's error key actually serialises the error (stack, cause)? If the lint rule and the logger disagree, follow lint and raise it centrally?
- No secrets or personal data in new log lines?

## 8. PR and review process
- PR description re-read against the code after every push (defaults for missing fields, test counts, release order)?
- Every review thread answered; "done" only for pushed code ("in the next push" otherwise)?
- When two reviewers disagree, the choice follows the more specific/newest convention, and both threads say what was done and why?
