# Azure DevOps host (`host=azure`)

How `pr-review` and `answer-pr-comments` work when the PR lives in Azure DevOps. Bitbucket and GitHub use the `bb_*.sh` / `gh_*.sh` REST tools; Azure DevOps has no REST tools here. The **main loop** reads and posts through the `azure-devops` MCP server, and diffs and code come from the local clone. Subagents (`pr-reviewer`, `comment-responder`) have no MCP access, so they get files the main loop wrote and never call Azure DevOps themselves.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Resolve the PR and the clone](#2-resolve-the-pr-and-the-clone)
3. [PR metadata → `pr.json`](#3-pr-metadata--prjson)
4. [Comment threads → `comments.json`](#4-comment-threads--commentsjson)
5. [Unanswered threads → `cr_unanswered_<pr>.json`](#5-unanswered-threads--cr_unanswered_prjson)
6. [Diff, diffstat, commits, files](#6-diff-diffstat-commits-files)
7. [Posting](#7-posting)
8. [Errors](#8-errors)

---

## 1. Prerequisites

- **MCP server.** Tools are named `mcp__azure-devops__<tool>`; if they are deferred, load them with ToolSearch `+azure-devops`. The server is on when the git host is `azure` or an org is known (`AZURE_DEVOPS_ORG` or `AZURE_DEVOPS_URL` in `.claude/.env`; `hooks/sync-env.py`, applied from the next session start). If no such tool exists, tell the user to set `AZURE_DEVOPS_URL=https://dev.azure.com/<org>/<project>/_git` in `.claude/.env`, start Claude Code, then restart it once, and stop. If `.mcp.json` has no `azure-devops` entry, they run `bin/sync-projects.sh` in the shared config repo first.
- **Sign-in.** With `AZURE_DEVOPS_PAT` in `.claude/.env` the server uses that token. Without it, the first call in a session opens a browser window for the Microsoft account sign-in: tell the user before that first call.
- **One organization per server.** The server is started for `AZURE_DEVOPS_ORG`. A PR URL from another organization cannot be read: say so and stop.
- **Local clone.** Diffs and code come from a local clone of the PR's repo (Section 2). Without one, stop and tell the user to clone it or run from inside it.

## 2. Resolve the PR and the clone

| Input | Coordinates |
| --- | --- |
| PR URL (`dev.azure.com/<org>/<project>/_git/<repo>/pullrequest/<id>` or `<org>.visualstudio.com/<project>/_git/<repo>/pullrequest/<id>`) | `python3 .claude/tools/azure_repo.py parse-url '<url>'` → `{org, project, repo, pr_id}` |
| Bare number | `python3 .claude/tools/azure_repo.py env` → `{org, project, repo}` (each from its `AZURE_DEVOPS_*` key, else `AZURE_DEVOPS_URL`, else the origin remote); an empty repo means ask the user for the PR URL |
| Branch name or empty | as for a bare number, then the branch lookup below |

Then find the clone and carry its path as a literal `REPO_DIR`:

```bash
python3 .claude/tools/azure_repo.py find-clone --org='<org>' --project='<project>' --repo='<repo>'
```

It looks in the current directory, `$CLAUDE_PROJECT_DIR` and their direct subdirectories, so a multi-repo workspace root works. Run every git command below as `git -C '<REPO_DIR>' …`. The project and repo names may contain spaces: single-quote them, writing each `'` as `'\''`.

**Branch lookup.** `repo_pull_request` with `action: "list"`, `repositoryId: <repo>`, `project: <project>`, `sourceRefName: "refs/heads/<branch>"`, `status: "Active"`. No result → local mode; one → its `pullRequestId`; several → list them and ask the user.

Every MCP call below passes `repositoryId: <repo>`, `project: <project>`, `pullRequestId: <id>`.

## 3. PR metadata → `pr.json`

1. `repo_pull_request` with `action: "get"`. It returns the full PR object.
2. Fetch the PR's commits into the clone:

    ```bash
    git -C '<REPO_DIR>' fetch -q origin '<source branch>' '<target branch>'
    git -C '<REPO_DIR>' cat-file -e '<lastMergeSourceCommit.commitId>^{commit}' && echo present
    ```

    If the source branch is gone, fetch `refs/pull/<id>/merge` instead; its second parent (`FETCH_HEAD^2`) is the source commit.
3. Commit messages: `git -C '<REPO_DIR>' log --format='%B%x1e' '<lastMergeTargetCommit.commitId>..<lastMergeSourceCommit.commitId>'` (records end with `\x1e`).
4. Write `<cache_dir>/pr.json` with the Write tool, never through the shell (the text is the PR author's), in the shape `bb_pr_fetch.sh` / `gh_pr_fetch.sh` print, plus three Azure fields:

| Field | From |
| --- | --- |
| `title` | `title` |
| `description` | `description`, cut to 4000 characters |
| `source_branch` / `dest_branch` | `sourceRefName` / `targetRefName` without `refs/heads/` |
| `source_commit` | `lastMergeSourceCommit.commitId` |
| `author` | `createdBy.displayName` |
| `commit_messages` | step 3, one string per commit |
| `dest_commit` | `lastMergeTargetCommit.commitId` |
| `repo_dir` | `REPO_DIR` |
| `reviewers` | `reviewers[]` as `{name: displayName, vote}`; vote 10 approved, 5 approved with suggestions, 0 none, -5 waiting for author, -10 rejected |

## 4. Comment threads → `comments.json`

`repo_pull_request_thread` with `action: "list"`, `fullResponse: true`, `top: 100`; while a page returns 100 threads, call again with `skip` raised by 100. Keep only threads with at least one comment whose `commentType` is `1` (text) and `isDeleted` is not true; system threads (votes, pushes, status changes) have `commentType` `3`.

Write `<cache_dir>/comments.json` with the Write tool as a list with one entry per kept comment, in the field names `pr-reviewer` already uses for Bitbucket:

| Field | From |
| --- | --- |
| `id` | `"<thread id>.<comment id>"` |
| `thread_id` | thread `id` |
| `parent_id` | comment `parentCommentId` (0 = first comment of the thread) |
| `author.display_name` | comment `author.displayName` |
| `content.raw` | comment `content` |
| `inline.path` | thread `threadContext.filePath` without the leading `/`; absent for a general comment |
| `inline.to` | `threadContext.rightFileStart.line`, else `leftFileStart.line` |
| `created_on` | comment `publishedDate` |
| `thread_status` | thread `status`: 1 active, 2 fixed, 3 won't fix, 4 closed, 5 by design, 6 pending, 0 unknown |

## 5. Unanswered threads → `cr_unanswered_<pr>.json`

For `answer-pr-comments`. On Azure DevOps a reply belongs to a thread, so a thread is the unit. From Section 4's data, a thread is unanswered when all of these hold:

- its status is active (1), pending (6) or unknown (0); fixed, won't fix, closed and by design are settled;
- its last text comment is not by the PR author (`author` in `pr.json`);
- that comment's author is not a bot, by the same keyword rule as `comment-responder`'s Step 1 (`REVIEW_BOT_KEYWORDS`);
- when a reviewer filter was given, that author's name contains it (case-insensitive).

Write `<cache_dir>/cr_unanswered_<pr>.json` with the Write tool, one entry per thread:

```json
[{"id": 123, "kind": "azure", "author": "Jane Doe", "file": "src/App.cs", "line": 42,
  "text": "<the last reviewer comment>", "thread": ["Jane Doe: <earlier comment>", "Author: <reply>"]}]
```

`id` is the thread id; `thread` holds the earlier text comments of that thread, oldest first.

## 6. Diff, diffstat, commits, files

From the clone, using the commits in `pr.json` (single-quote them):

| Need | Command |
| --- | --- |
| Diff | `git -C '<REPO_DIR>' diff '<dest_commit>...<source_commit>'` |
| Diffstat (`changed_files`) | `git -C '<REPO_DIR>' diff --name-status '<dest_commit>...<source_commit>'` |
| Commits | `git -C '<REPO_DIR>' log --oneline '<dest_commit>..<source_commit>'` |
| File at the source commit | `git -C '<REPO_DIR>' show '<source_commit>:<path>'` |
| CI config | `azure-pipelines.yml` or `.azure-pipelines/`, and `.github/workflows/` if present |

Three dots compare against the merge base, as the PR's Files tab does. Finding links: `pr_line_links.py --host=azure --owner='<org>/<project>' --repo='<repo>'`. The Azure PR view has no line URL, so a finding in the diff links to its file in the PR, and `blob_link` holds the line.

## 7. Posting

Only after the user confirms, as the calling skill says. The server's write tools for files, branches and PR state are denied in `settings.json.template`; posting comments asks for approval.

| What | Call: `repo_pull_request_thread_write` with |
| --- | --- |
| Line comment | `action: "create"`, `content`, `filePath: "/<path>"`, `rightFileStartLine: <line>`, `rightFileStartOffset: 1`, `rightFileEndLine: <line>`, `rightFileEndOffset: 1` |
| File comment (file in the PR, no line) | `action: "create"`, `content`, `filePath: "/<path>"` |
| General comment | `action: "create"`, `content` |
| Reply in a thread | `action: "reply"`, `threadId`, `content` |

A line comment must land on a line of the PR's diff (`changed_files` from Section 6 is the gate, as on the other hosts). Before posting replies, list the threads again (Section 4) and skip any thread whose last text comment is now by the PR author, so a retry never double-posts. Report each created thread or comment `id`.

## 8. Errors

| Symptom | Action |
| --- | --- |
| `azure-devops` tools missing | Section 1: set `AZURE_DEVOPS_URL`, start, restart once |
| Sign-in window did not open, or `Failed to obtain Azure DevOps token` | Ask the user to run `/mcp` → `azure-devops` → Reconnect |
| 401 with `AZURE_DEVOPS_PAT` set | The token expired or lacks the Code scope: renew it, or remove it to use the browser sign-in, then restart |
| `TF401019` / repository not found | Project or repo name is wrong, or the account has no access; check the URL |
| 401 / 403 | The signed-in account has no access to that project |
| `find-clone` fails | No local clone: clone it next to the workspace, or run from inside it |
