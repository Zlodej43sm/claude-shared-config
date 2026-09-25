#!/usr/bin/env bash
# bb_pr_lookup — find open PR by source branch name
#
# SCHEMA_IN
#   $1  BRANCH
#   env BITBUCKET_WORKSPACE  BITBUCKET_REPO_SLUG  BITBUCKET_EMAIL  BITBUCKET_API_TOKEN
#
# SCHEMA_OUT  stdout JSON (exactly one of):
#   { "mode": "pr",        "pr_id": int,  "title": string }
#   { "mode": "local" }
#   { "mode": "ambiguous", "choices": [{ "id": int, "title": string }, ...] }
#   Side-effects: none (uses private per-invocation temp file, removed on exit)
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail

BRANCH="${1:?ERROR: bb_pr_lookup.sh requires BRANCH as \$1}"
BASE="https://api.bitbucket.org/2.0/repositories/${BITBUCKET_WORKSPACE}/${BITBUCKET_REPO_SLUG}/pullrequests"

TMP_LOOKUP=$(mktemp)
trap 'rm -f "$TMP_LOOKUP"' EXIT

curl -sSL --fail-with-body -u "${BITBUCKET_EMAIL}:${BITBUCKET_API_TOKEN}" \
  --get --data-urlencode "q=source.branch.name=\"${BRANCH}\" AND state=\"OPEN\"" \
  "${BASE}" -o "$TMP_LOOKUP"

python3 - "$TMP_LOOKUP" <<'PY'
import json, sys
vals = json.load(open(sys.argv[1])).get("values", [])
if   len(vals) == 0: print(json.dumps({"mode": "local"}))
elif len(vals) == 1: print(json.dumps({"mode": "pr", "pr_id": vals[0]["id"], "title": vals[0]["title"]}))
else:                print(json.dumps({"mode": "ambiguous", "choices": [{"id": v["id"], "title": v["title"]} for v in vals]}))
PY
