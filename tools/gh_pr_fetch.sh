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
#   Side-effects: none (uses private per-invocation temp files, removed on exit)
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail

PR_NUMBER="${1:?ERROR: gh_pr_fetch.sh requires PR_NUMBER as \$1}"
API="${GITHUB_API_URL:-https://api.github.com}"
BASE="${API}/repos/${GITHUB_OWNER}/${GITHUB_REPO}/pulls"
AUTH="Authorization: Bearer ${GITHUB_TOKEN}"

TMP_META=$(mktemp)
TMP_COMMITS=$(mktemp)
trap 'rm -f "$TMP_META" "$TMP_COMMITS"' EXIT

curl -sSL --fail-with-body -H "$AUTH" -H "Accept: application/vnd.github+json" \
  "${BASE}/${PR_NUMBER}"                      -o "$TMP_META"    &
curl -sSL --fail-with-body -H "$AUTH" -H "Accept: application/vnd.github+json" \
  "${BASE}/${PR_NUMBER}/commits?per_page=100" -o "$TMP_COMMITS" &
wait

python3 - "$TMP_META" "$TMP_COMMITS" <<'PY'
import json, sys
meta    = json.load(open(sys.argv[1]))
commits = json.load(open(sys.argv[2]))
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
