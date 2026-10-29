---
name: pr-description
description: Write or rewrite a pull request title and description in short, plain English that non-native speakers read easily — what the PR does and why, not a tour of the diff. Uses the repo's own PR template, the branch diff, the commits, the Jira ticket and linked PRs as context. No Jira link in the body (the ticket key is in the title). Use whenever a PR is created or its description must be updated. Usage: /pr-description [<pr-number | branch>] [--post]
---

# pr-description

Write the PR title and description. Draft first; post only with `--post` or when the user asks.

## Step 0 — Load env

```bash
set -a; . .claude/.env; set +a
```

`JIRA_WORKSPACE` is the Jira project key (for example `ABC`). Never hardcode a key: always use `$JIRA_WORKSPACE`.

## Step 1 — Gather context (read, don't guess)

- The PR (number or branch): base branch, current title and body, commits. GitHub: `gh api repos/<owner>/<repo>/pulls/<n>`. Bitbucket: the `bb_pr_fetch.sh` tool.
- The diff against the base: `git diff --stat <base>...<head>`, then read the important files.
- The ticket `$JIRA_WORKSPACE-<n>`, from the branch name or title. Use `/get-jira-task` when the reason for the change isn't clear from the code.
- Linked PRs (same ticket, stacked branches) and the deploy or merge order between them.
- Test results from an actual run in this session or in CI. Never invent counts.
- A project recipe, if one exists (for example `docs/recipes/pr-description.md`), for repo-specific templates and rules. Project rules win over this file.

## Step 2 — Title

`<type>($JIRA_WORKSPACE-<n>): <what it does>`. Conventional Commits type, imperative, lower case, no period, at most ~70 characters. The key in the title is the Jira link, so the body has none.

## Step 3 — Body

Use the repo's template (`.github/pull_request_template.md`, any case, or the team template named in the project recipe). Keep its headings and checklist, and fill every section. With no template, use `## What?`, `## Why?`, `## How to verify`.

Writing rules:

- **Simple English.** Short sentences, common words, active voice. One idea per bullet. No idioms, no filler ("This PR aims to…", "comprehensive", "robust", "seamlessly", "it's worth noting").
- **Straight to the point.** Start with what changes for the user, the system or the data, and why it is needed. Don't recap the diff file by file; name a file or function only when the reviewer needs it.
- **Short.** Aim for 10–25 lines of text, without SQL and checklists. Cut anything the reviewer can see in the diff in seconds.
- **Why.** Give the reason when the context shows it: the ticket, a bug, a reviewer request, a limit of a third party.
- **Say what does not change** when a reviewer may worry: contracts, other callers, behaviour.
- **Order and dependencies.** Which PR or migration must go first, in one or two lines. Same repo `#<n>`, other repo `owner/repo#<n>`.
- **DB changes:** the SQL, whether it locks or rewrites a table, and whether it is breaking.
- **Checklist:** tick only what is really there. Give the test counts from a real run.
- **No Jira link** and no `[KEY]: https://…` reference lines. No secrets, tokens, customer data or full payloads.

Before you finish, reread the body and delete every sentence that doesn't help the reviewer decide or test.

## Step 4 — Show, then post

Show the title and body to the user. Post only with `--post` or a clear yes:

- GitHub: `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -f title='<title>' -F body=@<file>`. `gh pr edit` needs the `read:org` scope, which many tokens lack.
- Bitbucket: `PUT …/pullrequests/<id>` with `title` and `description`.

Report the PR link after posting.
