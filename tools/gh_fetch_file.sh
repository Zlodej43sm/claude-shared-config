#!/usr/bin/env bash
# gh_fetch_file — fetch a source file at a specific commit
#
# SCHEMA_IN
#   $1  COMMIT_HASH (full or short — GitHub's Contents API `ref` accepts either)
#   $2  FILE_PATH   (e.g. src/art_telemetry/activities/persist.py)
#   env GITHUB_OWNER  GITHUB_REPO  GITHUB_TOKEN
#   env GITHUB_API_URL  (optional, default https://api.github.com)
#
# SCHEMA_OUT  stdout  raw file contents — same contract as bb_fetch_file.sh
#
# EXIT  0=ok  1=bad-args  2=not-found (404)  3=other-http-error

set -euo pipefail

COMMIT="${1:?ERROR: gh_fetch_file.sh requires COMMIT_HASH as \$1}"
FILE="${2:?ERROR:   gh_fetch_file.sh requires FILE_PATH as \$2}"

API="${GITHUB_API_URL:-https://api.github.com}"
BASE="${API}/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents"

HTTP_STATUS=$(curl -sSL -w "%{http_code}" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
  --get --data-urlencode "ref=${COMMIT}" \
  "${BASE}/${FILE}" \
  -o /tmp/gh_file_fetch.tmp)

case "$HTTP_STATUS" in
  200)
    python3 -c "
import json, base64
d = json.load(open('/tmp/gh_file_fetch.tmp'))
print(base64.b64decode(d.get('content', '')).decode('utf-8', errors='replace'), end='')
"
    ;;
  404) echo "ERROR: ${FILE} not found at ${COMMIT}" >&2; exit 2 ;;
  *)   echo "ERROR: HTTP ${HTTP_STATUS} for ${FILE}" >&2; exit 3 ;;
esac
