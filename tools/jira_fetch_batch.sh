#!/usr/bin/env bash
# jira_fetch_batch — batch-fetch Jira tickets and their remote links in parallel
#
# SCHEMA_IN
#   $@  Jira ticket keys (e.g. PROJ-22 PROJ-21)
#   env JIRA_BASE_URL  JIRA_EMAIL  JIRA_API_TOKEN
#   env PR_REVIEW_CACHE_DIR  — per-invocation cache dir (see pr-review SKILL.md Step 0)
#
# SCHEMA_OUT  stdout JSON
#   { "fetched": ["PROJ-22", ...], "not_found": ["PROJ-99", ...] }
#   A key that is not KEY-123 shaped is never fetched and is listed in not_found.
#   Side-effects:
#     $PR_REVIEW_CACHE_DIR/jira_{KEY}.json               — ticket data (expand=renderedFields)
#     $PR_REVIEW_CACHE_DIR/jira_remotelinks_{KEY}.json   — formally attached web links
#
# EXIT  0=ok (partial not_found in JSON)  1=credential-error (401/403)  2=missing-cache-dir

set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/curl_auth.sh"
[[ $# -eq 0 ]] && { echo '{"fetched":[],"not_found":[]}'; exit 0; }

: "${PR_REVIEW_CACHE_DIR:?ERROR: PR_REVIEW_CACHE_DIR must be set (see pr-review SKILL.md Step 0)}"
mkdir -p "$PR_REVIEW_CACHE_DIR"

STATUS_DIR=$(mktemp -d)
trap 'rm -rf "$STATUS_DIR"' EXIT

# Keys reach this script from PR text and Jira API fields; only a well-formed key
# may become a URL path segment and part of an output file name.
VALID=() INVALID=()
for KEY in "$@"; do
  if [[ "$KEY" =~ ^[A-Za-z][A-Za-z0-9_]*-[0-9]+$ ]]; then VALID+=("$KEY"); else INVALID+=("$KEY"); fi
done
set -- ${VALID[@]+"${VALID[@]}"}

fetch_one() {
  local KEY="$1"
  local sc
  sc=$(curl -sS -L -w "%{http_code}" \
    -K <(curl_basic_auth "$JIRA_EMAIL" "$JIRA_API_TOKEN") -H "Accept: application/json" \
    "${JIRA_BASE_URL}/rest/api/3/issue/${KEY}?expand=renderedFields" \
    -o "${PR_REVIEW_CACHE_DIR}/jira_${KEY}.json")
  echo "$sc" > "${STATUS_DIR}/${KEY}"

  if [[ "$sc" == "401" || "$sc" == "403" ]]; then return; fi

  curl -sS -L \
    -K <(curl_basic_auth "$JIRA_EMAIL" "$JIRA_API_TOKEN") -H "Accept: application/json" \
    "${JIRA_BASE_URL}/rest/api/3/issue/${KEY}/remotelink" \
    -o "${PR_REVIEW_CACHE_DIR}/jira_remotelinks_${KEY}.json" &>/dev/null || true
}

for KEY in "$@"; do fetch_one "$KEY" & done
wait

# Credential error check (any key with 401/403 is fatal)
for KEY in "$@"; do
  sc=$(cat "${STATUS_DIR}/${KEY}" 2>/dev/null || echo "0")
  if [[ "$sc" == "401" || "$sc" == "403" ]]; then
    echo "ERROR: credential error (${sc}) for Jira ticket ${KEY}" >&2
    exit 1
  fi
done

python3 - "${STATUS_DIR}" "$@" -- ${INVALID[@]+"${INVALID[@]}"} <<'PY'
import json, sys, os
status_dir = sys.argv[1]
split = sys.argv.index("--")
keys, invalid = sys.argv[2:split], sys.argv[split + 1:]
fetched, not_found = [], list(invalid)
for key in keys:
    sc_file = os.path.join(status_dir, key)
    sc = open(sc_file).read().strip() if os.path.exists(sc_file) else "0"
    (fetched if sc == "200" else not_found).append(key)
print(json.dumps({"fetched": fetched, "not_found": not_found}))
PY
