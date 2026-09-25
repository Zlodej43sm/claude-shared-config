#!/usr/bin/env bash
# bb_pr_fetch — fetch Bitbucket PR metadata and commits
#
# SCHEMA_IN
#   $1  PR_ID (integer)
#   env BITBUCKET_WORKSPACE  BITBUCKET_REPO_SLUG  BITBUCKET_EMAIL  BITBUCKET_API_TOKEN
#
# SCHEMA_OUT  stdout JSON
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

PR_ID="${1:?ERROR: bb_pr_fetch.sh requires PR_ID as \$1}"
BASE="https://api.bitbucket.org/2.0/repositories/${BITBUCKET_WORKSPACE}/${BITBUCKET_REPO_SLUG}/pullrequests"
AUTH="${BITBUCKET_EMAIL}:${BITBUCKET_API_TOKEN}"

TMP_META=$(mktemp)
TMP_COMMITS=$(mktemp)
trap 'rm -f "$TMP_META" "$TMP_COMMITS"' EXIT

curl -sSL --fail-with-body -u "$AUTH" "${BASE}/${PR_ID}"                     -o "$TMP_META"    &
curl -sSL --fail-with-body -u "$AUTH" "${BASE}/${PR_ID}/commits?pagelen=50"  -o "$TMP_COMMITS" &
wait

python3 - "$TMP_META" "$TMP_COMMITS" <<'PY'
import json, sys
meta    = json.load(open(sys.argv[1]))
commits = json.load(open(sys.argv[2]))
print(json.dumps({
    "title":           meta["title"],
    "description":     (meta.get("description") or "")[:4000],
    "source_branch":   meta["source"]["branch"]["name"],
    "dest_branch":     meta["destination"]["branch"]["name"],
    "source_commit":   meta["source"]["commit"]["hash"],
    "author":          meta["author"]["display_name"],
    "commit_messages": [c.get("message", "") for c in commits.get("values", [])],
}))
PY
