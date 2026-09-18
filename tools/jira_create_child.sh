#!/usr/bin/env bash
# jira_create_child — create a single Jira issue, optionally as a child of a parent issue
#
# SCHEMA_IN
#   --summary=TEXT         Issue summary (required)
#   --description=TEXT     Plain-text description; converted to Atlassian Document
#                          Format, one paragraph per blank-line-separated block (optional)
#   --parent=KEY           Parent issue key, e.g. MA-29 (optional — omit for a top-level issue)
#   --issuetype=NAME       Issue type name (optional; default "Task")
#   --project=KEY          Project key (optional; default $JIRA_WORKSPACE)
#   --reporter=ACCOUNT_ID  Reporter accountId (optional; resolved via /myself when omitted —
#                          callers creating several issues should resolve this once and pass
#                          it down instead of paying the extra round trip per item)
#   --assignee=ACCOUNT_ID  Assignee accountId (optional; issue is left unassigned when omitted)
#   --dry-run              Print the built request payload and exit; no POST is sent
#   env JIRA_BASE_URL  JIRA_EMAIL  JIRA_API_TOKEN  JIRA_WORKSPACE
#
# SCHEMA_OUT  stdout JSON
#   { "key": "MA-157", "self": "https://<site>/browse/MA-157" }
#   --dry-run prints the built request payload instead, unposted.
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail

SUMMARY="" DESCRIPTION="" PARENT="" ISSUETYPE="Task" PROJECT="${JIRA_WORKSPACE:-}" REPORTER="" ASSIGNEE="" DRY_RUN=""
for arg in "$@"; do
  case "$arg" in
    --summary=*)     SUMMARY="${arg#*=}"     ;;
    --description=*) DESCRIPTION="${arg#*=}" ;;
    --parent=*)      PARENT="${arg#*=}"      ;;
    --issuetype=*)   ISSUETYPE="${arg#*=}"   ;;
    --project=*)     PROJECT="${arg#*=}"     ;;
    --reporter=*)    REPORTER="${arg#*=}"    ;;
    --assignee=*)    ASSIGNEE="${arg#*=}"    ;;
    --dry-run)       DRY_RUN=1               ;;
  esac
done

[[ -z "$SUMMARY" ]] && { echo "ERROR: --summary is required" >&2; exit 1; }
[[ -z "$PROJECT" ]] && { echo "ERROR: --project or \$JIRA_WORKSPACE is required" >&2; exit 1; }
if [[ -z "${JIRA_BASE_URL:-}" || -z "${JIRA_EMAIL:-}" || -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "ERROR: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN must be set" >&2
  exit 1
fi

if [[ -z "$REPORTER" ]]; then
  REPORTER=$(curl -sS --fail-with-body -u "${JIRA_EMAIL}:${JIRA_API_TOKEN}" \
    "${JIRA_BASE_URL}/rest/api/3/myself" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["accountId"])')
fi

PAYLOAD=$(python3 - "$SUMMARY" "$DESCRIPTION" "$PARENT" "$ISSUETYPE" "$PROJECT" "$REPORTER" "$ASSIGNEE" <<'PY'
import json, sys

summary, description, parent, issuetype, project, reporter, assignee = sys.argv[1:8]

def to_adf(text):
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs:
        return None
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p.replace("\n", " ")}]}
            for p in paragraphs
        ],
    }

fields = {
    "project": {"key": project},
    "issuetype": {"name": issuetype},
    "summary": summary,
    "reporter": {"accountId": reporter},
}
if parent:
    fields["parent"] = {"key": parent}
if assignee:
    fields["assignee"] = {"accountId": assignee}
adf = to_adf(description)
if adf:
    fields["description"] = adf

print(json.dumps({"fields": fields}))
PY
)

if [[ -n "$DRY_RUN" ]]; then
  echo "$PAYLOAD"
  exit 0
fi

RESPONSE=$(curl -sS --fail-with-body -u "${JIRA_EMAIL}:${JIRA_API_TOKEN}" \
  -X POST "${JIRA_BASE_URL}/rest/api/3/issue" -H "Content-Type: application/json" -d "$PAYLOAD") \
  || { echo "ERROR: Jira create failed — response: ${RESPONSE:-<none>}" >&2; exit 2; }

python3 - "$RESPONSE" "$JIRA_BASE_URL" <<'PY'
import json, sys
resp = json.loads(sys.argv[1])
base = sys.argv[2]
print(json.dumps({"key": resp["key"], "self": f"{base}/browse/{resp['key']}"}))
PY
