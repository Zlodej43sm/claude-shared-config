---
name: answer-pr-comments
description: Compose and post replies to unanswered human reviewer comments on a Bitbucket PR. Delegates the full workflow (fetch, research, compose, post) to the comment-responder agent. Usage: /answer-pr-comments <pr-number> [<reviewer-name>] [--dry-run]
---

# answer-pr-comments

Thin entry point. Validates credentials, resolves the PR number, and delegates everything else to the `comment-responder` agent.

Do **not** fetch comments, read files, compose replies, or post to Bitbucket yourself — the agent owns all of that.

---

## Input

```
<pr-number> [<reviewer-name>] [--dry-run]
```

- `<pr-number>` — required. Bare integer (`48`) or `#48`.
- `<reviewer-name>` — optional. Case-insensitive substring of `display_name` (e.g. `"Alfeu"` matches `"Alfeu Santos"`). Omit to reply to all human reviewers.
- `--dry-run` — passed through to the agent; it prints proposed replies without posting.

---

## Step 0 — Load credentials and validate

```bash
set -a; . .claude/.env; set +a
```

Required: `BITBUCKET_WORKSPACE`, `BITBUCKET_REPO_SLUG`, `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`.

If any key is missing or a placeholder, tell the user which key to fix and **stop**. Do not spawn the agent on missing creds.

---

## Step 1 — Resolve PR number

Parse `<pr-number>` from args (strip leading `#`). If args is empty, look up the open PR for the current branch:

```bash
BRANCH=$(git branch --show-current)
curl -sSL --fail-with-body -u "$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN" \
  --get --data-urlencode "q=source.branch.name=\"$BRANCH\" AND state=\"OPEN\"" \
  "https://api.bitbucket.org/2.0/repositories/$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG/pullrequests" \
  -o /tmp/pr_lookup.json
```

- One open PR → use its id.
- Zero → tell the user no open PR exists for this branch and stop.
- More than one → list `{id, title}` and ask the user to pick.

On 401/403 → stop, tell the user to check `BITBUCKET_EMAIL` / `BITBUCKET_API_TOKEN`. On 404 → check workspace / repo slug.

---

## Step 2 — Delegate to the `comment-responder` agent

Use the Agent tool with `subagent_type: "comment-responder"`. The agent handles everything from here: fetching comments, filtering, reading code, composing replies, and posting. Do **not** pass tokens in the prompt.

**Prompt template:**

```
Answer unanswered reviewer comments on a Bitbucket PR.

  workspace:       <BITBUCKET_WORKSPACE>
  repo:            <BITBUCKET_REPO_SLUG>
  pr_id:           <PR_ID>
  reviewer_filter: <REVIEWER_NAME or empty>
  dry_run:         <true|false>
  project_root:    <absolute path to repo root>

Run your full procedure (Steps 0–5) and return your completion summary as your final message.
```

Surface the agent's final message verbatim.

---

## Step 3 — Follow-up replies after manual fixes

When you (the main loop, not the agent) fix code in response to a reviewer comment and then post a confirmation reply, **always post it as a threaded reply under the original comment** — never as a top-level PR comment.

1. Look up the original comment ID from the PR comment list if you don't already have it:

    ```bash
    curl -sSL -u "$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN" \
      "https://api.bitbucket.org/2.0/repositories/$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG/pullrequests/{pr_id}/comments?pagelen=100" \
      | python3 -c "import sys,json; [print(c['id'], c['user']['display_name'], c['content']['raw'][:60]) for c in json.load(sys.stdin)['values']]"
    ```

2. Post the reply with a `parent` field:
    ```bash
    curl -sSL --fail-with-body -u "$BITBUCKET_EMAIL:$BITBUCKET_API_TOKEN" \
      -X POST -H "Content-Type: application/json" \
      -d '{"content":{"raw":"<reply text>"},"parent":{"id":<PARENT_COMMENT_ID>}}' \
      "https://api.bitbucket.org/2.0/repositories/$BITBUCKET_WORKSPACE/$BITBUCKET_REPO_SLUG/pullrequests/{pr_id}/comments"
    ```

---

## Constraints

- **One Bitbucket call max for PR lookup.** The branch-to-PR lookup is the only API call the skill makes. All fetching and posting belongs to the agent (Step 2) or uses the threaded pattern above (Step 3).
- **Always thread replies.** Never post a follow-up as a top-level comment — always include `"parent":{"id":<id>}`.
- **No token leaks.** Never echo, log, or include tokens in the agent prompt.
