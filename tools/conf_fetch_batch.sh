#!/usr/bin/env bash
# conf_fetch_batch — batch-fetch Confluence pages in parallel
#
# SCHEMA_IN
#   $@  Confluence page IDs (integers)
#   env JIRA_BASE_URL  JIRA_EMAIL  JIRA_API_TOKEN
#   env PR_REVIEW_CACHE_DIR  — per-invocation cache dir (see pr-review SKILL.md Step 0)
#
# SCHEMA_OUT  stdout JSON
#   { "fetched": ["12345", ...], "not_found": ["99999", ...] }
#   An id that is not all digits is never fetched and is listed in not_found.
#   Side-effects: $PR_REVIEW_CACHE_DIR/conf_{PAGE_ID}.json per page
#                 (fields: id, title, space.key, body.export_view.value)
#
# EXIT  0=ok (partial not_found in JSON)  1=credential-error (401/403)  2=missing-cache-dir

set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/curl_auth.sh"
[[ $# -eq 0 ]] && { echo '{"fetched":[],"not_found":[]}'; exit 0; }

: "${PR_REVIEW_CACHE_DIR:?ERROR: PR_REVIEW_CACHE_DIR must be set (see pr-review SKILL.md Step 0)}"
mkdir -p "$PR_REVIEW_CACHE_DIR"

CONF_API="${JIRA_BASE_URL}/wiki/rest/api"
STATUS_DIR=$(mktemp -d)
trap 'rm -rf "$STATUS_DIR"' EXIT

# Ids reach this script from PR text and fetched page bodies; only a numeric id
# may become a URL path segment and part of an output file name.
VALID=() INVALID=()
for ID in "$@"; do
  if [[ "$ID" =~ ^[0-9]+$ ]]; then VALID+=("$ID"); else INVALID+=("$ID"); fi
done
set -- ${VALID[@]+"${VALID[@]}"}

fetch_one() {
  local ID="$1"
  local sc
  sc=$(curl -sS -L -w "%{http_code}" \
    -K <(curl_basic_auth "$JIRA_EMAIL" "$JIRA_API_TOKEN") -H "Accept: application/json" \
    "${CONF_API}/content/${ID}?expand=body.export_view,title,space" \
    -o "${PR_REVIEW_CACHE_DIR}/conf_${ID}.json")
  echo "$sc" > "${STATUS_DIR}/${ID}"
}

for ID in "$@"; do fetch_one "$ID" & done
wait

for ID in "$@"; do
  sc=$(cat "${STATUS_DIR}/${ID}" 2>/dev/null || echo "0")
  if [[ "$sc" == "401" || "$sc" == "403" ]]; then
    echo "ERROR: credential error (${sc}) for Confluence page ${ID}" >&2
    exit 1
  fi
done

python3 - "${STATUS_DIR}" "$@" -- ${INVALID[@]+"${INVALID[@]}"} <<'PY'
import json, sys, os
status_dir = sys.argv[1]
split = sys.argv.index("--")
ids, invalid = sys.argv[2:split], sys.argv[split + 1:]
fetched, not_found = [], list(invalid)
for pid in ids:
    sc = open(os.path.join(status_dir, pid)).read().strip() if os.path.exists(os.path.join(status_dir, pid)) else "0"
    (fetched if sc == "200" else not_found).append(pid)
print(json.dumps({"fetched": fetched, "not_found": not_found}))
PY
