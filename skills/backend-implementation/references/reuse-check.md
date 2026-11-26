# Reuse check: answer these questions before you add code

Run it before you write any new method or endpoint, model, provider or repository, client call, helper, constant or job. Write every answer in the plan. A "none" names what you searched. Reviewers ask "why not the existing X?" when a new function duplicates one that is already there; this check answers that before the code exists.

## 1. Search the code index first

1. Find the **code index** (the root `CLAUDE.md` / `AGENTS.md` points to it; in a workspace built by the `workspace-docs` skill it is `docs/code-index/`). It lists every exported function, component, class with its public methods, interface, type, enum and constant of each repo, per directory, with `file:line` and the number of files that import it, plus each repo's declared dependencies.
2. **Fresh?** `workspace_docs.py status` prints `CODE INDEX behind (N commits)` when the default branch moved; then run `workspace_docs.py code-index --repos <repo>` before you search.
3. **Search** each verb and noun of the change: `workspace_docs.py symbol <words> [--repo R] [--kind fn|class|type|const|…]` (exact names first), then open the hit at its `file:line`. Search the repos the change calls and the shared libraries too, and read `docs/code-index/<repo>/dependencies.md` before adding a library.
4. **No index:** propose one (`/workspace-docs code-index`). Until it exists, grep the default branch: `git grep -nE "export (async )?(function|class|const|type|interface|enum) " <ref> -- <layer dir>`, plus the table, column, endpoint and event names the change touches. Say in the plan which of the two you used.
5. The index describes the default branch: code on open branches is not in it, so also check the open PRs of the repo when a sibling feature is in flight.

## 2. The questions (one short answer each)

| # | Question | Typical answer that saves a new function |
|---|---|---|
| 1 | What does the change need, as verbs on resources? (read rows of T filtered by …, write …, call third-party endpoint …, run on a schedule) | the list drives questions 2–6 |
| 2 | Does an existing method or model already run the whole flow for another trigger? | A refresh, replay or backfill is usually the existing "on change" flow called with the right input |
| 3 | For each read or write: which provider already queries that table, and does it have the filter or the columns? | an optional filter on the existing provider |
| 4 | For each outbound call: which client function already wraps it? | call it; no new wrapper |
| 5 | For each rule or calculation (dates, amounts, attribute builders): which helper already computes it? | reuse or move it to a shared helper |
| 6 | For a batch job: which job already loops over the same rows or calls the same flow? | copy its options, limits, exit codes and scheduler entry |
| 7 | A near match: can it be called unchanged? If not, what is the smallest change (one optional field or filter, default behaviour kept), and who else calls it (importer count) with which tests proving the default still holds? | extend, never fork a sibling |
| 8 | What does the reused code already write (timestamps, statuses, side tables)? Can the new code use that instead of adding state or a second check? | an `updated_at` the reused flow touches becomes the "already processed" marker |
| 9 | Nothing fits: why not, one line per candidate checked? | only then a new function, named like its siblings, in the layer the rules put it |

## 3. Record the decision

Add a table to the plan: `Need | Existing candidate (path) | Decision: reuse / extend / new | Why`. Ask the user before a "new" that the answers do not justify, and propose the smallest option first (see "Smallest change first" in SKILL.md §2).

## 4. After the change

- New or changed exported symbols reach the index when the branch is merged and the index is regenerated (`refresh`, or `code-index --repos <repo>`); never edit `docs/code-index/` by hand.
- A new flow or helper that later changes should call instead of copying ("to do X, call Y") goes into the project's hand-written reuse notes (the project recipe the root `CLAUDE.md` points to), with `workspace-docs note`.
