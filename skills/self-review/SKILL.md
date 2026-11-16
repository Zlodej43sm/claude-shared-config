---
name: self-review
description: Double-check one change for over-engineering and duplication in its implementation and its tests, simplify it, and prove nothing was lost. Inventories where each behaviour is implemented and proven, removes repeated validation layers, single-use files and helpers, tests repeated across levels, tests of a fake or a library, tests that cannot fail and duplicated fixtures; simplifies code first and shows the unchanged tests still pass, then trims tests, checks every kept rule test by removing the rule once, and separates pre-existing flaky failures from new ones. Use before pushing, after finishing a feature, or when asked to "double check", "simplify", "remove duplicates", "is this over-engineered" or "do we need these tests". Any stack. Generic - the rules live in test-design and backend-implementation §11; this skill is the procedure. Edits the working tree only; never commits, pushes or posts unless asked. Usage: /self-review [<base-ref> | <commit>]
---

# self-review — simplest code, each behaviour proven once

Generic: no project data lives here. The project's conventions (root `CLAUDE.md` / `AGENTS.md` and the docs they point to) come first. The rules come from `test-design` (tests) and `backend-implementation` §11 (code); this skill says how to apply them to one change and how to prove the result.

## Step 1 — scope and baseline
1. Scope: `git diff <base>...HEAD` plus the working tree (base = the PR's destination; one commit = `<commit>~1..<commit>`). List the changed source files, test files and docs.
2. Baseline: run the project's checks and the full test suite on the untouched scope and note the counts. A failure that also happens on the baseline is pre-existing. For a flaky suite, run it several times on both versions (`git stash -u` for the baseline) and compare the failure rates before blaming the change.

## Step 2 — inventory
Build one table: `behaviour → where it is implemented (each layer) → which tests prove it (each level)`. Include every input rule (where it is enforced), every value format (where its shape is asserted) and every error mapping. If a plan or ticket lists acceptance criteria, each one keeps at least one proof at the level the plan or the project's rules require (for example a check on the real artifact).

## Step 3 — find the extra
Code (`backend-implementation` §11):
- One rule enforced in several places: an edge schema and an inner guard, or an inner guard and the library's own check (a component re-checking a key length the config schema already validated; a parser pre-checking what the primitive rejects anyway). Keep the edge, drop the rest.
- Single-use files, wrappers and helpers; a value returned twice in one result; options, dependencies or exports nothing uses; exports only for tests.
Tests (`test-design`):
- The same triple at two levels, including one format or pattern asserted in several files: keep it at the lowest level that owns the rule.
- Tests on top of a fake that vary a rule the real store or library enforces.
- Tests of library or framework guarantees.
- "Still works after X" tests where no code path in X could break it, or that run against a fake that cannot.
- Negative tests whose input fails for any implementation.
- Duplicated fixture builders and single-use test helpers.

Decide each finding: remove, merge, move, strengthen, or keep with the reason (an acceptance criterion, a security property, an explicit project rule).

## Step 4 — simplify, code first
1. Change the implementation, then run the unchanged tests. Every behaviour test still passes; only tests of a removed guard fail. That run is the proof that behaviour is preserved.
2. Then remove or merge the tests the inventory marked, and strengthen weak negative tests.
3. Stay in scope: duplicates in files the change did not touch are listed in the report, not fixed.

## Step 5 — verify
1. For every kept rule test (each negative row, each guard): remove the rule once, see that row fail, restore it. Keep the table of mutations and the rows that caught them; a rule no row catches gets a stronger test.
2. Run the full checks (typecheck, lint, format, build, unit and integration suites, the database suite when there is one) and compare any failure with the Step 1 baseline.
3. Check that no file passes the project's size caps after the moves.

## Step 6 — report
- `finding → action → why`, naming for each removed test the test that still proves its behaviour;
- lines and test counts before and after, the mutation table, the check results, and any pre-existing flakiness with its baseline rate;
- what was kept on purpose, and what is out of scope (untouched files, docs).

Nothing is committed, pushed or posted unless the user asks.
