#!/usr/bin/env bash
# bb_post_comment — post a single comment to a Bitbucket PR
#
# SCHEMA_IN
#   --pr-id=N      PR id (required)
#   --body-file=F  Markdown comment body, read from file F (required, or --body)
#   --body=TEXT    Markdown comment body inline. Prefer --body-file for any text that
#                  quotes code, a PR or a reviewer: in a double-quoted shell argument,
#                  backticks and $(...) run as commands
#   --path=PATH    File path anchor (optional)
#   --line=LINE    Line number anchor (optional; requires --path; when omitted with
#                  --path the comment is file-level, not line-level)
#   --parent=ID    Reply threaded under comment ID (optional; no --path/--line)
#   env BITBUCKET_WORKSPACE  BITBUCKET_REPO_SLUG  BITBUCKET_EMAIL  BITBUCKET_API_TOKEN
#
# SCHEMA_OUT  stdout JSON
#   { "id": int, "anchor": "PATH:LINE" | "PATH:file-level" | "general" | "reply:ID" }
#
# Three posting modes:
#   path + line  → inline comment on a specific line in the diff
#   path only    → file-level comment anchored to the file (works even when the
#                  file is not in the PR diff; appears in the Files tab)
#   neither      → general PR comment (top-level conversation thread)
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/curl_auth.sh"

PR_ID="" BODY="" BODY_FILE="" FILE_PATH="" LINE="" PARENT=""
for arg in "$@"; do
  case "$arg" in
    --pr-id=*)     PR_ID="${arg#*=}"     ;;
    --body=*)      BODY="${arg#*=}"      ;;
    --body-file=*) BODY_FILE="${arg#*=}" ;;
    --path=*)      FILE_PATH="${arg#*=}" ;;
    --line=*)      LINE="${arg#*=}"      ;;
    --parent=*)    PARENT="${arg#*=}"    ;;
  esac
done

if [[ -n "$BODY_FILE" ]]; then
  [[ -f "$BODY_FILE" ]] || { echo "ERROR: --body-file not found: $BODY_FILE" >&2; exit 1; }
  BODY=$(cat "$BODY_FILE")
fi
[[ -z "$PR_ID" ]] && { echo "ERROR: --pr-id is required" >&2; exit 1; }
[[ -z "$BODY"  ]] && { echo "ERROR: --body-file or --body is required" >&2; exit 1; }
[[ "$PR_ID" =~ ^[0-9]+$ ]] || { echo "ERROR: --pr-id must be a number" >&2; exit 1; }
[[ -z "$PARENT" || "$PARENT" =~ ^[0-9]+$ ]] || { echo "ERROR: --parent must be a number" >&2; exit 1; }

BASE="https://api.bitbucket.org/2.0/repositories/${BITBUCKET_WORKSPACE}/${BITBUCKET_REPO_SLUG}/pullrequests/${PR_ID}/comments"

PAYLOAD=$(python3 - "$BODY" "$FILE_PATH" "$LINE" "$PARENT" <<'PY'
import json, sys
body, path, line, parent = sys.argv[1:5]
d = {"content": {"raw": body}}
if parent:
    d["parent"] = {"id": int(parent)}                # threaded reply
elif path and line:
    d["inline"] = {"to": int(line), "path": path}   # line-level inline
elif path:
    d["inline"] = {"path": path}                     # file-level inline
print(json.dumps(d))
PY
)

RESPONSE=$(curl -sSL --fail-with-body -K <(curl_basic_auth "$BITBUCKET_EMAIL" "$BITBUCKET_API_TOKEN") \
  -X POST "${BASE}" -H "Content-Type: application/json" -d "$PAYLOAD")

python3 - "$RESPONSE" "$FILE_PATH" "$LINE" "$PARENT" <<'PY'
import json, sys
resp = json.loads(sys.argv[1])
path, line, parent = sys.argv[2], sys.argv[3], sys.argv[4]
if parent:
    anchor = f"reply:{parent}"
elif path and line:
    anchor = f"{path}:{line}"
elif path:
    anchor = f"{path}:file-level"
else:
    anchor = "general"
print(json.dumps({"id": resp["id"], "anchor": anchor}))
PY
