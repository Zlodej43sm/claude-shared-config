---
name: pr-review
description: Review a Bitbucket or GitHub PR (by number, URL, or branch) — parses the PR title and description for every Jira ticket and Confluence link, batch-fetches them all in one structured preflight pass to build a base logic understanding, asks targeted clarifying questions about cross-service dependencies before the review starts, then delegates to the pr-reviewer subagent for a thorough structured review.
---

# pr-review — entry point for Bitbucket/GitHub PR review

You are the entry point. Your job, in order:

1. **Resolve** the user's argument into a concrete PR (or local-mode branch + destination).
2. **Validate** credentials.
3. **Preflight** — batch-fetch every Jira ticket and Confluence page linked from the PR title, description, source branch, commit messages, Jira remote links, Jira issue links, and Confluence body links — two rounds, all parallel within each round.
4. **Summarize** — present a structured context block and detect cross-service signals.
5. **Clarify** — if cross-service signals are found and no `related_repos` were provided, ask the user for repo paths or doc references **before** the review starts.
6. **Delegate** — pass the pre-fetched context to the `pr-reviewer` subagent so it never re-fetches the same data.

Do **not** fetch the PR diff, classify files, or write the review yourself. The subagent owns all of that.

---

## Tools

All executable logic lives in `.claude/tools/`. Never inline bash or python — call the tools.

This skill supports two git-hosting backends, **Bitbucket** and **GitHub**. `detect_git_host.sh` resolves which one applies to this project (see Step 0); every later step picks the matching `bb_*.sh` or `gh_*.sh` tool. Each pair returns the **same JSON shape**, so nothing downstream — the preflight in Step 1.5, the `pr-reviewer` subagent, Step 3's publishing — needs host-specific parsing. The one real behavioral difference: GitHub has no true "file-level, no line" comment anchor, so `gh_post_comment.sh`'s path-only mode falls back to a general comment prefixed with the file path (see that tool's header for detail).

| Tool                                                                                                           | Purpose                                                                                                                                                                                               |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `detect_git_host.sh`                                                                                           | Resolve `bitbucket` or `github` for this project → stdout bare word                                                                                                                                   |
| `bb_pr_fetch.sh <PR_ID>` / `gh_pr_fetch.sh <PR_NUMBER>`                                                        | Fetch PR metadata + commits → stdout JSON + `/tmp/{pr,gh_pr}_meta.json` `/tmp/{pr,gh_pr}_commits.json`                                                                                                |
| `bb_pr_lookup.sh <BRANCH>` / `gh_pr_lookup.sh <BRANCH>`                                                        | Find open PR by branch → stdout JSON `{mode, pr_id?, title?, choices?}`                                                                                                                               |
| `bb_pr_diffstat.sh <PR_ID>` / `gh_pr_diffstat.sh <PR_NUMBER>`                                                  | List all files changed in a PR → stdout JSON `{changed_files: ["path/to/file.ts", ...]}`                                                                                                              |
| `bb_post_comment.sh` / `gh_post_comment.sh` `--pr-id=N --body=TEXT [--path=P [--line=L]]`                     | Post PR comment → stdout JSON `{id, anchor}`. Three modes: path+line=line-level inline; path only=file-level anchor on Bitbucket (works even when file not in diff, appears in Files tab), falls back to a general comment on GitHub; neither=general thread. |
| `bb_fetch_file.sh <COMMIT> <PATH>` / `gh_fetch_file.sh <COMMIT> <PATH>`                                       | Fetch file at commit → stdout raw content                                                                                                                                                             |
| `jira_fetch_batch.sh KEY1 KEY2 …`                                                                              | Fetch Jira tickets + remote links → stdout JSON + `/tmp/jira_*.json`                                                                                                                                  |
| `conf_fetch_batch.sh ID1 ID2 …`                                                                                | Fetch Confluence pages → stdout JSON + `/tmp/conf_*.json`                                                                                                                                             |
| `extract_pr_links.py`                                                                                          | stdin: PR text → stdout JSON `{jira_keys, conf_page_ids, external_repos}` + writes `/tmp/link_registry.json`                                                                                          |
| `extract_secondary_links.py [--fetched-keys=…] [--fetched-pages=…]`                                            | Reads `/tmp/jira_*.json` + `/tmp/conf_*.json` → stdout JSON `{new_jira_keys, new_conf_page_ids}` + updates `/tmp/link_registry.json`                                                                  |
| `build_prefetch_context.py --pr-id=N --title=T --source-branch=B --dest-branch=B --source-commit=H --author=A` | Reads all `/tmp/jira_*.json` + `/tmp/conf_*.json` + `/tmp/link_registry.json` → stdout PREFETCHED_CONTEXT block                                                                                       |

---

## Input

`args` is one of the following forms (all optional components are in `[]`):

- `<pr-identifier> [-- <repo1> [<repo2> ...]]`
    - `<pr-identifier>` — one of:
        - A bare PR number: `2`, optionally `#2`. Resolved against `$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG` or `$GITHUB_OWNER/$GITHUB_REPO` from `.env`, whichever the detected git host uses (see Step 0).
        - A full Bitbucket PR URL: `https://bitbucket.org/<workspace>/<repo>/pull-requests/<id>`, or a full GitHub PR URL: `https://github.com/<owner>/<repo>/pull/<id>`. Trailing path/query is fine either way. When the URL names a workspace/repo (or owner/repo) different from `.env`, the URL wins — and its host overrides Step 0's detected host too.
        - A source branch name: anything that isn't all digits and doesn't look like a URL, e.g. `feat/$JIRA_WORKSPACE-2-description`.
        - Empty: use the current branch (`git branch --show-current`).
    - `--` followed by one or more **related repo paths or slugs** (e.g. `../sibling-service`, `../shared-lib`) — microservices / sibling packages the reviewer should consider when assessing cross-service contract changes. Optional; omit if not relevant.

Parse the `--` separator greedily: everything before `--` is the pr-identifier; everything after is the related_repos list. If no `--` is present, related_repos is empty.

---

## Step 0 — Load env, resolve the git host, and validate credentials

```bash
set -a; . .claude/.env; set +a
HOST=$(.claude/tools/detect_git_host.sh) || HOST=""
```

`$HOST` is `bitbucket` or `github` — carry it through every later step; it decides which tool script and which credential set applies. If `detect_git_host.sh` exited non-zero (empty `$HOST`), tell the user to set `GIT_HOST=bitbucket` or `GIT_HOST=github` in `.claude/.env` and stop.

Required keys:
- **Always**: `JIRA_WORKSPACE`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.
- **When `$HOST=bitbucket`**: `BITBUCKET_WORKSPACE`, `BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`.
- **When `$HOST=github`**: `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_TOKEN` (`GITHUB_API_URL` is optional — only needed for GitHub Enterprise Server).

Optional keys: `CONFLUENCE_BASE_URL`. If absent, falls back to the host of `$JIRA_BASE_URL` for Confluence URL matching.

If any **required** key is missing or has a placeholder value (`replace-with-...`, `your-...`, etc.), tell the user which key needs to be set and stop.

---

## Step 1 — Resolve the PR id (or fall back to local mode)

Parse the pr-identifier portion of `args`:

- `^#?[0-9]+$` → `PR_ID = digits only`. Skip to Step 1.5, using `$HOST` from Step 0.
- `bitbucket.org/<ws>/<repo>/pull-requests/<id>(/.*)?` → extract workspace, repo, id; override `.env` values and set `HOST=bitbucket` (an explicit URL always wins over Step 0's detected host). Skip to Step 1.5.
- `github.com/<owner>/<repo>/pull/<id>(/.*)?` → extract owner, repo, id; override `.env` values and set `HOST=github`. Skip to Step 1.5.
- Empty → `BRANCH = $(git branch --show-current)`. Do branch lookup (below).
- Anything else → treat as source branch name. Do branch lookup (below).

**Branch lookup:**

```bash
set -a; . .claude/.env; set +a
if [ "$HOST" = "github" ]; then
  .claude/tools/gh_pr_lookup.sh "$BRANCH"
else
  .claude/tools/bb_pr_lookup.sh "$BRANCH"
fi
```

Parse the JSON output:

- `mode=pr` → use `pr_id`. Skip to Step 1.5.
- `mode=local` → **local mode**: skip Steps 1.5–1.6, delegate with `mode=local, branch=$BRANCH, destination=origin/develop`. Tell the user no open PR was found.
- `mode=ambiguous` → list `choices` and ask the user to pick. Stop and wait.

On 401/403: tell the user to check `BITBUCKET_EMAIL`/`BITBUCKET_API_TOKEN` (Bitbucket) or `GITHUB_TOKEN` (GitHub) and stop. On 404: tell them the workspace/repo slug (Bitbucket) or owner/repo (GitHub) in `.env` is likely wrong.

---

## Step 1.5 — Preflight: two-round parallel fetch

### Round 1 — PR metadata + initial links

**1a. Fetch PR metadata and commits:**

```bash
set -a; . .claude/.env; set +a
if [ "$HOST" = "github" ]; then
  .claude/tools/gh_pr_fetch.sh "$PR_ID"
else
  .claude/tools/bb_pr_fetch.sh "$PR_ID"
fi
```

Capture the JSON output as `PR_SUMMARY`. Extract: `title`, `description`, `source_branch`, `dest_branch`, `source_commit`, `author`, `commit_messages`.

**1b. Extract all links from the PR surface:**

```bash
set -a; . .claude/.env; set +a
printf '%s|||COMMITS|||%s' "$title $description $source_branch" "$commit_messages_joined" \
  | .claude/tools/extract_pr_links.py
```

Capture as `INITIAL_LINKS`. Extract `jira_keys[].key` → `JIRA_KEYS` list, `conf_page_ids[].id` → `CONF_IDS` list.

**1c. Batch-fetch tickets + Confluence pages in parallel:**

```bash
set -a; . .claude/.env; set +a
.claude/tools/jira_fetch_batch.sh $JIRA_KEYS &
.claude/tools/conf_fetch_batch.sh $CONF_IDS  &
wait
```

For 404s reported in the JSON outputs: note "Not found" and continue. For exit code 1 (credential error): stop and tell the user.

### Round 2 — Secondary links

**2a. Extract secondary links from Round 1 results:**

```bash
set -a; . .claude/.env; set +a
.claude/tools/extract_secondary_links.py \
  --fetched-keys="$(echo $JIRA_KEYS | tr ' ' ',')" \
  --fetched-pages="$(echo $CONF_IDS | tr ' ' ',')"
```

Capture as `SECONDARY`. Extract `new_jira_keys[].key` → `NEW_KEYS`, `new_conf_page_ids[].id` → `NEW_IDS`.

**2b. Fetch any new items (skip if both lists are empty):**

```bash
set -a; . .claude/.env; set +a
.claude/tools/jira_fetch_batch.sh $NEW_KEYS &
.claude/tools/conf_fetch_batch.sh $NEW_IDS  &
wait
```

For 404s: note "Not found (secondary link)" and continue.

### Round 3 — Build the context block

```bash
set -a; . .claude/.env; set +a
.claude/tools/build_prefetch_context.py \
  --pr-id="$PR_ID" \
  --title="$title" \
  --source-branch="$source_branch" \
  --dest-branch="$dest_branch" \
  --source-commit="$source_commit" \
  --author="$author"
```

Capture the full output (everything from `---PREFETCHED_CONTEXT_START---` to `---PREFETCHED_CONTEXT_END---`) as `PREFETCHED_CONTEXT`.

---

## Step 1.6 — Clarify cross-service scope (interactive)

**Run this step only when BOTH conditions are true:**

1. The `CROSS-SERVICE SIGNALS:` section in `PREFETCHED_CONTEXT` lists at least one signal.
2. `related_repos` (from `args`) is empty.

Present the full `PREFETCHED_CONTEXT` block to the user as a code block, then ask:

> **Pre-fetched context for PR #\<id\>: \<title\>**
>
> \[paste the full context block here\]
>
> ---
>
> I found the following cross-service signals:
> \[list the signals\]
>
> To include a cross-service impact assessment in the review, you can provide:
>
> - **Related repo paths** — local paths like `../consumer-service`
> - **Additional Confluence docs** — paste any contract or schema-registry page URL
> - **Bitbucket/GitHub slugs** — a sibling repo name if the full path isn't available locally
>
> Reply with any of the above, or **"proceed"** to continue without them.

**Wait for the user's reply.** Paths/URLs/slugs → append to `related_repos`/`extra_docs`; proceed to Step 2. `"proceed"` or empty → proceed without additional context.

**If no cross-service signals were found**, skip this step entirely.
**If `related_repos` was already provided** in `args`, skip this step entirely.

---

## Step 2 — Delegate to the `pr-reviewer` subagent

Use the Agent tool with `subagent_type: "pr-reviewer"`. Do **not** pass credentials in the prompt.

**PR-mode prompt template:**

```
Review this <Bitbucket|GitHub> PR. Resolved values from the entry-point skill:

  host:          <bitbucket|github — from $HOST>
  workspace:     <BITBUCKET_WORKSPACE, or GITHUB_OWNER when host=github>
  repo:          <BITBUCKET_REPO_SLUG, or GITHUB_REPO when host=github>
  pr_id:         <PR_ID>
  base_url:      host=bitbucket -> https://api.bitbucket.org/2.0/repositories/<workspace>/<repo>/pullrequests/<pr_id>
                 host=github    -> <GITHUB_API_URL, default https://api.github.com>/repos/<workspace>/<repo>/pulls/<pr_id>
  mode:          pr
  related_repos: <comma-separated list, or "none">
  extra_docs:    <comma-separated Confluence URLs from Step 1.6, or "none">

The following context was pre-fetched by the entry-point skill in a parallel preflight pass.
Use it directly — do NOT re-fetch these Jira tickets or Confluence pages.

<PREFETCHED_CONTEXT>

Because the Jira ticket and Confluence pages are already above, skip the Jira-fetch and Confluence-fetch portions of your Step 1 and the entirety of your Step 1b. Build your AC checklist and logic spec directly from the PREFETCHED_CONTEXT block. Then run Steps 2 through 4 as normal and return the structured review as your final message.
```

**Local-mode prompt template:**

```
Review the current branch against its destination. Resolved values from the entry-point skill:

  branch:        <BRANCH>
  destination:   origin/develop
  mode:          local
  related_repos: <comma-separated list, or "none">

There is no open PR for this branch. Run your standing review procedure in local mode (skip PR-mode-only API calls) and return the structured review as your final message.
```

Surface the subagent's returned message **verbatim**. Do not paraphrase, summarize, or wrap it.

After surfacing the review, write it to a markdown file:

- PR mode: `.claude/reviews/pr-<PR_ID>.md`
- Local mode: `.claude/reviews/<BRANCH-with-slashes-replaced-by-dashes>.md`

Create `.claude/reviews/` if it doesn't exist (`mkdir -p`). Tell the user the file path once it's written.

---

## Step 3 — Publish findings as PR comments (only when user explicitly requests)

Execute this step **only** when the user explicitly asks to publish, post, or push comments. Never post automatically after a review.

Skip entirely in local mode.

### 3a — Resolve source commit

Source commit is already in `$source_commit` from Step 1.5. If the session is fresh and that value is gone, re-run `bb_pr_fetch.sh $PR_ID` (or `gh_pr_fetch.sh $PR_ID` when `$HOST=github`) and read `.source_commit` from the JSON output.

### 3b — Parse findings from the saved review

From `.claude/reviews/pr-<PR_ID>.md`, extract every `Cx` finding header and body. Classify:

- **Inline candidates** — header has `` `path/to/file.py:LINE` `` (explicit line number).
- **File-only candidates** — header has `` `path/to/file.py` `` with no `:LINE`.
- **True general candidates** — header has no file path.

**Comment body transformation:** Header `**Cx** — \`path:line\` — severity`→ opening line`**Cx — emoji severity**` (drop the path:line, keep badge + severity). Follow with the substantive paragraph(s). Strip any meta-framing.

### 3b.5 — Gate: fetch the PR diffstat

Before resolving any line anchor, fetch the set of files actually changed in this PR:

```bash
set -a; . .claude/.env; set +a
if [ "$HOST" = "github" ]; then
  .claude/tools/gh_pr_diffstat.sh "$PR_ID"
else
  .claude/tools/bb_pr_diffstat.sh "$PR_ID"
fi
```

Capture the `changed_files` array as `DIFF_FILES`. This is the **authoritative gate** for all anchor decisions below: a file not in `DIFF_FILES` cannot receive an inline comment — Bitbucket will silently create a misanchored comment that appears detached from the diff view; GitHub instead rejects the post outright (422) if the line isn't part of a diff hunk.

### 3c — Resolve and verify all line anchors

**Mandatory before posting any inline comment.** Bitbucket silently accepts out-of-range line numbers and produces unanchored (invisible) comments; GitHub is stricter and returns a hard error, but only for lines outside the diff — a line that's in the file but in the wrong hunk position can still land on the wrong code, so the same verification applies to both hosts.

**Diffstat gate (apply first to every finding with a file path):**

- If the finding's file is **not** in `DIFF_FILES` → post a **file-level comment**: pass `--path` but **omit** `--line`. On Bitbucket the comment is anchored to the file in the Files tab; on GitHub, `gh_post_comment.sh` falls back to a general comment prefixed with the file path, since GitHub has no true file-only anchor. Either way, do not attempt to resolve a line number for these.
- If the finding's file **is** in `DIFF_FILES` → proceed to the line-range checks below.

Fetch the file at `$source_commit` via `bb_fetch_file.sh` or `gh_fetch_file.sh` depending on `$HOST` (same raw-content output either way):

```bash
set -a; . .claude/.env; set +a
if [ "$HOST" = "github" ]; then
  FETCH_FILE=".claude/tools/gh_fetch_file.sh"
else
  FETCH_FILE=".claude/tools/bb_fetch_file.sh"
fi
```

**For inline candidates (explicit `file:LINE`, file is in diff):**

```bash
"$FETCH_FILE" "$source_commit" "$PATH" | wc -l
```

- `line > total_lines` → keyword-search the file for a distinctive term from the finding body:
    ```bash
    "$FETCH_FILE" "$source_commit" "$PATH" | grep -n "KEYWORD"
    ```
    Use the matched line. If no match, anchor to line 1. On GitHub, a review comment must land on a line that is actually part of the PR's diff hunks — if the matched line falls outside any hunk, the post in 3d will be rejected (422); fall back to a general comment noting the file and intended line in that case.
- `line <= total_lines` → spot-check: fetch the file, confirm expected code appears near that line. If not, run keyword search.

**For file-only candidates (no line number, file is in diff):**

1. Fetch the file via `$FETCH_FILE`.
2. Search for 2–3 distinctive keywords from the finding body.
3. Use the first match line, or line 1 if no match.

**Keyword heuristics by finding type:**

| Finding type                                 | Keyword to search                   |
| -------------------------------------------- | ----------------------------------- |
| Missing `from __future__ import annotations` | line 1 directly                     |
| Test-gap — missing class                     | `class Test` + class name           |
| Missing `.env.example` entry                 | the env var name                    |
| Logic error in a function                    | the function name (`def func_name`) |
| Convention violation in a method             | the method name                     |

### 3d — Post comments

```bash
set -a; . .claude/.env; set +a
if [ "$HOST" = "github" ]; then
  POST_COMMENT=".claude/tools/gh_post_comment.sh"
else
  POST_COMMENT=".claude/tools/bb_post_comment.sh"
fi

# Inline comment
"$POST_COMMENT" \
  --pr-id="$PR_ID" \
  --body="BODY" \
  --path="PATH" \
  --line="LINE"

# General comment (no file reference)
"$POST_COMMENT" \
  --pr-id="$PR_ID" \
  --body="BODY"
```

Report each posted comment's `id` and `anchor` to the user.

---

## Step 4 — Offer related-repo follow-up (when applicable)

If the surfaced review contains an `## Open Questions — Related Services` section **and** `related_repos` was empty, ask the user:

> The review found cross-service contract changes that may affect other services. Would you like me to re-run the review with access to those services? You can provide repo paths like:
>
> `/pr-review <pr-identifier> -- ../sibling-service`

Do this **after** writing the review file. If `related_repos` was already provided, skip.

---

## What NOT to do

- **No inline bash/python.** All executable logic lives in `.claude/tools/`. If you need a new operation, call an existing tool or ask the user to create one — do not embed code in this skill.
- **No diff fetching.** The diff, diffstat, commits, and file reads belong to the subagent.
- **No double-fetching.** Pass `PREFETCHED_CONTEXT` to the subagent verbatim; never re-fetch.
- **No git mutations.** Only `git branch --show-current` (read-only).
- **No token leaks.** Never put credentials in the subagent prompt; the subagent re-reads `.env`.
- **No posting without line verification.** Never call `bb_post_comment.sh`/`gh_post_comment.sh` with `--line` before running Step 3c.
- **No re-reviewing.** If the subagent returned a review, your job is done.
- **No blocking on cross-service questions.** Step 1.6 is one round of clarification. If the user says "proceed", proceed.
