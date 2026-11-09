#!/usr/bin/env bash
# bb_pr_diffstat — list files changed in a Bitbucket PR
#
# SCHEMA_IN
#   $1  PR_ID
#   env BITBUCKET_WORKSPACE  BITBUCKET_REPO_SLUG  BITBUCKET_EMAIL  BITBUCKET_API_TOKEN
#
# SCHEMA_OUT  stdout  JSON {"changed_files": ["path/to/file.ts", ...]}
#
# EXIT  0=ok  1=bad-args  2=not-found (404)  3=other-http-error

set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/curl_auth.sh"

PR_ID="${1:?ERROR: bb_pr_diffstat.sh requires PR_ID as \$1}"
[[ "$PR_ID" =~ ^[0-9]+$ ]] || { echo "ERROR: PR_ID must be a number" >&2; exit 1; }

BASE="https://api.bitbucket.org/2.0/repositories/${BITBUCKET_WORKSPACE}/${BITBUCKET_REPO_SLUG}"
TMP_BODY=$(mktemp)
TMP_PAGE=$(mktemp)
trap 'rm -f "$TMP_BODY" "$TMP_PAGE"' EXIT

# Fetch PR metadata to get source and destination commits
HTTP_STATUS=$(curl -sSL \
  -K <(curl_basic_auth "$BITBUCKET_EMAIL" "$BITBUCKET_API_TOKEN") \
  -w "%{http_code}" \
  -o "$TMP_BODY" \
  "${BASE}/pullrequests/${PR_ID}")

case "$HTTP_STATUS" in
  200) ;;
  404) echo "ERROR: PR ${PR_ID} not found" >&2; exit 2 ;;
  *)   echo "ERROR: HTTP ${HTTP_STATUS} fetching PR metadata" >&2; exit 3 ;;
esac

SOURCE_COMMIT=$(python3 -c "import sys,json; d=json.load(open('$TMP_BODY')); print(d['source']['commit']['hash'])")
DEST_COMMIT=$(python3   -c "import sys,json; d=json.load(open('$TMP_BODY')); print(d['destination']['commit']['hash'])")

# Paginate through the diffstat and collect all changed file paths
NEXT_URL="${BASE}/diffstat/${SOURCE_COMMIT}..${DEST_COMMIT}?pagelen=100"
ALL_FILES="[]"

while [ -n "$NEXT_URL" ]; do
  # `next` comes from the API response: send the credentials only back to this repo's endpoints
  case "$NEXT_URL" in
    "${BASE}/"*) ;;
    *) echo "ERROR: refusing to follow pagination URL outside ${BASE}/: ${NEXT_URL}" >&2; exit 3 ;;
  esac
  HTTP_STATUS=$(curl -sSL \
    -K <(curl_basic_auth "$BITBUCKET_EMAIL" "$BITBUCKET_API_TOKEN") \
    -w "%{http_code}" \
    -o "$TMP_PAGE" \
    "$NEXT_URL")

  case "$HTTP_STATUS" in
    200) ;;
    *)   echo "ERROR: HTTP ${HTTP_STATUS} fetching diffstat page" >&2; exit 3 ;;
  esac

  ALL_FILES=$(python3 - "$TMP_PAGE" "$ALL_FILES" <<'EOF'
import sys, json
page_file, existing_json = sys.argv[1], sys.argv[2]
with open(page_file) as f:
    d = json.load(f)
existing = json.loads(existing_json)
for entry in d.get('values', []):
    path = (entry.get('new') or entry.get('old') or {}).get('path', '')
    if path:
        existing.append(path)
print(json.dumps(existing))
EOF
)

  NEXT_URL=$(python3 - "$TMP_PAGE" <<'EOF'
import sys, json
with open(sys.argv[1]) as f:
    d = json.load(f)
print(d.get('next', ''))
EOF
)
done

echo "{\"changed_files\": ${ALL_FILES}}"
