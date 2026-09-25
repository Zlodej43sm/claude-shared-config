#!/usr/bin/env bash
# jira_fetch_batch — batch-fetch Jira tickets and their remote links in parallel
#
# SCHEMA_IN
#   $@  Jira ticket keys (e.g. MA-22 MA-21)
#   env JIRA_BASE_URL  JIRA_EMAIL  JIRA_API_TOKEN
#   env PR_REVIEW_CACHE_DIR  — per-invocation cache dir (see pr-review SKILL.md Step 0)
#
# SCHEMA_OUT  stdout JSON
#   { "fetched": ["MA-22", ...], "not_found": ["MA-99", ...] }
#   Side-effects:
#     $PR_REVIEW_CACHE_DIR/jira_{KEY}.json               — ticket data (expand=renderedFields)
#     $PR_REVIEW_CACHE_DIR/jira_remotelinks_{KEY}.json   — formally attached web links
#
# EXIT  0=ok (partial not_found in JSON)  1=credential-error (401/403)  2=missing-cache-dir

set -uo pipefail
[[ $# -eq 0 ]] && { echo '{"fetched":[],"not_found":[]}'; exit 0; }

: "${PR_REVIEW_CACHE_DIR:?ERROR: PR_REVIEW_CACHE_DIR must be set (see pr-review SKILL.md Step 0)}"
mkdir -p "$PR_REVIEW_CACHE_DIR"

B64=$(printf '%s:%s' "${JIRA_EMAIL}" "${JIRA_API_TOKEN}" | base64)
STATUS_DIR=$(mktemp -d)

fetch_one() {
  local KEY="$1"
  local sc
  sc=$(curl -sS -L -w "%{http_code}" \
    -H "Authorization: Basic ${B64}" -H "Accept: application/json" \
    "${JIRA_BASE_URL}/rest/api/3/issue/${KEY}?expand=renderedFields" \
    -o "${PR_REVIEW_CACHE_DIR}/jira_${KEY}.json")
  echo "$sc" > "${STATUS_DIR}/${KEY}"

  if [[ "$sc" == "401" || "$sc" == "403" ]]; then return; fi

  curl -sS -L \
    -H "Authorization: Basic ${B64}" -H "Accept: application/json" \
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

python3 - "${STATUS_DIR}" "$@" <<'PY'
import json, sys, os
status_dir = sys.argv[1]
keys = sys.argv[2:]
fetched, not_found = [], []
for key in keys:
    sc_file = os.path.join(status_dir, key)
    sc = open(sc_file).read().strip() if os.path.exists(sc_file) else "0"
    (fetched if sc == "200" else not_found).append(key)
print(json.dumps({"fetched": fetched, "not_found": not_found}))
PY
