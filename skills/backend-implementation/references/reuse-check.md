# Reuse check: answer these questions before you add code

Run it before you write any new method or endpoint, model, provider or repository, client call, helper, constant or job. Write every answer in the plan. A "none" names what you searched. Reviewers ask "why not the existing X?" when a new function duplicates one that is already there; this check answers that before the code exists.

## 1. Get the map of what exists

1. Look for a **code map** in the project docs (the root `CLAUDE.md` / `AGENTS.md` points to it). A code map is a generated list of every exported function per layer and domain, with its parameters and the number of files that import it. When the commit it was built from is behind the default branch, regenerate it, then search it.
2. **No map:** propose generating one: parse the source tree of the default branch (not the local checkout), list each layer's exported functions with their first parameter's fields and their importer count, and write chunks the docs index can link. Until it exists, list the layer folders and grep them: `git grep -nE "export (async )?function|export const \w+ = (async )?\(" -- <layer dir>`, plus the table, column, endpoint and event names the change touches. Say in the plan which of the two you used.

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
