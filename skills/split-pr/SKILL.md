---
name: split-pr
description: Analyze a large or complex pull request or branch and propose smaller, dependency-ordered pull requests. Uses the target repository's actual structure and CI configuration. Analysis only unless the user explicitly requests `--apply`. Usage: /split-pr [<pr-identifier> | <branch>] [--base=<branch>] [--apply] [--interactive]
---

# split-pr — large-PR split planner

Produces a plan for splitting an oversized PR/branch into smaller, reviewable, correctly-ordered PRs. The hard part is not listing files — it's getting the **order** right (which piece must land before which) and catching **hunks that bundle unrelated concerns into one file**. Both of those come from checking real imports and real diffs, not from file names, directory layout, or what the human proposing the split assumed. By default the synthesis step (Step 5) picks a PR count on its own; pass `--interactive` to instead negotiate that count with the user before a plan is written (Step 5.5). When actually applying a split (`--apply`), every resulting branch is a hard gate on reproducing the real CI pipeline green (Applying the split, step 5) — not just an "it should compile" guess.

## Use When

- The user asks to split, break up, or stack a large/complex PR or branch.
- A PR review (e.g. `/pr-review`) flags the diff as too large to review as one unit.

## Do Not Use When

- The user wants a normal code review of a reasonably-sized PR — use `/pr-review` or `/code-review` instead.
- The user has already agreed on a split and just wants the branches created — go straight to **Applying the split**, below, and skip the analysis if a recent plan file already covers it, **but first verify that plan file's own claimed status is still true** (see the verification note under Input's `--apply` entry) — don't skip analysis on the strength of a status header alone.

## Input

```
[<pr-identifier> | <branch>] [--base=<branch>] [--apply] [--interactive]
```

- `<pr-identifier>` — a PR number, a Bitbucket or GitHub PR URL, or a branch name. Empty → current branch (`git branch --show-current`).
- `--base=<branch>` — the branch this PR targets. If omitted: try `git symbolic-ref refs/remotes/origin/HEAD` (the repo's configured default branch); if that fails, try `develop` then `main` then `master`, in that order, using the first that exists; if none exist, ask the user.
- `--apply` — skip straight to **Applying the split** using the most recent plan file for this branch under `.claude/reviews/pr-split/`. Errors if none exists. This flag is the *only* way this skill mutates git state — never construct branches as a side effect of the analysis steps below, even if the user's original request also asked to apply.
  **Before acting on that plan file, verify its status against live state — never trust a plan's "Application status"/"COMPLETE" header at face value.** A plan doc is a snapshot of intent at write-time; the actual apply (run later, by a different invocation, or — in a repo with concurrent Claude Code sessions, check `ListAgents` — by a peer session) can diverge from it without the doc ever being corrected, and a stale "already done" claim is exactly what causes duplicate or conflicting work. Concretely: `git branch -r` to confirm the branches the plan names actually exist on `origin`; if they don't, or don't match, the doc is stale — treat the *live* branch/PR state as ground truth, not the doc, and reconcile (or ask the user which one is wanted) before doing anything else. If hosting credentials are configured, also check `bb_pr_lookup.sh` (Bitbucket) or `gh_pr_lookup.sh` (GitHub) / a direct API call for real PR + pipeline state rather than trusting the plan's notes about what was pushed or opened.
- `--interactive` — after Step 5's synthesis, run the **Step 5.5** propose → confirm/adjust loop instead of writing the plan straight from the first synthesis. Meaningless combined with `--apply` (which skips analysis entirely) — ignore it if both are given.

## Step 0 — Load lessons

Read two lesson sources in full and concatenate them (shared first, then project-local) into the `lessons` text used below:

1. `.claude/skills/split-pr/LESSONS.md` — a curated, read-only shared reference. It contains portable heuristics only. Never write to it during a project run.
2. `.claude/reviews/split-pr-lessons.local.md` — project-local, not part of the shared config repo. Read it if it exists; skip silently if it doesn't (no run has captured a repo-specific lesson yet). This is where real package names, ticket numbers, and incident narratives belong.

The combined text gets threaded into every classification agent's prompt (Step 3) and must inform the synthesis (Step 5) — e.g. a note on files that habitually bundle unrelated hunks tells you where to look extra carefully; a note on stale ticket citations tells you not to trust a commit's ticket-key reference at face value.

## Step 1 — Resolve target and scope

Resolve `BASE_REF`/`HEAD_REF` per the Input section. If `<pr-identifier>` is a PR number or URL and hosting credentials are configured (`.claude/.env`), resolve the host with `.claude/tools/detect_git_host.sh` (or the URL's own domain, if `<pr-identifier>` is a full PR URL — that always wins) and use `bb_pr_lookup.sh`/`bb_pr_diffstat.sh` (Bitbucket) or `gh_pr_lookup.sh`/`gh_pr_diffstat.sh` (GitHub) to resolve it to a branch; otherwise treat it as a local branch/ref directly — this skill's core analysis only needs two git refs, not a live PR, so a missing or undetected host is never a blocker here.

```bash
git merge-base "$BASE_REF" "$HEAD_REF"
git log "$BASE_REF..$HEAD_REF" --oneline --reverse
git log "$BASE_REF..$HEAD_REF" --reverse --format='%H %s' | while read hash msg; do
  echo "$hash | $(git show --stat "$hash" | tail -1)"
done
git diff "$BASE_REF...$HEAD_REF" --name-status
```

From the commit list, per the lessons file: flag any commit immediately reverted by a later one (net zero, exclude from classification) and any commit whose message says "ported from PR #N" / mirrors an existing guard elsewhere (strong independent-PR candidate).

## Step 2 — Import graph (deterministic — run this before any LLM classification)

```bash
.claude/tools/import_graph.sh "$BASE_REF" "$HEAD_REF"
```

This is mechanical (grep + JSON parse, no model call) — trust its `edges` over any name-based guess. Read the output for:

- **`edges`**: `{file, from_package, imports_package, specifiers}` — a package that imports another changed package's symbols cannot land in an earlier or parallel PR than the concern that adds those symbols.
- **`reference_mismatches`**: a `package.json` workspace dependency with no matching `tsconfig.json` `references` entry. Report any non-empty result to the user as a standalone finding regardless of the split — per the lessons file, this has caught a real pre-existing gap before.

## Step 3 — Group changed files and classify hunks in parallel

Derive groups from the changed paths and the target repository's declared layout (for example, workspaces, services, packages, tests, docs, and root configuration). Do not assume directory names. If this produces more than ~10 groups, merge the smallest groups that have no dependency edge between them unless the user requested a larger review.

Summarize the Step 2 edges relevant to each group into a short text block (which packages this group's files import from, and which import it), then invoke:

```
Workflow({
  name: "split-pr-analyze",
  args: {
    baseRef: BASE_REF,
    headRef: HEAD_REF,
    groups: [{ key, paths, hint? }, ...],
    lessons: <combined lessons text from Step 0>,
    importGraphSummary: <per-group edge summary>,
  }
})
```

This fans out one agent per group; each returns hunk-level concern labels (free text, not a fixed taxonomy — don't force this diff's concerns into last time's labels) plus any cross-concern risks it spotted. Do not skip this step for a "small enough" diff — even under ~10 files, hunk-level bundling (Step 0's lesson list) is easy to miss by eye.

## Step 4 — Also check the working tree

If there are uncommitted changes on `HEAD_REF`'s branch (`git status --porcelain`), run one more classification pass on that diff too (`git diff` with no ref, against the working tree) and mark every hunk from it explicitly as **uncommitted** in the output — an uncommitted change must never be silently folded into a PR's file list as if it were already reviewed history.

## Step 5 — Synthesize

1. Merge every group's `hunks` by `concern` label (same label text = same concern, across groups) into a single list of concerns.
2. Build a dependency DAG from Step 2's `edges` (concern A → concern B when A's files import a symbol from B's files that's new in this diff) plus any `cross_concern_risks` the classification agents surfaced.
3. Topologically sort into **tracks** (parallel-safe, no edge between them) and, within a track, a **stack** (sequential PRs, each depending on the last). Do not assume the user's proposed order is correct — say explicitly if the DAG contradicts it, and why (cite the specific import edge).
4. For every file with hunks in 2+ concerns, call it out explicitly as needing a hunk-level split (`git add -p`), not a whole-file assignment.
5. List concerns marked `independent: true` separately — these are candidates for small, ordering-free PRs that can land anytime and should usually go first to shrink the remaining diff.
6. For configuration or environment-schema changes, read the target repository's documented conventions and ensure their required paired files travel together. Flag any missing required companion change.

## Step 5.5 — Interactive convergence loop (`--interactive` only)

Skip this step entirely when `--interactive` was not passed — go straight from Step 5 to Step 6 with the first synthesis, as before. This step is chat-only: it never writes the plan file and never touches git.

1. From the Step 5 synthesis, state the **current proposal** to the user: the number of tracks/PRs, and one paragraph of reasoning grounded in the actual DAG and concern list — which edges force a sequential stack, which concerns are `independent: true` and could stand alone or be bundled, which shared files forced a merge. This is a short chat summary, not Step 6's file.
2. Ask, via `AskUserQuestion`: "Do you agree with splitting this into **N** PRs?" — one option to confirm, one to give a different target count.
3. **If the user agrees**: proceed to Step 6 with this synthesis. If more than one round ran, note the final agreed count and round count in the plan's Verdict section (Step 6).
4. **If the user gives a different target count M**, re-derive tracks from the *same* Step 5 concern list and DAG — do not re-run Step 3's classification agents or Step 2's import graph; only the grouping changes:
   - **To reduce the count**, merge tracks only where it doesn't violate the DAG. Prefer, in order: (a) two tracks both marked `independent: true`, then (b) a track collapsed into its single direct dependency. Never merge ambiguous hunks or separate configuration changes from companions required by the target repository's conventions.
   - **To increase the count**, split a track only along boundaries the existing data already supports: a concern label Step 5's item 1 folded into a bigger track purely for size, a file Step 5's item 4 flagged as bundling hunks from 2+ concerns, or an `independent: true` concern bundled into a larger PR instead of standing alone. Never invent a split boundary that isn't backed by a concern label or hunk record from Step 3 — this is the same rule as the Constraints section's "no silent bucket assignment," applied to re-grouping.
   - **If M is infeasible** — a hard dependency edge blocks merging past some minimum, or there's no remaining independently-verified boundary to split out to reach M — say so explicitly, cite the specific edge/hunk that blocks it, state the closest feasible count, and re-ask with that count as the new proposal. Never silently substitute a different number without saying so.
   - Return to step 1 with the new proposal.
5. **Loop cap**: after 4 rounds without convergence, stop proposing new numbers. Summarize the range of counts explored and what boundary blocked each direction, then ask the user to either accept the closest proposal or take over the grouping manually (naming exact files per PR) — don't loop indefinitely.

## Step 6 — Write the plan

In `--interactive` mode, only reach this step once Step 5.5 has converged (or hit its loop cap and the user picked an option); non-interactive runs proceed here directly from Step 5.

Write a markdown plan to `.claude/reviews/pr-split/<branch-with-slashes-as-dashes>-<YYYY-MM-DD>.md` (`mkdir -p` the directory first; get the date via `date +%F`, not by guessing). Structure:

```
# PR split plan: <branch> → <base>

## Verdict on any split the user proposed
<one paragraph — confirm, or state precisely how/why the dependency order differs, citing the import edge. If --interactive ran more than one round, also note the agreed PR count and how many rounds it took>

## Tracks
| Track/PR | Depends on | Contents (concern labels) | Rationale |

## File → PR mapping
<table or list, grouped by track/PR>

## Files needing hunk-level splitting
<list, each with which concerns are mixed in and how to tell them apart>

## Risks / dependencies
<bulleted, most important first — ordering violations, shared-file hunk hazards, reference_mismatches, uncommitted-diff items, anything from the Step 0 lessons text that applied here>

## Standalone findings (not about the split)
<e.g. reference_mismatches that are real bugs regardless of how the PR gets split>
```

Tell the user the file path. Do not also paste the entire plan into chat if it's long — summarize the verdict, track count, and top 2-3 risks, and point at the file.

## Step 7 — Adversarial self-critique (self-improvement — runs every time, not only on complaint)

Put the draft plan on trial before showing it to the user, instead of waiting for them to catch a mistake. Spawn 2-3 independent critic agents in parallel via the `Agent` tool (fresh/general-purpose, **not** forks — they must not inherit your synthesis reasoning or they'll just agree with it). Give each critic only: the draft plan file's contents, the diff range (`BASE_REF...HEAD_REF`), the combined lessons text from Step 0, and Step 2's import-graph JSON. Instruct each to try to REFUTE the plan, specifically checking:

- Does every edge cited in "Verdict on any split the user proposed" and the "Tracks" table actually appear in the import-graph JSON or a hunk a classification agent reported — not just asserted?
- Is any file assigned wholly to one concern/track when its actual diff contains hunks from 2+ concerns?
   - Does any configuration concern omit a companion required by the target repository's documented conventions?
- Does the plan repeat a mistake the lessons text already warns about, or ignore a non-empty `reference_mismatches`?
- Is the dependency order actually a valid topological sort of the DAG, or does some track depend on a later one?
- For any concern that **deletes** an exported symbol: does the plan claim (or assume) that concern is independently landable? If so, that claim is unverified until someone actually runs a build with only that concern's changes applied on top of the base branch — reading imports only catches *forward* dependencies (what new code needs), never *reverse* ones (unmigrated old code elsewhere in the repo that still imports the symbol being deleted). Flag any such unverified claim explicitly rather than trusting it.

A critique counts as **CONFIRMED** only when the critic cites a specific file, hunk, or import edge as evidence — discard vague or unevidenced doubts. Require at least 2 of 3 critics (or 1 of 1 if only one ran) to independently flag the same issue before treating a borderline call as confirmed; a single critic's uncorroborated claim is not enough on its own to rewrite the plan.

For every CONFIRMED finding:
1. Correct the plan file in place before presenting it.
2. Capture a new dated lesson per "Capture corrections" below — phrase it as a general rule that would catch this class of mistake on a *different* diff, not a restatement of this one instance.

Mention in the chat summary (not necessarily the plan file) how many critique findings were confirmed and fixed, if any — silently correcting the plan without saying so hides a real mistake the user should know almost happened.

## Applying the split (`--apply`, or a separate explicit later request — never implied by an analysis request)

Only run this section when explicitly asked, in words, to create the branches/commits — not merely because a plan was produced. Confirm the plan file being applied is the one the user means if more than one exists for this branch.

1. For each track/PR in dependency order: `git switch -c <branch-name> <parent-branch-or-base>`.
2. For files wholly owned by one concern: `git checkout <head_ref> -- <file>` (or cherry-pick the relevant commit) onto that branch.
3. For files flagged as needing a hunk-level split: use `git checkout --patch` / interactive staging against `HEAD_REF`'s version of the file, applying only the hunks belonging to this track's concerns.
4. After staging each branch, regenerate any dependency lockfile with the package-manager command documented by the target project. Never hand-edit generated lockfiles. Commit only after reviewing the resulting diff.
5. Verify each branch against the target repository's current CI configuration and documented local commands. Start from a clean build state when the project uses incremental compilation. Run every applicable local gate; explicitly report any gate that requires unavailable services or credentials. Do not call a branch ready until all runnable gates pass on that branch alone.
6. Push only after verification passes and only when the user explicitly requested pushes. Report the branch names and dependency order; do not assume a particular hosting provider or PR-creation workflow.
7. Never force-push, never rewrite a branch another person may have already pulled, and never touch the original `HEAD_REF` branch itself.

## Capture corrections (self-improvement)

This is the fallback path for mistakes that slip past Step 7's critique pass or only surface later. Record corrections in the project-local file before rerunning analysis.

Where the entry goes depends on what kind of lesson it is:

- Append the correction to `.claude/reviews/split-pr-lessons.local.md` (create it if needed). Keep it concrete and free of credentials.
- Never write to the shared `LESSONS.md` during a project run. A maintainer may separately promote an anonymized, portable lesson after review.
- For a reproducible tool defect, fix the relevant shared script in a deliberate maintenance change rather than recording project data in a lesson.

## Constraints

- **No git mutations outside "Applying the split."** Steps 0–6 are read-only (`git diff`/`git log`/`git show`/`git merge-base`/`git status`). Never `git checkout`, `git switch`, `git commit`, `git push`, or `git reset` during analysis.
- **No fabricated ticket numbers or PR-creation calls.** If a citation looks stale (per LESSONS.md), say so; don't invent a replacement.
- **No silent bucket assignment on ambiguous hunks.** If a classification agent or the synthesis step genuinely can't tell which concern a hunk belongs to, list it as ambiguous in the plan and ask the user — don't guess and hide the guess.
- **Project-driven.** Derive package names, layout, CI commands, and branch names from the target repository rather than assuming a particular stack.
