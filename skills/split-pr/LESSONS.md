# split-pr — accumulated lessons (shared, cross-repo)

This file is symlinked into every project that links this config repo, so it
must only hold **generic, cross-repo** lessons — universal splitting
heuristics, script bugs and their fixes. Repo-specific judgment calls (real
package names, ticket numbers, incident narratives) belong in that project's
own `.claude/reviews/split-pr-lessons.local.md` instead — see "Capture
corrections" in `SKILL.md`.

Read this file **first** on every run (Step 0 of `SKILL.md`), alongside the
project-local file, and pass the combined text into every `split-pr-analyze`
classification agent and into the synthesis step. This is the skill's
self-improvement mechanism: it has no other memory between runs, so a lesson
not written down is a lesson the next run will not have.

Append a new dated entry per the "Capture corrections" step in `SKILL.md`
whenever a run's output turns out wrong, incomplete, or (if a split was
applied) caused a broken build. Each entry: dated, concrete, phrased as a
rule to apply next time — not a narrative of what happened. Do not delete old
entries even if they look obvious in hindsight; another run is what makes
them obvious.

> **Note on the entries below:** they were all captured before this file was
> split from the project-local lessons file, and most are tied to one
> specific project's real package names and ticket numbers (e.g. `@findfix/*`,
> `MA-207`) rather than being generic. They're left in place rather than
> deleted (per the rule above, and because they're still useful to whoever
> owns that project), but if you're linking this config repo into a
> **different** project, treat them as reference examples of the lesson
> *style* to follow, not as facts about your codebase — and prefer moving them
> to that project's own `.claude/reviews/split-pr-lessons.local.md` over time.

## 2026-09-17 — seeded from the manual MA-207 split analysis that designed this skill

- **Never trust file names or commit-message subjects for bucket assignment
  without checking real imports.** The MA-207 branch's own author proposed
  "Kafka setup → Kafka flow → refactor" as the PR order. The actual imports
  (`packages/pipeline/src/activities.ts` importing `emitLibraryScript`/
  `formatScript` from `@findfix/remediation`) proved the refactor has to land
  *before* the Kafka-flow PR, not after — the human's own mental model of the
  split was backwards. Always run `import_graph.sh` and trust its edges over
  a proposed ordering, a commit subject, or a directory name.

- **Files that commonly bundle hunks from 3+ unrelated concerns in this
  repo**: `packages/core/src/env.ts`, `.env.example`, `docs/DEPLOY.md`,
  `docs/ARCHITECTURE.md`, `docker-compose.yml`, `README.md`,
  `vitest.config.ts`, `scripts/a11y-gate.sh`, `docker/worker.Dockerfile`, and
  any file named `orchestrator.ts`. Always classify these at the hunk level;
  never assign one concern label to the whole file.

- **A commit pair that reverts itself nets to zero.** Check `git log` for a
  commit immediately followed by `Revert "<that commit>"` — drop both when
  reconstructing history; don't classify their (canceled-out) content.

- **A commit message citing "ported from PR #N" or mirroring an existing
  guard on another branch is a strong signal the change is fully
  separable** — it was already independently reviewed once elsewhere. Treat
  it as its own tiny PR by default.

- **This repo's Jira ticket citations in code comments go stale** — tickets
  get reassigned/reused (see this repo's own `CLAUDE.md` warning about
  "MA-44"-style reassignment). A ticket number in a comment is not proof of
  current scope; don't use it to justify a bucket assignment without
  independently checking the diff content.

- **`docker-compose.yml`'s MockServer-based services need an external
  polling shim** (e.g. `wait-for-telemetry-plan`) because MockServer's
  distroless image has no shell for an in-container healthcheck. A generic
  "simplify the compose file" pass during a manual hunk split can accidentally
  drop this — flag it explicitly if a split touches a MockServer-based
  compose service.

- **`pnpm-lock.yaml` / `pnpm-workspace.yaml` must be regenerated per split PR
  via `pnpm install`, never hand-edited or split by hunk** — the lockfile's
  shape depends on the full dependency graph at that PR's tip, not just the
  lines that look relevant to one concern.

- **A `package.json` `workspace:*` dependency addition and its matching
  `tsconfig.json` `references` entry must travel in the same PR** — a split
  that adds one without the other passes `pnpm install` but breaks `tsc -b`
  silently until someone runs a full build. `import_graph.sh`'s
  `reference_mismatches` field checks this automatically. During the run
  that seeded this file, it surfaced a real, pre-existing gap unrelated to
  the split itself: `packages/pipeline/tsconfig.json` was missing
  `references` entries for `a11y-runtime`, `a11y-tests`,
  `playwright-runner`, and `remediation` despite `package.json` already
  depending on all four. Report a non-empty `reference_mismatches` to the
  user as a standalone finding even when it isn't blocking the split itself.

- **`tsconfig.json` in this repo is JSONC** (allows `//` line comments and,
  in some files, trailing commas) — a strict `json.loads` on the raw file
  throws. `import_graph.sh` strips comments/trailing commas before parsing;
  if you're reading a `tsconfig.json` by hand, don't assume a JSON parse
  failure means the file is broken.

## 2026-09-17 — two `import_graph.sh` blind spots found and fixed during the real MA-207 run

- **A package that only re-exports a symbol (`export { X } from '@findfix/pkg'`)
  creates the same build-ordering dependency as importing it, but the old
  regex only matched the `import` keyword.** Found live: `git-ops/src/
  outputRepoContract.ts` re-exports `runSafetyLint`/`SafetyLintViolation`
  from `@findfix/core`'s new `scriptSafety.ts` — invisible to `edges` until
  fixed. **Fixed in the script** (`import_graph.sh` now matches `import|export`
  for cross-package edges) — this bullet is a record of why, not a manual
  check to keep repeating.

- **Two files in the SAME `@findfix/*` package can still have a hard
  ordering constraint via a plain relative import (`./x.js`, `../x.js`),
  because this repo builds each package as one `tsc -b` unit.** A
  cross-package-only edge list will miss this and mis-sort a same-package
  file-level split. Found live: `packages/pipeline/src/kafka/workflowClient.ts`
  does `import { FindFixWorkflow, type FindFixWorkflowInput } from
  '../workflows.js'` — a real VALUE import — which meant 3 files the manual
  hint had bucketed under "Kafka setup" (`kafka/workflowClient.ts`,
  `kafka/startEventProcessor.ts` transitively, `consumerMain.ts`
  transitively) actually belong with "Kafka flow" (`workflows.ts`) instead.
  **Fixed in the script**: `import_graph.sh` now emits a separate
  `intra_package_edges` array (file, target_file, package, specifiers,
  `value_import`) for relative imports between two files that are BOTH
  changed in the diff and in the same package. Read this field, not just
  `edges`, before bucketing files within one package into different PRs —
  a same-package split is exactly the case this field exists for.

- **Cherry-picking a dependency's commit only brings that ONE commit's diff — not its own ancestors.** Building PR-13 by cherry-picking PR-12's single commit onto PR-8's tip silently dropped PR-1 (which PR-12 itself depends on and was built on top of), since cherry-pick doesn't replay history, only a diff. The build failed with `TS2305` for symbols `PR-1` adds. **When stacking branch B onto branch A via cherry-pick (rather than branching directly from A's tip), you must cherry-pick A's *entire* commit chain back to the common base, not just A's own newest commit** — or branch from A's tip directly and cherry-pick only the *other* prerequisite's commit on top, whichever is fewer cherry-picks. Always re-verify with a real build after any cherry-pick chain, exactly as this run's own practice already does — this is a reminder of why that step is non-negotiable, not a new rule.

- **A same-shape global type/interface declared independently in two packages is a reverse-dependency hazard too, and it's invisible until both packages are actually compiled together.** `packages/engine/src/library.ts` (old, undeleted without PR-9) and `packages/a11y-runtime/src/library.ts` (new, from PR-3) both augment the global `Window` interface with `__FF_LIB__`, with different shapes. Neither file alone has an error; the conflict (`TS2717`/`TS2741`) only appears once a single `tsc -b` project-reference graph includes both — which happened here because PR-13's tsconfig fix (adding the missing `a11y-runtime` reference) pulled a11y-runtime's declaration into the same graph as engine's still-present old one. **When two packages that formerly had independent implementations of "the same idea" are being consolidated (one deletes and defers to the other), check for shared global/ambient type declarations specifically** — module-scoped exports collide loudly (`TS2305` on the missing side), but global augmentations collide quietly and only when something else (like a tsconfig reference fix) brings them into the same compilation unit.

- **Commit AFTER `pnpm install`, never before, for any branch whose `package.json` changes.** Committing first and running `pnpm install` only later (for verification) leaves the regenerated `pnpm-lock.yaml` sitting uncommitted in the worktree — the build/test verification still passes (it reads from the already-populated `node_modules`, not from git), which hides the gap. Caught only by explicitly diffing `pnpm-lock.yaml` after the fact across 6 branches in one run (PR-6, PR-7, PR-8, PR-9, PR-11, PR-12) and pushing a follow-up `chore: regenerate pnpm-lock.yaml` commit to each. Reorder the "Applying the split" steps in practice: stage files → `pnpm install` → review the lockfile diff → commit everything together, not commit → verify → notice the lockfile gap.

- **A shared validation/lint rule getting STRICTER (not just a deleted export) is the same reverse-dependency hazard, and it shows up as a test failure, not a build error.** `packages/git-ops` re-exporting `runSafetyLint` from `@findfix/core` (instead of its own older, looser local rule table) made `packages/remediation/src/descriptors/emit.test.ts` (only deleted by a *different* PR in the same atomic group) fail — the new shared rule set includes a `no-dom-structure-mutation` check the old rule table didn't have, and it correctly flags the old applier-era script format's legitimate DOM operations as violations. **Running `pnpm build`/`pnpm typecheck` alone is not enough to verify "no compile break" claims — always run the full test suite too**, on a genuinely isolated branch, before asserting any concern is independently landable. Add this to the same "atomic group" as any concern whose deleted/changed code the new rule would have applied to.

- **Both blind spots above were only caught because a classification agent
  read real source instead of trusting the deterministic tool's silence.**
  `import_graph.sh` is still not exhaustive — it does regex matching, not a
  real TS resolver, so it will miss: dynamic `import()`, re-exports via a
  barrel that itself re-exports another barrel (multi-hop), and any
  ordering constraint expressed as a *shared string convention* rather than
  a code import (e.g. this diff's `workflowId` template format duplicated,
  with no import between them, across `packages/api/src/server.ts` and
  `packages/pipeline/src/kafka/startEventProcessor.ts`). Keep telling
  classification agents to verify by reading the actual diff, not just by
  trusting an empty result from the script.

## 2026-09-17 — Step 7 adversarial critique caught 14 issues on the first real synthesis (MA-207 plan) — patterns to check up front next time

Three fresh critics (DAG validity, hunk-bundling completeness, convention/standalone-findings accuracy) found real, evidence-backed problems in the synthesized plan that the classification agents' own reports had already correctly surfaced data for — the mistakes were made during synthesis, not classification. Generalized:

- **A non-`src` directory inside an otherwise-fully-assigned package is easy to drop entirely.** `packages/pipeline/scratch/{activities.ts,run.ts,workflows.ts}` had real, substantive diff content (confirmed via the classification agent's own report) but never made it into any PR's file list during synthesis — "entire package diff" silently meant "entire `src/`". When a classification report's `hunks` list includes a path outside the package's normal source root, double-check it actually landed in a Tracks-table Contents cell before finalizing.

- **A cross-file "depended on by" claim must be traced to a literal you can point at, not inferred from matching domain vocabulary.** The synthesis claimed `tests/e2e/temporal.findfix-workflow.test.ts`'s `domSnippet` depended on an `accordion.html` class-name rename in the same diff — both are "about accordions," but the test's `domSnippet` was a hardcoded string, not derived from the fixture file at all. Before writing "X depends on Y" in a plan, grep for the actual identifier/string in X's diff and confirm it traces to Y, don't infer it from both files touching the same feature.

- **When a hunk bundles a small independent one-line change with a larger dependent rewrite, the small change is NOT cleanly separable** — the whole hunk travels with the larger concern. A `taskQueue: 'findfix'` → `'findfix.tq-workflow'` rename living in the same hunk as a full test-behavior rewrite (new args shape, new assertion) cannot be cherry-picked alone; only a *second, isolated* occurrence of the same rename elsewhere was actually independent. Check hunk boundaries, not just "this string changed," before assigning a small-looking edit to its own PR.

- **A "PR touches env.ts, therefore needs `.env.example` + `docs/DEPLOY.md`" pairing must be verified per-PR, not assumed uniformly.** One of this diff's three env.ts sub-changes was a code-comment-only rename with an `.env.example` comment counterpart but *no* `docs/DEPLOY.md` content at all — asserting the full 3-file pairing for it was wrong. Check what content actually exists in each paired file before claiming the pairing, don't apply the lockstep rule as a blanket assumption.

- **A doc/comment hunk's PR assignment should follow what it describes, not what package/file it physically lives in.** `packages/core/src/canonical.ts`'s comment removal documented `@findfix/remediation`'s behavior change, not anything in `core/scriptSafety.ts` — it was mis-bucketed into the same PR as an unrelated core file just because both are in `packages/core`. **This recurred a second time in the same run, during apply**: `packages/core/src/env.ts`'s and `.env.example`'s "`authorFixDescriptors`→`authorLibraryFix`" comment hunks were also bucketed with `core/scriptSafety.ts` (PR-2) purely by file location, when they actually document `@findfix/agents`' method rename (PR-5) and have nothing to do with scriptSafety. Two occurrences in one run means this isn't a one-off — **explicitly re-check every comment-only hunk's actual subject against the PR it's assigned to as its own synthesis step**, don't rely on catching it only via Step 7 critique or apply-time review. **A third occurrence surfaced while actually building PR-4**: `docs/ARCHITECTURE.md`'s "Input (phase 2 — audit, HTTP)" bullet relabel was bucketed as pure ticket-bookkeeping, but its body text says "not touched by the Kafka path below" — a direct forward-reference to a bullet that doesn't exist without the Kafka-setup PR. **Test for this concretely**: try mentally (or literally) deleting every OTHER concern's neighboring hunks and re-reading the sentence in isolation — if it now reads as broken, dangling, or referencing something no longer present, that hunk doesn't belong to the concern it was assigned to. Don't judge by whether the change "sounds like" a citation fix.

- **A "no file overlap" or "duplicate rule lives in file X" claim about a grab-bag or cross-package pairing needs a literal grep check, not a plausibility check.** Two sub-items in one PR's grab-bag actually shared a file (different hunks, so not a hard conflict, but the "zero overlap" claim was still false); a separately-claimed "duplicate safety rule" pointed at the wrong package's file (the rule lived in `core/scriptSafety.ts`, not the file the plan named). Grep for the specific pattern/filename before asserting either kind of claim.

- **A hand-written "parallel tracks" quick-reference line summarizing a large Tracks table can silently drop an entry** (PR-11 was missing from it here) — regenerate that summary mechanically from the table's own "Depends on" column rather than re-typing it from memory.

- **Always explicitly state the outcome of the self-reverting-commit-pair check in the plan itself, even when it's a non-event** — LESSONS.md already said to check for this, but the check's result wasn't visible anywhere in the written plan, which is itself a due-diligence gap even though the two-ref diff already nets it to zero automatically.

## 2026-09-17 — CRITICAL: a "no compile break" claim in the plan was never actually built, and was wrong

While applying PR-3 (a11y-runtime library API) as its own standalone branch off `develop`, `pnpm build` (`tsc -b`) failed with real `TS2305` errors in 9 files across 3 *other* packages (`agents/src/authoredFix.ts`, `remediation/src/descriptors/*.ts`, `a11y-tests/src/catalog/{run,types}.ts` + `fix/ledgerInputs.ts`) — all still-`develop`-era code importing symbols (`FixDescriptor`, `FixOperation`, `ConflictPolicy`, `FixFamily`, `LedgerResult`) that PR-3 deletes from `a11y-runtime`. The plan's Risk section had explicitly asserted "no compile break" for this exact scenario — an assertion based on checking *forward* imports (what a11y-tests' new code imports) but never checking *reverse* dependencies (what still-unmigrated code elsewhere in the repo imports from the symbols being deleted). Three adversarial critics and the classification agents all missed this too.

- **Every "no compile break" or "safe to land alone" claim about a PR that DELETES an exported symbol must be verified by actually running `pnpm build` with ONLY that PR's changes applied on top of the base branch — not asserted from reading imports.** Reading the diff's own changed files is not enough; a deleted export can break code the diff never touches.
- **`import_graph.sh` only analyzes forward imports among CHANGED files — it has no concept of "this diff deletes an export that unchanged files elsewhere in the repo still import."** This is a real, structural blind spot (distinct from the re-export/intra-package ones already fixed) worth a script enhancement: for any package with deleted exports in this diff, grep the *whole repository* (not just changed files) for remaining imports of those names from packages outside this diff's own concern set, and report them as `reverse_dependency_breaks`.
- **When a plan's Risk/Verdict claims two concerns are only "conceptually" coupled (safe to land with a gap between them), treat that as a hypothesis to verify by building, not a conclusion** — the language "no compile break" is exactly the kind of confident-sounding claim that needs a build to back it up, especially for any package doing a wholesale delete-and-replace of its public vocabulary (descriptor/ledger-style refactors are exactly this pattern in this repo).

## 2026-09-17 — a plan file's "Application status" header can go stale within the same day, in a multi-session repo

The MA-207 plan file's header claimed "ALL 15 PRs COMPLETE ... pushed to origin." Hours later (same day), the actual apply that happened used a completely different, coarser 3-PR consolidation (`pr1-foundation-library-refactor` / `pr2-pipeline-consumers` / `pr3-api-docs-integration`, opened as real Bitbucket PRs #57–59) — a direct and correct consequence of this file's own Risk #2 (atomic-group collapse under project-wide `tsc -b`), but nobody updated the doc to say so. This surfaced only because a *different* session, invoked fresh on `/split-pr` for the same branch, found the doc's claimed branch names didn't exist on `origin` at all.

- **Never trust a plan file's "Application status" / "COMPLETE" header at face value — verify against live `origin` branches (`git branch -r`) and, if credentials allow, live Bitbucket/SonarQube API state before either building on it or reporting it to the user.** A plan doc is a snapshot of intent at write-time; the actual apply (especially in a repo with concurrent Claude Code sessions — see this repo's own note about that) can diverge from it without the doc ever being corrected.
- **If a repo has multiple concurrent Claude Code sessions on the same working directory, check `ListAgents` and ask a peer session before assuming you understand who applied what** — but treat the peer's answer as one more input to verify, not as ground truth; in this case the peer session had no memory of doing the apply either, and the real answer came from checking `git branch -r` / the Bitbucket API directly, not from any session's recollection.
- **A 15-way (or N-way) plan getting consolidated down to 3 real PRs during apply is not a failure of the analysis — it's what Risk #2-style atomic-group findings are supposed to produce.** Don't treat a smaller-than-planned final PR count as a sign something went wrong; verify it against the DAG reasoning instead (does the consolidation respect every dependency edge the plan found?).
