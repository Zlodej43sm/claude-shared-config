#!/usr/bin/env bash
# gh_pr_diffstat — list files changed in a GitHub PR
#
# SCHEMA_IN
#   $1  PR_NUMBER
#   env GITHUB_OWNER  GITHUB_REPO  GITHUB_TOKEN
#   env GITHUB_API_URL  (optional, default https://api.github.com)
#
# SCHEMA_OUT  stdout  JSON {"changed_files": ["path/to/file.ts", ...]} — same
#             shape as bb_pr_diffstat.sh
#
# EXIT  0=ok  1=bad-args  2=not-found (404)  3=other-http-error

set -euo pipefail

PR_NUMBER="${1:?ERROR: gh_pr_diffstat.sh requires PR_NUMBER as \$1}"
API="${GITHUB_API_URL:-https://api.github.com}"
BASE="${API}/repos/${GITHUB_OWNER}/${GITHUB_REPO}/pulls/${PR_NUMBER}/files"
AUTH="Authorization: Bearer ${GITHUB_TOKEN}"

TMP_PAGE=$(mktemp)
trap 'rm -f "$TMP_PAGE"' EXIT

PAGE=1
ALL_FILES="[]"
while :; do
  HTTP_STATUS=$(curl -sSL -H "$AUTH" -H "Accept: application/vnd.github+json" \
    -w "%{http_code}" -o "$TMP_PAGE" \
    "${BASE}?per_page=100&page=${PAGE}")

  case "$HTTP_STATUS" in
    200) ;;
    404) echo "ERROR: PR ${PR_NUMBER} not found" >&2; exit 2 ;;
    *)   echo "ERROR: HTTP ${HTTP_STATUS} fetching PR files" >&2; exit 3 ;;
  esac

  PAGE_COUNT=$(python3 -c "import json; print(len(json.load(open('$TMP_PAGE'))))")
  [ "$PAGE_COUNT" -eq 0 ] && break

  ALL_FILES=$(python3 - "$TMP_PAGE" "$ALL_FILES" <<'EOF'
import sys, json
page_file, existing_json = sys.argv[1], sys.argv[2]
with open(page_file) as f:
    d = json.load(f)
existing = json.loads(existing_json)
for entry in d:
    path = entry.get("filename", "")
    if path:
        existing.append(path)
print(json.dumps(existing))
EOF
)

  [ "$PAGE_COUNT" -lt 100 ] && break
  PAGE=$((PAGE + 1))
done

echo "{\"changed_files\": ${ALL_FILES}}"
