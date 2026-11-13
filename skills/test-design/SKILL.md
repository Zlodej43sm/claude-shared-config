---
name: test-design
description: Rules for writing and reviewing tests in any language or stack (backend, frontend, infrastructure/DevOps, scripts, data pipelines) so every test is unique and necessary - no duplicates, no tests implied by other tests, no tests of what a library, framework or tool already guarantees, each behaviour proven once at the lowest level that can prove it, and every new test or scenario named in the form the tests around it already use (should-form only when there is none). Use whenever you add, change, plan or review tests, and before finishing any implementation that touches tests. Generic - project test conventions come from the project's own docs.
---

# test-design — every test unique, every test needed

Generic and reusable: no project data lives here. Read the project's test conventions first (root `CLAUDE.md` / `AGENTS.md` and the docs it points to); they decide tools, folders and naming. This skill decides **which** tests exist.

## The rule

A test exists only if it proves a behaviour that **no other test proves** and that **no tool already guarantees**. Identify each test by the triple *(subject, condition, expected outcome)*; two tests with the same triple — at any level, in any language — are duplicates.

## Step 1 — inventory before writing
1. Find the existing tests for the code you touch (search by subject name, method, route, resource, module) at every level: unit, integration/functional, contract, end-to-end, infrastructure checks.
2. Write down what each one proves as triples. This is the coverage map.
3. For each new behaviour, check the map. Add a test only for a triple that is missing.

## Step 2 — what not to test
- **Library, framework, language and tool guarantees:** schema/type validation (types, required fields, enums, formats, integer checks) at any entry point — service methods, API and webhook routes (an invalid payload only to get the framework's 400), message consumers, job arguments — ORM or query-builder mechanics, framework routing or serialisation, cloud/provider APIs, container or orchestrator schemas, template syntax, what the compiler, type checker, linter, formatter, `validate`/`plan` step or CI policy check already enforces.
- **Implied behaviour:** a case that a combination of existing tests already proves (A proves "link new", B proves "move existing" ⇒ "link existing" is covered).
- **The same behaviour at two levels:** prove it once, at the **lowest level that can prove it**:
  - pure logic, branching, mapping, normalisation, de-duplication, sorting → unit;
  - queries, persistence, concurrency conditions in the database, wiring between layers, real serialisation → integration/functional;
  - agreements between services → contract tests;
  - only critical user journeys → end-to-end;
  - infrastructure: configuration rules → static/policy checks; behaviour of a deployed resource → one smoke check per deploy path.
  A higher-level test is justified only when it adds something the lower one can't (a real database, real wiring, the real contract) — and then it asserts that addition, not the lower-level logic again.
- **Copies with different data:** variants of the same behaviour are one parameterised test (table/each/outline), not N copies.
- **Implementation details:** private helpers already exercised through their caller's tests, call order that isn't part of the contract, log lines, snapshot dumps of large objects.
- **Other components' rules:** another service's input validation (mock its error only if your code reacts to it in a specific way), the validity of generated API documentation (the tooling owns it).

## Step 3 — shape of each test
- One behaviour per test; its name states subject, condition and outcome.
- **A new name copies the naming form of the tests around it.** Before you write or rename a test, read the titles already in that file (feature-file scenarios, `describe`/`it`/`test` titles) and copy their form: opening words, tense, subject, how the outcome and condition are phrased. A feature file whose scenarios read `<Subject> is not allowed when …` gets `<Subject> is not allowed when <new condition>`, not `Should reject …`; a unit file of `returns <CODE> when …` gets `returns <OTHER_CODE> when …`, not `should return …`.
  - A new file copies its sibling files (same folder, then same module), then the form most of the repo uses (tally the first word of the existing titles).
  - Only when there is nothing to copy does the default apply: the project's naming doc, else `should <outcome> [when <condition>]` (`Should …` in scenario titles).
  - The file's form wins over the project's default form, and the default never justifies renaming untouched tests (a drive-by change). A test whose assertion you change keeps the file's form.
- Fixtures are minimal and clean: only the data the behaviour needs, already in normalised form unless normalisation is the behaviour.
- A failure test asserts **why** it failed (error type/code/message or the invalid fields), not just "failed"; no unrelated side-effect checks after it.
- Assertions check the observable outcome of that behaviour; don't re-assert what a sibling test already asserts.
- Mocked collaborator responses carry realistic values (what the collaborator really returns), not empty placeholders.
- When one entry point handles several event types, each type gets its own test, so the test list shows which events it answers.
- **Paths a stub can't prove get one check on the real artifact.** When a behaviour depends on the real runtime (signal delivery through the init process, the real migration or build tool, a real lock or timeout, the files in the built image), the lowest level that can prove it is the real artifact. Walk the ticket's acceptance criteria and every path of the code (success, failure, disabled by flag, stopped mid-run, contended, restarted): each gets one automated check there, or the PR says why not. A stubbed unit test, a manual run or a doc paragraph is not that proof.
- **Force rare paths deterministically:** hold the lock, inject the failing input or bad URL, stop at a known point. Don't rely on timing or data size to reach a timeout or a race.
- **Every wait has a deadline and slack:** each poll or `until` loop in a test or CI script gives up after a bounded time with a message naming what it waited for; a forced timeout leaves seconds of margin (hold a lock well past the timeout), not a near race.
- **Overlapping conditions:** where two events can overlap (a stop signal and a failure, a timeout and a retry), state the expected outcome (exit code, final state) and test it.
- **Sibling instances get the same assertions:** a check made on one instance (exit code after stop, state after restart) is made on the others in the same test.
- **A guard check runs today and is tight:** a test that enforces a repo rule (file shape, naming, migration format) does not skip until matching files exist. Put the check in a function and test it on sample inputs: one that passes, one that fails, and the edge a loose pattern gets wrong (the keyword in a comment, on the wrong line). Anchor the pattern where the rule says (first and last statement).
- Time-dependent logic runs on a fixed clock (fake timers restored after each test, or the project's fixed-clock test step), never on the real date, so the test does not change result when the calendar passes the boundary.

## Step 4 — clean up what you touch
- In files you change, delete or merge tests that duplicate each other or test library guarantees; say so in the PR (the "Tests" line: added / removed / why).
- Don't add a test only to raise coverage; coverage follows unique behaviours.
- Tests remove what they create (temp dirs and files, containers, networks, rows) in `afterEach` / `after-script`, also when they fail.
- In a file you changed substantively, remove pre-existing tests of library guarantees too. In a file you touched only for fixtures or mocks, leave them and list them in the PR (or a ticket) for a follow-up, so the PR stays on topic.

## Step 5 — self-check before finishing
Produce (in the plan, PR or review) a table: `test → triple proven → why no other test or tool covers it`. Any row you can't fill is removed. In a review, report each duplicate as should-fix with the test that already covers it.
