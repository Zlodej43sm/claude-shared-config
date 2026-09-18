---
name: pr-review
description: Review a Bitbucket PR (by number, URL, or branch) — parses the PR title and description for every Jira ticket and Confluence link, batch-fetches them all in one structured preflight pass to build a base logic understanding, asks targeted clarifying questions about cross-service dependencies before the review starts, then delegates to the pr-reviewer subagent for a thorough structured review.
---

# pr-review — entry point for Bitbucket PR review

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

| Tool                                                                                                           | Purpose                                                                                                                                                                                               |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bb_pr_fetch.sh <PR_ID>`                                                                                       | Fetch PR metadata + commits → stdout JSON + `/tmp/pr_meta.json` `/tmp/pr_commits.json`                                                                                                                |
| `bb_pr_lookup.sh <BRANCH>`                                                                                     | Find open PR by branch → stdout JSON `{mode, pr_id?, title?, choices?}`                                                                                                                               |
| `bb_pr_diffstat.sh <PR_ID>`                                                                                    | List all files changed in a PR → stdout JSON `{changed_files: ["path/to/file.ts", ...]}`                                                                                                              |
| `bb_post_comment.sh --pr-id=N --body=TEXT [--path=P [--line=L]]`                                               | Post PR comment → stdout JSON `{id, anchor}`. Three modes: path+line=line-level inline; path only=file-level anchor (works even when file not in diff, appears in Files tab); neither=general thread. |
| `bb_fetch_file.sh <COMMIT> <PATH>`                                                                             | Fetch file at commit → stdout raw content                                                                                                                                                             |
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
        - A bare PR number: `2`, optionally `#2`. Resolved against `$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG` from `.env`.
        - A full Bitbucket PR URL: `https://bitbucket.org/<workspace>/<repo>/pull-requests/<id>`. Trailing path/query is fine. When the URL names a workspace/repo different from `.env`, the URL wins.
        - A source branch name: anything that isn't all digits and doesn't look like a URL, e.g. `feat/$JIRA_WORKSPACE-2-description`.
        - Empty: use the current branch (`git branch --show-current`).
    - `--` followed by one or more **related repo paths or slugs** (e.g. `../sibling-service`, `../shared-lib`) — microservices / sibling packages the reviewer should consider when assessing cross-service contract changes. Optional; omit if not relevant.

Parse the `--` separator greedily: everything before `--` is the pr-identifier; everything after is the related_repos list. If no `--` is present, related_repos is empty.

---

## Step 0 — Load env and validate credentials

```bash
set -a; . .claude/.env; set +a
```

Required keys: `BITBUCKET_WORKSPACE`, `BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`, `JIRA_WORKSPACE`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.

Optional keys: `CONFLUENCE_BASE_URL`. If absent, falls back to the host of `$JIRA_BASE_URL` for Confluence URL matching.

If any **required** key is missing or has a placeholder value (`replace-with-...`, `your-...`, etc.), tell the user which key needs to be set and stop.

---

## Step 1 — Resolve the PR id (or fall back to local mode)

Parse the pr-identifier portion of `args`:

- `^#?[0-9]+$` → `PR_ID = digits only`. Skip to Step 1.5.
- `bitbucket.org/<ws>/<repo>/pull-requests/<id>(/.*)?` → extract workspace, repo, id; override `.env` values. Skip to Step 1.5.
- Empty → `BRANCH = $(git branch --show-current)`. Do branch lookup (below).
- Anything else → treat as source branch name. Do branch lookup (below).

**Branch lookup:**

```bash
set -a; . .claude/.env; set +a
.claude/tools/bb_pr_lookup.sh "$BRANCH"
```

Parse the JSON output:

- `mode=pr` → use `pr_id`. Skip to Step 1.5.
- `mode=local` → **local mode**: skip Steps 1.5–1.6, delegate with `mode=local, branch=$BRANCH, destination=origin/develop`. Tell the user no open PR was found.
- `mode=ambiguous` → list `choices` and ask the user to pick. Stop and wait.

On 401/403: tell the user to check `BITBUCKET_EMAIL` / `BITBUCKET_API_TOKEN` and stop. On 404: tell them the workspace/repo slug in `.env` is likely wrong.

---

## Step 1.5 — Preflight: two-round parallel fetch

### Round 1 — PR metadata + initial links

**1a. Fetch PR metadata and commits:**

```bash
set -a; . .claude/.env; set +a
.claude/tools/bb_pr_fetch.sh "$PR_ID"
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
> - **Bitbucket slugs** — a sibling repo name if the full path isn't available locally
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
Review this Bitbucket PR. Resolved values from the entry-point skill:

  workspace:     <BITBUCKET_WORKSPACE>
  repo:          <BITBUCKET_REPO_SLUG>
  pr_id:         <PR_ID>
  base_url:      https://api.bitbucket.org/2.0/repositories/<workspace>/<repo>/pullrequests/<pr_id>
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

Source commit is already in `$source_commit` from Step 1.5. If the session is fresh and that value is gone, re-run `bb_pr_fetch.sh $PR_ID` and read `.source_commit` from the JSON output.

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
.claude/tools/bb_pr_diffstat.sh "$PR_ID"
```

Capture the `changed_files` array as `DIFF_FILES`. This is the **authoritative gate** for all anchor decisions below: a file not in `DIFF_FILES` cannot receive an inline comment — Bitbucket will silently create a misanchored comment that appears detached from the diff view.

### 3c — Resolve and verify all line anchors

**Mandatory before posting any inline comment.** Bitbucket silently accepts out-of-range line numbers and produces unanchored (invisible) comments.

**Diffstat gate (apply first to every finding with a file path):**

- If the finding's file is **not** in `DIFF_FILES` → post a **file-level comment**: pass `--path` but **omit** `--line`. The comment will be anchored to the file in the Files tab rather than floating as a general thread. Do not attempt to resolve a line number for these.
- If the finding's file **is** in `DIFF_FILES` → proceed to the line-range checks below.

**For inline candidates (explicit `file:LINE`, file is in diff):**

```bash
set -a; . .claude/.env; set +a
.claude/tools/bb_fetch_file.sh "$source_commit" "$PATH" | wc -l
```

- `line > total_lines` → keyword-search the file for a distinctive term from the finding body:
    ```bash
    .claude/tools/bb_fetch_file.sh "$source_commit" "$PATH" | grep -n "KEYWORD"
    ```
    Use the matched line. If no match, anchor to line 1.
- `line <= total_lines` → spot-check: fetch the file, confirm expected code appears near that line. If not, run keyword search.

**For file-only candidates (no line number, file is in diff):**

1. Fetch the file via `bb_fetch_file.sh`.
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

# Inline comment
.claude/tools/bb_post_comment.sh \
  --pr-id="$PR_ID" \
  --body="BODY" \
  --path="PATH" \
  --line="LINE"

# General comment (no file reference)
.claude/tools/bb_post_comment.sh \
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
- **No posting without line verification.** Never call `bb_post_comment.sh` with `--line` before running Step 3c.
- **No re-reviewing.** If the subagent returned a review, your job is done.
- **No blocking on cross-service questions.** Step 1.6 is one round of clarification. If the user says "proceed", proceed.
