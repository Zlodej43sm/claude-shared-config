#!/usr/bin/env bash
# gh_pr_lookup — find open PR by source branch name
#
# SCHEMA_IN
#   $1  BRANCH
#   env GITHUB_OWNER  GITHUB_REPO  GITHUB_TOKEN
#   env GITHUB_API_URL  (optional, default https://api.github.com)
#
# SCHEMA_OUT  stdout JSON (exactly one of) — same shape as bb_pr_lookup.sh:
#   { "mode": "pr",        "pr_id": int,  "title": string }
#   { "mode": "local" }
#   { "mode": "ambiguous", "choices": [{ "id": int, "title": string }, ...] }
#   Side-effects: writes /tmp/gh_pr_lookup.json
#
# NOTE: GitHub's `head` filter requires "<owner>:<branch>" and assumes the
# branch lives in $GITHUB_OWNER/$GITHUB_REPO itself (not a fork) — the same
# same-repo assumption that bb_pr_lookup.sh makes for Bitbucket.
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail

BRANCH="${1:?ERROR: gh_pr_lookup.sh requires BRANCH as \$1}"
API="${GITHUB_API_URL:-https://api.github.com}"
BASE="${API}/repos/${GITHUB_OWNER}/${GITHUB_REPO}/pulls"

curl -sSL --fail-with-body -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
  --get --data-urlencode "head=${GITHUB_OWNER}:${BRANCH}" --data-urlencode "state=open" \
  "${BASE}" -o /tmp/gh_pr_lookup.json

python3 - <<'PY'
import json
vals = json.load(open("/tmp/gh_pr_lookup.json"))
if   len(vals) == 0: print(json.dumps({"mode": "local"}))
elif len(vals) == 1: print(json.dumps({"mode": "pr", "pr_id": vals[0]["number"], "title": vals[0]["title"]}))
else:                print(json.dumps({"mode": "ambiguous", "choices": [{"id": v["number"], "title": v["title"]} for v in vals]}))
PY
