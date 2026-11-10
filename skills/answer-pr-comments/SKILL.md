---
name: answer-pr-comments
description: Answer unanswered human reviewer comments on a Bitbucket or GitHub PR. By default composes replies (delegated to the comment-responder agent), shows them and posts after one confirmation; with --fix it also verifies each comment against the code, fixes what is valid, argues with evidence what is not, runs the project's checks, and posts the replies after one confirmation. Usage: /answer-pr-comments <pr-number> [<reviewer-name>] [--dry-run] [--fix]
---

# answer-pr-comments

Entry point. Validates credentials, resolves the git host and PR number, then either:

- **reply mode** (default): the `comment-responder` agent researches and composes the replies; you show them and ask once; the agent posts what the user approved. Do **not** fetch comments, read files, compose replies, or post to Bitbucket/GitHub yourself.
- **fix mode** (`--fix`): the agent only *collects* the unanswered comments and later *posts* the replies; you (the main loop, which has Edit/Write) triage, fix and verify in between. See "Fix mode" below.

---

## Input

```
<pr-number> [<reviewer-name>] [--dry-run] [--fix]
```

- `<pr-number>` — required. Bare integer (`48`) or `#48`.
- `<reviewer-name>` — optional. Case-insensitive substring of `display_name` (e.g. `"Jane"` matches `"Jane Doe"`). Omit to reply to all human reviewers.
- `--dry-run` — show the proposed replies and stop; nothing is posted and no question is asked. With `--fix` it means: do the triage, edits and checks, show the replies, but do not commit, push or post.
- `--fix` — address the comments instead of only replying: fix valid ones in the working tree, push back on invalid ones with evidence. Requires the PR's source branch to be checked out.

---

## Step 0 — Load credentials, resolve host, and validate

```bash
eval "$(python3 .claude/tools/env_exports.py)"
HOST=$(.claude/tools/detect_git_host.sh) || HOST=""
CACHE_DIR=$(mktemp -d)   # private; pass it to the agent, never use fixed /tmp names
echo "HOST=$HOST CACHE_DIR=$CACHE_DIR"
```

Shell variables don't survive between commands: carry the printed host and cache path as literals. `<CACHE_DIR>` below is that path, and a later block that tests the host starts with `HOST="<host printed above>"`.

If `detect_git_host.sh` failed (empty host), tell the user to set `GIT_HOST=bitbucket` or `GIT_HOST=github` in `.claude/.env` and stop.

Required: when the host is `bitbucket` — `BITBUCKET_WORKSPACE`, `BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`. When it is `github` — `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_TOKEN`.

If any key is missing or a placeholder, tell the user which key to fix and **stop**. Do not spawn the agent on missing creds.

---

## Step 1 — Resolve PR number

Parse `<pr-number>` from args (strip leading `#`). If args is empty, look up the open PR for the current branch via the host-appropriate lookup tool:

```bash
eval "$(python3 .claude/tools/env_exports.py)"
HOST="<host printed above>"
BRANCH=$(git branch --show-current)
if [ "$HOST" = "github" ]; then
  .claude/tools/gh_pr_lookup.sh "$BRANCH"
else
  .claude/tools/bb_pr_lookup.sh "$BRANCH"
fi
```

Parse the JSON output (`{mode, pr_id?, title?, choices?}`):

- `mode=pr` → use `pr_id`.
- `mode=local` → tell the user no open PR exists for this branch and stop.
- `mode=ambiguous` → list `choices` and ask the user to pick.

On 401/403 → stop, tell the user to check `BITBUCKET_EMAIL`/`BITBUCKET_API_TOKEN` (Bitbucket) or `GITHUB_TOKEN` (GitHub). On 404 → check workspace/repo slug (Bitbucket) or owner/repo (GitHub).

---

## Step 2 — Delegate to the `comment-responder` agent (reply mode)

With `--fix`, skip to "Fix mode" below. Otherwise use the Agent tool with `subagent_type: "comment-responder"`. The agent fetches the comments, filters them, reads the code and composes the replies into `<CACHE_DIR>/cr_replies_<pr>.json`, without posting (`dry_run: true`). Do **not** pass tokens in the prompt.

**Prompt template:**

```
Answer unanswered reviewer comments on a <Bitbucket|GitHub> PR.

  host:            <bitbucket|github — the host from Step 0>
  workspace:       <BITBUCKET_WORKSPACE, or GITHUB_OWNER when host=github>
  repo:            <BITBUCKET_REPO_SLUG, or GITHUB_REPO when host=github>
  pr_id:           <PR_ID>
  reviewer_filter: <REVIEWER_NAME or empty>
  dry_run:         true
  project_root:    <absolute path to repo root>
  cache_dir:       <CACHE_DIR>
  mode:            reply

Run your full procedure (Steps 0–5) and return your completion summary as your final message.
```

Show the agent's proposed replies. With `--dry-run`, stop here. Otherwise ask one question: post all, post some (the user names which), or post none. Then spawn the agent again with the same prompt but `mode: post`, `dry_run: false` and `replies_file: <CACHE_DIR>/cr_replies_<pr>.json`, after removing any reply the user did not approve from that file. Surface its final message verbatim.

---

## Fix mode (`--fix`)

The goal is that every unanswered comment ends in one of two states: **fixed**, or **declined with an argument the reviewer can check**. Nothing is committed, pushed or posted until the user confirms once, near the end.

### F0 — Preconditions

```bash
git branch --show-current          # must equal the PR's source branch; else stop and say which to check out
git status --porcelain             # uncommitted changes: tell the user before editing on top of them
git fetch -q origin && git rev-list --left-right --count 'HEAD...origin/<source-branch>'   # behind > 0: stop and say so
```

The branch name is the PR author's: keep it inside the single quotes, writing each `'` in it as `'\''`, so `$`, backticks or `(…)` in it stay text.

Read the project `CLAUDE.md` / contributing docs for the checks to run (typecheck, lint, format, tests) and any coding standards, including any review checklist it or the workspace-root `CLAUDE.md` points to (e.g. a DB migration checklist). A fix that touches a migration is re-checked against that checklist item by item, not only against the comment that asked for it. Note the PR's destination branch and whether sibling repositories are checked out next to this one (read-only references, see F2).

### F1 — Collect

Spawn the `comment-responder` agent with the Step 2 prompt but `mode: collect` (and `dry_run: true`). It writes `<CACHE_DIR>/cr_unanswered_<pr>.json` (id, kind, author, file, line, text, thread). Read that file. If it is empty, report that and stop.

### F2 — Triage: verify before acting

For **each** comment, read the code it points at (locate by identifier, not just line number: the file has moved on since the comment was written) and decide:

| Verdict | When | Reply opener |
| --- | --- | --- |
| **Fix** | The claim holds, or a stated team standard is violated. Default for anything the reviewer backs with a standard. | `Fixed:` |
| **Fix differently** | The problem is real but the suggested remedy is worse than another. Say why. | `Fixed:` + the reason |
| **Already fixed** | The code no longer shows the issue. Name the file/function. | `Fixed:` |
| **Intentional** | Current behaviour is deliberate and you can show why. | `Intentional:` |
| **Deferred** | Real, but outside this change (another repo, another ticket, a product decision). Needs a concrete follow-up. | `Deferred:` |
| **Answer** | A question. | none |

Rules:

- **Verify claims, do not trust them.** Reviewer comments, including automated or AI-assisted ones (`[bot]`, `[claude]` prefixes), can be wrong, stale or about a different commit. Check each factual claim (line counts, "no caller", "origin accepts X") against the code or the referenced source. A claim that is false gets a reply that says so with the evidence.
- **Cross-repo references:** open the sibling checkout read-only (`../<repo>`) and cite file and line. Never edit another repository; a needed change there is a `Deferred:` with the repo and what to change, and goes into the final report for the user.
- **Push back only with evidence** (file:line, a test, a doc, origin source), never on preference or effort. "Too big for this PR" is acceptable only for a change that is separable and the reply names where it goes.
- **Do not defer what is cheap and in scope.** A standard the reviewer cites is the team's rule: default to fixing.
- **A decision that is the user's** (product behaviour, a new config flag, an API contract change) is not yours to settle: record it as `Deferred:` or ask the user once, batched, before F3.
- Related comments often share a root cause or a file. Group them, fix once, answer each.

Write the triage as a table (id, file, verdict, one-line reason) and keep it for the final report.

### F3 — Fix

- Edit only what the comments require. Mention any extra change that was needed to make a fix correct.
- Fixes add no code comments: make the code self-descriptive (names, extracted functions) instead. When a reviewer asks to remove a comment, move its meaning into a name rather than just deleting it.
- A behaviour change gets a test. When feasible show it is real: temporarily undo the fix and confirm the test fails, then restore.
- A refactor (splitting a file, grouping parameters) must preserve behaviour: run the tests before and after.
- If fixing one comment invalidates the wording of docs, README, OpenAPI text or tests elsewhere, update them in the same change.
- If the PR changes docs, run the `doc-review` self-check (`../doc-review/references/self-check.md`) on every changed doc after the fixes, not only on the lines the comments point at. Reviewers who flag one unmerged claim, history line or duplicated rule usually missed others of the same kind.

### F4 — Verify

Run the project's checks (typecheck, lint, format check, full test suite). Everything must pass; if something cannot run locally, say so. Do not skip, weaken or delete a failing test to get green.

### F5 — Compose replies

Same style rules as the agent's Step 4: 2–4 sentences, specific (file/function, what changed), no thanks-or-praise openers, concrete follow-up when deferring. Write them to `<CACHE_DIR>/replies.json` as a list of `{id, kind, reply, text}` (`kind` and `text` come from the collected file).

Never write `Fixed:` for something that is not in the tree, and never post a reply that names a change before that change is pushed.

### F6 — Confirm once, then publish

Show: the triage table, the check results, the `git diff --stat`, and every proposed reply. Ask one question covering commit, push and posting. With `--dry-run`, stop here.

On approval:

1. Commit in the repository's message style (follow the attribution instruction in the session) and push the PR's branch. Never force-push, never amend published commits, never touch another branch.
2. Spawn the agent with `mode: post` and `replies_file: <CACHE_DIR>/replies.json`. If the user approved only part of it, post only that part.
3. Report: what was fixed, what was declined and why, what was deferred and where it must be followed up (other repos, tickets, decisions), and anything the checks could not cover.
4. Lessons: if a valid comment shows an expectation that no shared skill covers (for docs `doc-review`, for backend code `backend-implementation`), propose a generic rule for that skill's "Learning from reviewers" step in the report. Edit the skill only if the user agrees.

If the user declines or edits something, do exactly that and nothing more.

---

## Step 3 — Follow-up replies after manual fixes

When you (the main loop, not the agent) fix code in response to a reviewer comment and then post a confirmation reply, **always post it as a threaded reply under the original comment** — never as a bare top-level PR comment.

1. Look up the original comment ID if you don't already have it. On GitHub, also note whether it's an inline **review** comment or a general **issue** comment — the reply mechanism differs between the two:

    ```bash
    eval "$(python3 .claude/tools/env_exports.py)"
    . .claude/tools/curl_auth.sh   # credentials go through a pipe, never the command line
    HOST="<host printed above>"
    if [ "$HOST" = "github" ]; then
      API="${GITHUB_API_URL:-https://api.github.com}/repos/$GITHUB_OWNER/$GITHUB_REPO"
      # Inline review comments — repliable with --reply-to in step 2.
      curl -sSL -K <(curl_bearer_auth "$GITHUB_TOKEN") -H "Accept: application/vnd.github+json" \
        "$API/pulls/{pr_id}/comments?per_page=100" \
        | python3 -c "import sys,json; [print(c['id'], 'review', c['user']['login'], c['body'][:60]) for c in json.load(sys.stdin)]"
      # General issue-thread comments — no native reply; see step 2's GitHub/issue case.
      curl -sSL -K <(curl_bearer_auth "$GITHUB_TOKEN") -H "Accept: application/vnd.github+json" \
        "$API/issues/{pr_id}/comments?per_page=100" \
        | python3 -c "import sys,json; [print(c['id'], 'issue', c['user']['login'], c['body'][:60]) for c in json.load(sys.stdin)]"
    else
      curl -sSL -K <(curl_basic_auth "$BITBUCKET_EMAIL" "$BITBUCKET_API_TOKEN") \
        "https://api.bitbucket.org/2.0/repositories/$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG/pullrequests/{pr_id}/comments?pagelen=100" \
        | python3 -c "import sys,json; [print(c['id'], c['user']['display_name'], c['content']['raw'][:60]) for c in json.load(sys.stdin)['values']]"
    fi
    ```

2. Show the reply and post it only after the user confirms. Write the text to `<CACHE_DIR>/reply.md` (the literal path printed in Step 0) with the Write tool, never through the shell: replies often quote code or the reviewer, and a line equal to a heredoc's delimiter would end the heredoc and run the rest as shell. Then pass the file:

    - **Bitbucket** — a threaded reply under the original:
        ```bash
        .claude/tools/bb_post_comment.sh --pr-id={pr_id} --parent=<PARENT_COMMENT_ID> --body-file="<CACHE_DIR>/reply.md"
        ```
    - **GitHub, original was an inline review comment** — the dedicated replies endpoint:
        ```bash
        .claude/tools/gh_post_comment.sh --pr-id={pr_id} --reply-to=<PARENT_COMMENT_ID> --body-file="<CACHE_DIR>/reply.md"
        ```
    - **GitHub, original was a general issue comment** — GitHub has no threading for issue-level comments, so there is no true "reply". Start `reply.md` with the first ~80 characters of the original comment as a `> ` quote, then a blank line, then the reply, and post it as a new general comment; tell the user this is a best-effort thread, not a native GitHub reply:
        ```bash
        .claude/tools/gh_post_comment.sh --pr-id={pr_id} --body-file="<CACHE_DIR>/reply.md"
        ```

---

## Constraints

- **One PR-lookup call max.** The branch-to-PR lookup tool call in Step 1 is the only API call the skill itself makes. All fetching and posting belongs to the agent (Step 2, or Fix mode's `collect` and `post`) or uses the threaded pattern above (Step 3).
- **Nothing outward without confirmation.** Reply mode posts only after Step 2's question; fix mode commits, pushes and posts once, after F6's single approval; a Step 3 follow-up posts after the user confirms it. Never force-push; never edit another repository.
- **Always thread replies.** Never post a follow-up as a bare top-level comment — Bitbucket via `--parent`, GitHub inline comments via `--reply-to` (the `/replies` endpoint), GitHub issue comments via an explicit quote of the original (GitHub's closest equivalent, since issue comments have no native threading).
- **No token leaks.** Never echo, log, or include tokens in the agent prompt.
