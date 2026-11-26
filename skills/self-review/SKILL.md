---
name: self-review
description: Double-check one change for over-engineering and duplication in its design, its implementation and its tests, simplify it, and prove nothing was lost. Loads the project's own rules first (root CLAUDE.md / AGENTS.md, the reviewer, pre-push and per-PR lesson docs they route to, the plan's acceptance criteria), then compares the change with the simplest design that meets them, scans the whole repository for code, types, constants and text the change could reuse or copied, inventories where each behaviour is implemented and proven, removes repeated validation layers, single-use files, wrappers, types and helpers, tests repeated across levels, tests of a fake, a library or a generated artifact, tests that cannot fail and duplicated fixtures; simplifies code first and shows the unchanged tests still pass, then trims tests, checks every kept rule test by removing the rule once, separates pre-existing flaky failures from new ones without touching the working tree, and ends with a per-file What / Why / How / Calls table and a flow diagram of the change. Use before pushing, after finishing a feature, or when asked to "double check", "simplify", "remove duplicates", "is this over-engineered", "keep it simple" or "do we need these tests". Any stack. Generic - the rules live in test-design and backend-implementation §11; this skill is the procedure. Edits the working tree only; never commits, pushes or posts unless asked. Usage: /self-review [<base-ref> | <commit>]
---

# self-review — simplest design, reused code, each behaviour proven once

Generic: no project data lives here. The rules come from `test-design` (tests) and `backend-implementation` §11 (code); this skill says how to apply them to one change and how to prove the result. The project's own rules come first and win where they ask for more.

## Step 0 — load the project's rules
1. Read the root `CLAUDE.md` / `AGENTS.md` and every doc it routes "write / review code" to: code standard, test rules, pre-push list, size caps, reviewer profiles and the per-PR review-lesson files of this repo. Read the plan or ticket of the change: acceptance criteria and the deviations it already justified.
2. Note the rules that decide what must stay even if it looks repeated (an acceptance criterion proven end to end, a refusal the reviewer asked to see at app level, a security property) and the caps every file must keep.

## Step 1 — scope and baseline
1. Scope: `git diff <base>...HEAD` plus the working tree and untracked files (base = the PR's destination; one commit = `<commit>~1..<commit>`). List the changed source files, test files and docs.
2. Baseline: run the project's checks and the full test suite and note the counts. Never stash or check out over uncommitted work: export the base with `git archive <base> | tar -x -C <empty temp dir>`, link the dependency folder (`node_modules`, a virtualenv) and generate what the build generates there. For a flaky suite, interleave runs of both trees under the same load and compare failure rates before blaming the change.

## Step 2 — design check against the simplest version
Write the simplest design that meets the acceptance criteria with what the repo already has, then compare:
- New layers, wrappers or parse helpers over a function the repo already has (a `parseX` that returns the same error the existing validation helper already sends).
- New files, types, exports and parameters: count them; each needs an importer outside its file and tests, and a reason the simplest design lacked it.
- Compile-time or runtime guards the call sites already enforce (a `satisfies` check every caller's types already prove), objects built only to pass a subset the callee already reads from the full value.
- A rule placed in the layer that does not own it (contract rules in an HTTP file, a vocabulary in a repository).

## Step 3 — repo-wide reuse scan
For every new type, constant, helper, error value, regex, message and doc sentence in the diff, search the whole repository (`git grep -nF '<literal>'`, `git grep -n '<name>\|<body fragment>'`), not only the diff:
- A type equal to an existing one (`Pick<X, …>` naming every member of `X` is `X`).
- A constant, doc string or response block copied from an untouched file: move it to one shared place and import it in both. The copy is the change's, so the move is in scope.
- A test value copied from config or env defaults: read it from the test env.
- Duplicates that existed before the change go to the report, not the diff.

## Step 4 — inventory and the extra
Build one table: `behaviour → where it is implemented (each layer) → which tests prove it (each level)`, with every input rule, value format and error mapping. Each acceptance criterion keeps at least one proof at the level the plan or the project's rules require.
Code (`backend-implementation` §11): one rule enforced in several places (keep the edge); single-use files, wrappers, types and helpers; values returned twice; options, dependencies or exports nothing uses; exports only for tests.
Tests (`test-design`):
- One format asserted in several files: keep the exact shape at the level that owns it; elsewhere assert which value was used (a call with the builder's output, a count).
- An outer level repeating every outcome of an inner unit: keep one test per outcome kind the outer layer maps, plus what the project's rules require there.
- Tests of a library, framework, generated artifact (a document generated from the runtime schema) or global handler already tested elsewhere; tests on top of a fake that vary a rule the real store enforces; pass-through tests a higher test already proves.
- "Still works after X" tests no path in X could break; negative tests that fail for any implementation; duplicated fixtures and single-use test helpers.
Decide each finding: remove, merge, move, strengthen, or keep with the reason (acceptance criterion, security property, project rule).

## Step 5 — simplify, code first
1. Change the implementation, then run the unchanged tests: every behaviour test still passes, only tests of a removed guard fail. That run proves behaviour is preserved.
2. Then remove or merge the tests the inventory marked and strengthen weak negative tests.

## Step 6 — verify
1. For every kept rule (each guard, each order, each mapping, each limit): break it once, see a named test fail, restore it. Keep the mutation table; a rule no test catches gets a stronger test.
2. Run the full checks (typecheck, lint, format, build, unit and integration suites, the database suite) and compare failures with the Step 1 baseline.
3. Check every file against the project's size caps.

## Step 7 — report
- `finding → action → why`, naming for each removed test the test that still proves its behaviour;
- files, lines and test counts before and after, the mutation table, the check results, pre-existing flakiness with both failure rates;
- what was kept on purpose and why, duplicates outside the change, and open design questions;
- each finding a project rule should have prevented, as a proposed line for the project's reviewer or pre-push docs (added only when the user agrees);
- **the change explained, last:** one row per changed file (source, tests, config; reused code that the change calls but does not edit gets its own row marked "reused, unchanged"), columns `File | What changed | Why | How it works | Calls / called by`, at most four short sentences per cell, the tests row naming which rule each test proves;
- **a flow diagram** of the whole change at work, from the trigger (request, job, event) through each layer to the stores and third parties it touches, with the decision points, what is skipped, and what is written where. Use a plain-text block (boxes and arrows) unless the reader asked for a rendered format.

Nothing is committed, pushed or posted unless the user asks.
