---
name: feature-doc
description: Generate a plain-English feature doc from the current branch's Jira ticket and diff — readable by QA, PMs, and tech leads without code knowledge.
---

# feature-doc

You are the entry point for generating a feature documentation file. Your job is to **gather context** (branch, ticket, diff, key files) and then **delegate writing** to a subagent. You do not write the document yourself.

## Input (`args`)

- Empty — auto-detect everything from the current branch.
- A Jira ticket key — `$JIRA_WORKSPACE-13` or bare `13`. Overrides the key parsed from the branch name.
- An output path — any argument containing `/` or ending in `.md` is treated as the output path.
- Both — `$JIRA_WORKSPACE-13 docs/my-feature.md` (key first, path second).

## Step 0 — Load env

```bash
set -a; source .claude/.env; set +a
```

Required: `JIRA_WORKSPACE`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.
If any are missing or placeholder, tell the user and stop.

## Step 1 — Resolve branch and ticket key

```bash
git branch --show-current
```

Parse the ticket key from the branch name using the pattern `[A-Z]+-[0-9]+` (matches any Jira project prefix). The primary prefix is `$JIRA_WORKSPACE` (from `.env`), but branches may carry other project prefixes (e.g. ops, devops, infra keys). Examples:

- `feat/$JIRA_WORKSPACE-13-avro-schema` → `$JIRA_WORKSPACE-13`
- `feat/OPS-5566-sdk-publish` → `OPS-5566`

If the user supplied a key in `args`, use that instead. If neither source yields a key, ask the user.

Determine the output path:

- If the user gave an explicit path, use it.
- Otherwise default to `docs/features/<ticket-key-lowercase>-<branch-slug>.md` where `branch-slug` is the branch name with `/` replaced by `-`, lowercased, with the leading `feat-` or `fix-` stripped. Example: `feat/$JIRA_WORKSPACE-13-avro-schema` → `docs/features/$JIRA_WORKSPACE-13-avro-schema.md` (lowercased at write time).

## Step 2 — Fetch the Jira ticket

Call `mcp__atlassian__jira_get_issue` with the resolved key. If it fails, fall back to JQL search via `mcp__atlassian__jira_search`. Extract:

- Summary (title)
- Status
- Description (full text — this is the "why")
- Acceptance criteria (look for an "Acceptance Criteria" heading inside the description)
- Any linked Confluence page URLs (scan description for links starting with `$CONFLUENCE_BASE_URL`)

If a Confluence URL is found, fetch it via `mcp__atlassian__confluence_get_page` and include the content in the context passed to the subagent.

On MCP unavailability: fall back to curl.

```bash
set -a; source .claude/.env; set +a
curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
  -H "Accept: application/json" \
  "$JIRA_BASE_URL/rest/api/3/issue/$TICKET_KEY?fields=summary,status,description,comment" \
  -o /tmp/jira-issue.json
```

Never echo or log the token.

## Step 3 — Collect the diff and changed files

Run these in parallel:

```bash
# All commits on the branch not yet on develop
git log origin/develop..HEAD --oneline

# Full diff — file paths only first, for sizing
git diff origin/develop...HEAD --name-only

# Stat summary (lines added/removed per file)
git diff origin/develop...HEAD --stat
```

Then read the **full diff** and the **full content** of changed source files (not test files, not lock files, not generated dist). Cap at ~15 files; if more changed, prioritise by: schemas → core logic → config → tests.

## Step 4 — Delegate writing to a subagent

Spawn an Agent with the following prompt. Replace the placeholders with the actual gathered data — inline them directly, do not reference file paths that the subagent cannot read.

---

**Subagent prompt template:**

```
You are a senior technical writer. Your audience ranges from QA engineers and
product managers to engineering leads. Write with clarity and confidence.
Avoid jargon where plain words work. When a technical term is unavoidable, explain it in
parentheses the first time.

Write a feature documentation markdown file for the following implemented feature. The file
must be complete and ready to commit — no placeholders, no "TODO: fill this in".

---
JIRA TICKET
Key: <TICKET_KEY>
Title: <TICKET_SUMMARY>
Status: <TICKET_STATUS>
Description:
<TICKET_DESCRIPTION>

Acceptance Criteria:
<ACCEPTANCE_CRITERIA — or "Not specified" if absent>

Confluence context (if any):
<CONFLUENCE_CONTENT — or "None">
---
GIT COMMITS ON THIS BRANCH
<git log output>
---
CHANGED FILES (stat)
<git diff --stat output>
---
DIFF
<full git diff output — trimmed to ~300 lines if very large; include the most important hunks>
---
KEY SOURCE FILES (full content)
<contents of the most important changed files, labelled by path>
---

Write the document using EXACTLY this structure. Do not add or remove top-level sections.
The tone throughout should be: clear, direct, confident — like a good internal wiki page.

---

# <Feature title — plain English, not the ticket key>

> **Ticket**: <TICKET_KEY> · **Status**: <TICKET_STATUS>

## What this feature does

One or two paragraphs. Explain what the feature is and what it enables, as if the reader has
never seen the codebase. Focus on outcomes, not file names.

## Why it was built

Explain the business or technical problem this solves. Draw from the Jira description and
acceptance criteria. Keep it brief — three to five sentences.

## How it works

Describe the end-to-end flow in plain language. Use a numbered list if there is a clear
sequence of steps. A short diagram in ASCII or mermaid is welcome if it genuinely helps.
Avoid quoting code directly; describe behaviour instead.

## Key components

A compact table or bullet list of what was added or changed, with one-line plain-English
descriptions. Group by layer (schema / server / client / tooling / CI) if the change spans
multiple layers.

| Component | What changed |
|---|---|
| ... | ... |

## How to verify it works

Concrete steps a QA engineer can follow to confirm the feature works as expected. Reference
test commands where relevant (use the test command from CLAUDE.md for this project). Call out any manual
steps that automation does not cover.

## Glossary

Define any domain-specific or project-specific terms used above that a non-engineer might not
know. Omit if there are none.

---

Return ONLY the markdown content of the document — no preamble, no explanation, no code fences
around the entire document. Start directly with the `# ` heading.
```

---

The subagent's response is the **complete markdown content** of the document.

## Step 5 — Write the file

Write the subagent's output verbatim to the resolved output path.

Tell the user:

- The path the file was written to.
- One sentence on what to do next (e.g. "Review the file, then commit it with the rest of the branch changes.").

Do not summarise or repeat the document content in the main conversation.

## What NOT to do

- **Do not write the document yourself** in the main conversation turn. The subagent owns that.
- **Do not expose tokens** in the subagent prompt or logs.
- **Do not invent ticket content** if the Jira fetch fails — tell the user and stop. A document written without the real ticket description is worse than no document.
- **Do not include lock files, dist outputs, or generated files** in the context passed to the subagent. They add noise without adding meaning.
- **Do not create the `docs/features/` directory** if it doesn't exist — the Write tool handles that automatically.
