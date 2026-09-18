---
name: answer-pr-comments
description: Compose and post replies to unanswered human reviewer comments on a Bitbucket or GitHub PR. Delegates the full workflow (fetch, research, compose, post) to the comment-responder agent. Usage: /answer-pr-comments <pr-number> [<reviewer-name>] [--dry-run]
---

# answer-pr-comments

Thin entry point. Validates credentials, resolves the git host and PR number, and delegates everything else to the `comment-responder` agent.

Do **not** fetch comments, read files, compose replies, or post to Bitbucket/GitHub yourself — the agent owns all of that.

---

## Input

```
<pr-number> [<reviewer-name>] [--dry-run]
```

- `<pr-number>` — required. Bare integer (`48`) or `#48`.
- `<reviewer-name>` — optional. Case-insensitive substring of `display_name` (e.g. `"Alfeu"` matches `"Alfeu Santos"`). Omit to reply to all human reviewers.
- `--dry-run` — passed through to the agent; it prints proposed replies without posting.

---

## Step 0 — Load credentials, resolve host, and validate

```bash
set -a; . .claude/.env; set +a
HOST=$(.claude/tools/detect_git_host.sh) || HOST=""
```

If `detect_git_host.sh` failed (empty `$HOST`), tell the user to set `GIT_HOST=bitbucket` or `GIT_HOST=github` in `.claude/.env` and stop.

Required: when `$HOST=bitbucket` — `BITBUCKET_WORKSPACE`, `BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`. When `$HOST=github` — `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_TOKEN`.

If any key is missing or a placeholder, tell the user which key to fix and **stop**. Do not spawn the agent on missing creds.

---

## Step 1 — Resolve PR number

Parse `<pr-number>` from args (strip leading `#`). If args is empty, look up the open PR for the current branch via the host-appropriate lookup tool:

```bash
set -a; . .claude/.env; set +a
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

## Step 2 — Delegate to the `comment-responder` agent

Use the Agent tool with `subagent_type: "comment-responder"`. The agent handles everything from here: fetching comments, filtering, reading code, composing replies, and posting. Do **not** pass tokens in the prompt.

**Prompt template:**

```
Answer unanswered reviewer comments on a <Bitbucket|GitHub> PR.

  host:            <bitbucket|github — from $HOST>
  workspace:       <BITBUCKET_WORKSPACE, or GITHUB_OWNER when host=github>
  repo:            <BITBUCKET_REPO_SLUG, or GITHUB_REPO when host=github>
  pr_id:           <PR_ID>
  reviewer_filter: <REVIEWER_NAME or empty>
  dry_run:         <true|false>
  project_root:    <absolute path to repo root>

Run your full procedure (Steps 0–5) and return your completion summary as your final message.
```

Surface the agent's final message verbatim.

---

## Step 3 — Follow-up replies after manual fixes

When you (the main loop, not the agent) fix code in response to a reviewer comment and then post a confirmation reply, **always post it as a threaded reply under the original comment** — never as a bare top-level PR comment.

1. Look up the original comment ID if you don't already have it. On GitHub, also note whether it's an inline **review** comment or a general **issue** comment — the reply mechanism differs between the two:

    ```bash
    set -a; . .claude/.env; set +a
    if [ "$HOST" = "github" ]; then
      # Inline review comments — repliable via the /replies endpoint in step 2.
      curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
        "${GITHUB_API_URL:-https://api.github.com}/repos/$GITHUB_OWNER/$GITHUB_REPO/pulls/{pr_id}/comments?per_page=100" \
        | python3 -c "import sys,json; [print(c['id'], 'review', c['user']['login'], c['body'][:60]) for c in json.load(sys.stdin)]"
      # General issue-thread comments — no native reply; see step 2's GitHub/issue case.
      curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
        "${GITHUB_API_URL:-https://api.github.com}/repos/$GITHUB_OWNER/$GITHUB_REPO/issues/{pr_id}/comments?per_page=100" \
        | python3 -c "import sys,json; [print(c['id'], 'issue', c['user']['login'], c['body'][:60]) for c in json.load(sys.stdin)]"
    else
      curl -sSL -u "$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN" \
        "https://api.bitbucket.org/2.0/repositories/$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG/pullrequests/{pr_id}/comments?pagelen=100" \
        | python3 -c "import sys,json; [print(c['id'], c['user']['display_name'], c['content']['raw'][:60]) for c in json.load(sys.stdin)['values']]"
    fi
    ```

2. Post the reply:

    - **Bitbucket** — a `parent` field on a normal comment POST:
        ```bash
        curl -sSL --fail-with-body -u "$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN" \
          -X POST -H "Content-Type: application/json" \
          -d '{"content":{"raw":"<reply text>"},"parent":{"id":<PARENT_COMMENT_ID>}}' \
          "https://api.bitbucket.org/2.0/repositories/$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG/pullrequests/{pr_id}/comments"
        ```
    - **GitHub, original was an inline review comment** — the dedicated replies endpoint:
        ```bash
        curl -sSL --fail-with-body -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
          -X POST -d '{"body":"<reply text>"}' \
          "${GITHUB_API_URL:-https://api.github.com}/repos/$GITHUB_OWNER/$GITHUB_REPO/pulls/{pr_id}/comments/<PARENT_COMMENT_ID>/replies"
        ```
    - **GitHub, original was a general issue comment** — GitHub has no threading for issue-level comments, so there is no true "reply". Post a new general comment that quotes the original so the connection is visible in the UI, and tell the user this is a best-effort thread, not a native GitHub reply:
        ```bash
        curl -sSL --fail-with-body -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
          -X POST -d '{"body":"> <first ~80 chars of original comment>\n\n<reply text>"}' \
          "${GITHUB_API_URL:-https://api.github.com}/repos/$GITHUB_OWNER/$GITHUB_REPO/issues/{pr_id}/comments"
        ```

---

## Constraints

- **One PR-lookup call max.** The branch-to-PR lookup tool call in Step 1 is the only API call the skill itself makes. All fetching and posting belongs to the agent (Step 2) or uses the threaded pattern above (Step 3).
- **Always thread replies.** Never post a follow-up as a bare top-level comment — Bitbucket via `"parent":{"id":<id>}`, GitHub inline comments via the `/replies` endpoint, GitHub issue comments via an explicit quote of the original (GitHub's closest equivalent, since issue comments have no native threading).
- **No token leaks.** Never echo, log, or include tokens in the agent prompt.
