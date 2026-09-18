---
name: sonar-triage
description: Fetch and triage SonarQube Cloud issues for this repo's project — on a PR, a branch, or the main branch — and propose a fix for each. Knows this repo's known false-positive classes (serialized browser runtimes) so it does not propose changes that break the build. Analysis only; never edits code unless the user explicitly asks. Usage: /sonar-triage [pr <number> | branch <name> | main]
---

# sonar-triage — SonarQube Cloud issue triage

Reads issues from SonarQube Cloud via the **`sonarqube` MCP server** (registered in
`.mcp.json`, tools prefixed `mcp__sonarqube__`). Produces a triage table plus a
suggested fix per issue.

**This skill is analysis-only.** Report and suggest. Do not edit source, do not
call `change_sonar_issue_status`, and do not commit — unless the user asks for
that in a separate, explicit instruction.

## Configuration

Never hardcode the org or project key. Resolve them, in order:

| Value | Source |
|---|---|
| Org | `$SONAR_ORG` (falls back to `sonar.organization` in `sonar-project.properties`) |
| Project key | `sonar.projectKey` in `sonar-project.properties` |
| Base URL | `$SONAR_URL` (default `https://sonarcloud.io`) |
| Token | `$SONAR_API_TOKEN`, synced from `.claude/.env` by the `sync-env.py` SessionStart hook |

Read the project key from the repo, not from memory — this skill is used across
several `art-platform-*` repos and each has its own key.

**Never echo `$SONAR_API_TOKEN`** into output, a commit, or a file.

## Choosing the scope

Sonar scopes issues to a branch or PR. Picking the wrong one silently returns
zero issues, which reads as "clean" when it is not. Resolve scope in this order:

1. **Argument given** (`pr 35`, `branch develop`, `main`) — use it.
2. **No argument** — get the current git branch. If it has an open PR analyzed by
   Sonar, use `list_pull_requests` to find its key and scope to that PR.
3. **Neither** — fall back to the main branch, and **say so explicitly** in the
   output.

Before reporting "no issues", confirm the scope was actually analyzed
(`list_branches` / `list_pull_requests` show an `analysisDate`). A project with
zero analyses reports zero issues and a quality gate of `NONE` — that is
"never measured", not "clean". Report those as different findings.

> As of 2026-08-24 the `develop` main branch of `art-platform-findfix` had **never been
> analyzed** — `bitbucket-pipelines.yml` runs the SonarCloud step only in the PR
> pipeline. All real data lives on PR scopes. Re-check rather than assuming this
> is still true.

## Procedure

1. Resolve config and scope as above.
2. `mcp__sonarqube__get_project_quality_gate_status` — record pass/fail and which
   condition failed.
3. `mcp__sonarqube__search_sonar_issues_in_projects` for the scope.

   Scope parameters are named **`pullRequest`** and **`branch`** — *not*
   `pullRequestId`. The server rejects unknown properties outright, so a wrong
   name is a hard validation error, not a silent full-project query.

   | Tool | Key params |
   |---|---|
   | `search_sonar_issues_in_projects` | `projects[]`, `pullRequest`, `branch`, `severities`, `impactSoftwareQualities`, `issueStatuses`, `files`, `p`, `ps` |
   | `get_project_quality_gate_status` | `projectKey`, `pullRequest`, `branch` |
   | `list_pull_requests` / `list_branches` | `projectKey` |
   | `show_rule` | `key` |

   The MCP server exposes no coverage-by-file breakdown for new code. When the
   gate fails on `new_coverage`, fall back to the REST API for the per-file
   split — `api/measures/component_tree` with
   `metricKeys=new_lines_to_cover,new_uncovered_lines`. Those values arrive under
   `measures[].periods[0].value`, **not** `measures[].value`; reading the wrong
   one yields `None` for every file and looks like "no data".
4. For each distinct rule key, `mcp__sonarqube__show_rule` once to get what the
   rule actually checks. Do not paraphrase a rule from its message alone.
5. **Read the flagged code.** Every suggestion must be based on the actual file,
   not the Sonar message. Line numbers drift between the analyzed commit and the
   working tree — if they disagree, locate the code by symbol name and say the
   line has moved.
6. Group by rule, then triage each group against the known false positives below.
7. Emit the report.

## Known false-positive classes in this repo

Check these **before** suggesting a fix. Proposing them is worse than silence —
they break the build in ways unit tests do not catch.

### `typescript:S7721` "Move function to the outer scope" in `packages/a11y-runtime/**`

**Do not fix. This rule is invalid for this package.**

`installLocatorRuntime` and `installApplier` are each ONE self-contained function
that is serialized with `Function.prototype.toString()` and injected into a live
page (via `page.addInitScript`, and inlined into the emitted fix script). Their
bodies must close over **nothing** — every helper has to be defined inside.
Hoisting a helper to module scope drops it from the serialized string, and the
fix script throws `ReferenceError` in the browser. `packages/a11y-runtime/src/locatorRuntime.ts`
documents this in its header comment.

Unit tests will not catch a regression here: `sonar-project.properties` excludes
`packages/a11y-runtime/**` from coverage precisely because vitest cannot execute
this code. Only `pnpm test:a11y` (Playwright, not in CI) exercises it.

The correct resolution is to mark them **Won't fix / false positive** in Sonar,
or to disable `typescript:S7721` for `packages/a11y-runtime/**` in the quality
profile. Recommend that — do not edit the runtime files.

Same reasoning applies to any rule that wants to hoist, extract, or dedupe across
the boundary of an `install*` function in that package.

### `typescript:S7721` in `packages/engine/src/library.ts`

**Same false-positive class as above — do not fix.**

`installFindFixLibrary` is a self-contained function serialized with
`Function.prototype.toString()` (see `serializeFindFixLibrary`) and injected
into a live page — as `output-lib.js`, or into a Playwright context by
`verifier.ts`. `setAttr`/`removeAttr`/`mintId` capture nothing from the
enclosing scope, so Sonar suggests hoisting them to module scope; doing that
drops them from the serialized string and the browser throws `ReferenceError`
the moment a remediation script calls them — the exact failure mode a leaked
`__name(...)` helper call caused here once already (fixed in
`serializeFindFixLibrary`'s `__name` shim). Mark as **false positive** in
Sonar — this is a structural must-stay-nested constraint, not a coverage gap:
`library.test.ts` runs `installFindFixLibrary` for real under a
`// @vitest-environment jsdom` override, so unlike `a11y-runtime`, this file
is NOT in `sonar.coverage.exclusions`.

### A stale `new_coverage` gate failure

`sonar.coverage.exclusions` is applied **at scan time**. If the exclusion list
changed after the last analysis, the gate still shows the old number, and the
uncovered lines will be concentrated in the newly-excluded paths.

Before proposing that anyone write tests, check the timing:

```sh
git log -S'<excluded-path>' --date=iso --format='%h %ad %s' -- sonar-project.properties
```

Compare that commit date against the scope's `analysisDate`. If the exclusion is
newer, the fix is **re-run the analysis** — not new tests. Say so plainly, and
give the projected coverage with the excluded files removed so the claim is
checkable.

Cross-check against the local `coverage/coverage-summary.json` (vitest). A large
gap between vitest's number and Sonar's `new_coverage` is the signature of this
drift; `sonar-project.properties` records a prior incident of exactly this
(Sonar 35% vs vitest 94%).

## Output format

Lead with scope + quality gate, then a table, then per-rule detail:

```
Scope: PR #35 (feat/…) · Quality gate: ERROR (new maintainability rating)
11 open issues — 1 actionable, 10 false positive
```

| # | Rule | Sev | Location | Verdict |
|---|------|-----|----------|---------|

For each rule group give: what the rule checks (from `show_rule`), why it fired
here, and a concrete suggested fix — or an explicit **Won't fix** with the
reason. State the verdict for every issue; never leave one unclassified.

Close with a "Recommended actions" list ordered by value, and flag anything
structural you noticed (e.g. a branch that is never analyzed) as its own item —
those are usually worth more than the individual issues.
