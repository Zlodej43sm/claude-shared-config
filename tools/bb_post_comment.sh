#!/usr/bin/env bash
# bb_post_comment — post a single comment to a Bitbucket PR
#
# SCHEMA_IN
#   --pr-id=N      PR id (required)
#   --body=TEXT    Markdown comment body (required)
#   --path=PATH    File path anchor (optional)
#   --line=LINE    Line number anchor (optional; requires --path; when omitted with
#                  --path the comment is file-level, not line-level)
#   env BITBUCKET_WORKSPACE  BITBUCKET_REPO_SLUG  BITBUCKET_EMAIL  BITBUCKET_API_TOKEN
#
# SCHEMA_OUT  stdout JSON
#   { "id": int, "anchor": "PATH:LINE" | "PATH:file-level" | "general" }
#
# Three posting modes:
#   path + line  → inline comment on a specific line in the diff
#   path only    → file-level comment anchored to the file (works even when the
#                  file is not in the PR diff; appears in the Files tab)
#   neither      → general PR comment (top-level conversation thread)
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail

PR_ID="" BODY="" FILE_PATH="" LINE=""
for arg in "$@"; do
  case "$arg" in
    --pr-id=*)   PR_ID="${arg#*=}"    ;;
    --body=*)    BODY="${arg#*=}"     ;;
    --path=*)    FILE_PATH="${arg#*=}" ;;
    --line=*)    LINE="${arg#*=}"     ;;
  esac
done

[[ -z "$PR_ID" ]] && { echo "ERROR: --pr-id is required" >&2; exit 1; }
[[ -z "$BODY"  ]] && { echo "ERROR: --body is required"  >&2; exit 1; }

BASE="https://api.bitbucket.org/2.0/repositories/${BITBUCKET_WORKSPACE}/${BITBUCKET_REPO_SLUG}/pullrequests/${PR_ID}/comments"

PAYLOAD=$(python3 - "$BODY" "$FILE_PATH" "$LINE" <<'PY'
import json, sys
body, path, line = sys.argv[1], sys.argv[2], sys.argv[3]
d = {"content": {"raw": body}}
if path and line:
    d["inline"] = {"to": int(line), "path": path}   # line-level inline
elif path:
    d["inline"] = {"path": path}                     # file-level inline
print(json.dumps(d))
PY
)

RESPONSE=$(curl -sSL --fail-with-body -u "${BITBUCKET_EMAIL}:${BITBUCKET_API_TOKEN}" \
  -X POST "${BASE}" -H "Content-Type: application/json" -d "$PAYLOAD")

python3 - "$RESPONSE" "$FILE_PATH" "$LINE" <<'PY'
import json, sys
resp = json.loads(sys.argv[1])
path, line = sys.argv[2], sys.argv[3]
if path and line:
    anchor = f"{path}:{line}"
elif path:
    anchor = f"{path}:file-level"
else:
    anchor = "general"
print(json.dumps({"id": resp["id"], "anchor": anchor}))
PY
