---
name: sonar-triage
description: Fetch and triage SonarQube Cloud issues for this repo's project — on a PR, a branch, or the main branch — and propose a fix for each. Checks a project-local `.claude/sonar-known-issues.md` (if present) for confirmed false-positive rules so it does not propose changes that break the build. Analysis only; never edits code unless the user explicitly asks. Usage: /sonar-triage [pr <number> | branch <name> | main]
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

Read the project key from the repo, not from memory — this skill is shared
across every project that links this config repo, and each has its own key.

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
"never measured", not "clean". Report those as different findings — some
repos only run the SonarCloud step in the PR pipeline, so their main/default
branch is never independently analyzed and all real data lives on PR scopes;
don't assume this without checking `bitbucket-pipelines.yml` (or the repo's
CI config) for this run.

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

## Known false-positive classes

This shared skill does not hardcode any project's known false-positive rules —
those are one specific codebase's structural exceptions (e.g. "this function
must stay self-contained because it gets serialized and injected elsewhere"),
not something every project linking this config repo shares. Before triaging,
check for a project-local file:

`$PROJECT_ROOT/.claude/sonar-known-issues.md`

If it exists, read it in full and check every flagged rule against its entries
**before** suggesting a fix — treat them with the same authority this section
used to have inline (proposing a fix for a documented false positive is worse
than silence: it can break the build in ways unit tests don't catch). If the
file doesn't exist, there are no known false positives recorded for this
project yet — triage every issue on its own merits, and suggest the user
capture one in that file the first time you confirm a real false positive
together, using this format:

```markdown
### `<rule-key>` "<rule name>" in `<path-glob>`

**Do not fix. <one-line reason>**

<Why the rule doesn't apply here — the structural constraint, with a pointer
to the file/comment that documents it, and what breaks if "fixed".>
```

`$PROJECT_ROOT/.claude/sonar-known-issues.md` is project-local (like
`.claude/.env`) — it lives in the project's own `.claude/` directory, not in
this shared config repo, so one project's rule exceptions never leak into
another project's triage.

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

Cross-check against the local coverage report (e.g. `coverage/coverage-summary.json`
for vitest/Jest). A large gap between the local runner's number and Sonar's
`new_coverage` is the signature of this drift — check whether `sonar-project.properties`
or a nearby comment already records a prior incident of exactly this pattern
before assuming it's new.

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
