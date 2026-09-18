#!/usr/bin/env bash
# gh_pr_fetch — fetch GitHub PR metadata and commits
#
# SCHEMA_IN
#   $1  PR_NUMBER (integer)
#   env GITHUB_OWNER  GITHUB_REPO  GITHUB_TOKEN
#   env GITHUB_API_URL  (optional, default https://api.github.com — set for GitHub Enterprise)
#
# SCHEMA_OUT  stdout JSON — same shape as bb_pr_fetch.sh, so callers don't
#             need host-specific parsing:
#   {
#     "title":           string,
#     "description":     string   (truncated to 4000 chars),
#     "source_branch":   string,
#     "dest_branch":     string,
#     "source_commit":   string,
#     "author":          string,
#     "commit_messages": [string, ...]
#   }
#   Side-effects: writes /tmp/gh_pr_meta.json  /tmp/gh_pr_commits.json
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail

PR_NUMBER="${1:?ERROR: gh_pr_fetch.sh requires PR_NUMBER as \$1}"
API="${GITHUB_API_URL:-https://api.github.com}"
BASE="${API}/repos/${GITHUB_OWNER}/${GITHUB_REPO}/pulls"
AUTH="Authorization: Bearer ${GITHUB_TOKEN}"

curl -sSL --fail-with-body -H "$AUTH" -H "Accept: application/vnd.github+json" \
  "${BASE}/${PR_NUMBER}"                      -o /tmp/gh_pr_meta.json    &
curl -sSL --fail-with-body -H "$AUTH" -H "Accept: application/vnd.github+json" \
  "${BASE}/${PR_NUMBER}/commits?per_page=100" -o /tmp/gh_pr_commits.json &
wait

python3 - <<'PY'
import json
meta    = json.load(open("/tmp/gh_pr_meta.json"))
commits = json.load(open("/tmp/gh_pr_commits.json"))
print(json.dumps({
    "title":           meta["title"],
    "description":     (meta.get("body") or "")[:4000],
    "source_branch":   meta["head"]["ref"],
    "dest_branch":     meta["base"]["ref"],
    "source_commit":   meta["head"]["sha"],
    "author":          meta["user"]["login"],
    "commit_messages": [c.get("commit", {}).get("message", "") for c in commits],
}))
PY
