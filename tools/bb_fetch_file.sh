#!/usr/bin/env bash
# bb_fetch_file — fetch a source file at a specific commit
#
# SCHEMA_IN
#   $1  COMMIT_HASH (full or short)
#   $2  FILE_PATH   (e.g. src/app/module.py)
#   env BITBUCKET_WORKSPACE  BITBUCKET_REPO_SLUG  BITBUCKET_EMAIL  BITBUCKET_API_TOKEN
#
# SCHEMA_OUT  stdout  raw file contents
#
# EXIT  0=ok  1=bad-args  2=not-found (404)  3=other-http-error

set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/curl_auth.sh"

COMMIT="${1:?ERROR: bb_fetch_file.sh requires COMMIT_HASH as \$1}"
FILE="${2:?ERROR:   bb_fetch_file.sh requires FILE_PATH as \$2}"
[[ "$COMMIT" =~ ^[0-9A-Za-z._/-]+$ && "/$COMMIT/" != */../* ]] || { echo "ERROR: invalid COMMIT_HASH" >&2; exit 1; }
[[ "/$FILE/" != */../* ]] || { echo "ERROR: FILE_PATH must not contain a .. segment" >&2; exit 1; }
FILE_ENC=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe="/"))' "$FILE")

BASE="https://api.bitbucket.org/2.0/repositories/${BITBUCKET_WORKSPACE}/${BITBUCKET_REPO_SLUG}/src"

TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT

HTTP_STATUS=$(curl -sSL -w "%{http_code}" \
  -K <(curl_basic_auth "$BITBUCKET_EMAIL" "$BITBUCKET_API_TOKEN") \
  "${BASE}/${COMMIT}/${FILE_ENC}" \
  -o "$TMP_FILE")

case "$HTTP_STATUS" in
  200) cat "$TMP_FILE" ;;
  404) echo "ERROR: ${FILE} not found at ${COMMIT}" >&2; exit 2 ;;
  *)   echo "ERROR: HTTP ${HTTP_STATUS} for ${FILE}" >&2; exit 3 ;;
esac
