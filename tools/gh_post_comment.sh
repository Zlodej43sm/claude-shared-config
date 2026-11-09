#!/usr/bin/env bash
# gh_post_comment — post a single comment to a GitHub PR
#
# SCHEMA_IN
#   --pr-id=N      PR number (required)
#   --body-file=F  Markdown comment body, read from file F (required, or --body)
#   --body=TEXT    Markdown comment body inline. Prefer --body-file for any text that
#                  quotes code, a PR or a reviewer: in a double-quoted shell argument,
#                  backticks and $(...) run as commands
#   --path=PATH    File path anchor (optional)
#   --line=LINE    Line number anchor (optional; requires --path; when omitted
#                  with --path, falls back to a general comment — see below)
#   --reply-to=ID  Reply threaded under inline review comment ID (optional; no
#                  --path/--line). General (issue) comments have no threading on
#                  GitHub: quote the original in the body instead.
#   env GITHUB_OWNER  GITHUB_REPO  GITHUB_TOKEN
#   env GITHUB_API_URL  (optional, default https://api.github.com)
#
# SCHEMA_OUT  stdout JSON — same shape as bb_post_comment.sh
#   { "id": int, "anchor": "PATH:LINE" | "PATH:file-level" | "general" | "reply:ID" }
#
# Three posting modes. Unlike Bitbucket, GitHub has no true "file-level, no
# line" review-comment anchor — a review comment MUST target a line that is
# actually part of the PR's diff hunks, or the API rejects it (422):
#
#   path + line  -> inline review comment on that line of the PR's head
#                   commit. Requires the head commit SHA, fetched internally
#                   via one extra GET to /pulls/{pr}.
#   path only    -> falls back to a general (issue) comment with the path
#                   prefixed in bold, since GitHub cannot anchor to a file
#                   with no line. Reported anchor is "PATH:file-level" for
#                   caller compatibility with bb_post_comment.sh, but this is
#                   NOT a true file-level GitHub UI anchor like Bitbucket's.
#   neither      -> general PR (issue) comment.
#
# EXIT  0=ok  1=bad-args  2=http-error

set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/curl_auth.sh"

PR_ID="" BODY="" BODY_FILE="" FILE_PATH="" LINE="" REPLY_TO=""
for arg in "$@"; do
  case "$arg" in
    --pr-id=*)     PR_ID="${arg#*=}"     ;;
    --body=*)      BODY="${arg#*=}"      ;;
    --body-file=*) BODY_FILE="${arg#*=}" ;;
    --path=*)      FILE_PATH="${arg#*=}" ;;
    --line=*)      LINE="${arg#*=}"      ;;
    --reply-to=*)  REPLY_TO="${arg#*=}"  ;;
  esac
done

if [[ -n "$BODY_FILE" ]]; then
  [[ -f "$BODY_FILE" ]] || { echo "ERROR: --body-file not found: $BODY_FILE" >&2; exit 1; }
  BODY=$(cat "$BODY_FILE")
fi
[[ -z "$PR_ID" ]] && { echo "ERROR: --pr-id is required" >&2; exit 1; }
[[ -z "$BODY"  ]] && { echo "ERROR: --body-file or --body is required" >&2; exit 1; }
[[ "$PR_ID" =~ ^[0-9]+$ ]] || { echo "ERROR: --pr-id must be a number" >&2; exit 1; }
[[ -z "$REPLY_TO" || "$REPLY_TO" =~ ^[0-9]+$ ]] || { echo "ERROR: --reply-to must be a number" >&2; exit 1; }

API="${GITHUB_API_URL:-https://api.github.com}"
REPO_BASE="${API}/repos/${GITHUB_OWNER}/${GITHUB_REPO}"

if [[ -n "$REPLY_TO" ]]; then
  PAYLOAD=$(python3 - "$BODY" <<'PY'
import json, sys
print(json.dumps({"body": sys.argv[1]}))
PY
)
  RESPONSE=$(curl -sSL --fail-with-body -K <(curl_bearer_auth "$GITHUB_TOKEN") -H "Accept: application/vnd.github+json" \
    -X POST "${REPO_BASE}/pulls/${PR_ID}/comments/${REPLY_TO}/replies" -d "$PAYLOAD")
  ANCHOR="reply:${REPLY_TO}"

elif [[ -n "$FILE_PATH" && -n "$LINE" ]]; then
  COMMIT_ID=$(curl -sSL --fail-with-body -K <(curl_bearer_auth "$GITHUB_TOKEN") -H "Accept: application/vnd.github+json" \
    "${REPO_BASE}/pulls/${PR_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["head"]["sha"])')

  PAYLOAD=$(python3 - "$BODY" "$FILE_PATH" "$LINE" "$COMMIT_ID" <<'PY'
import json, sys
body, path, line, commit_id = sys.argv[1:5]
print(json.dumps({"body": body, "commit_id": commit_id, "path": path, "line": int(line), "side": "RIGHT"}))
PY
)
  RESPONSE=$(curl -sSL --fail-with-body -K <(curl_bearer_auth "$GITHUB_TOKEN") -H "Accept: application/vnd.github+json" \
    -X POST "${REPO_BASE}/pulls/${PR_ID}/comments" -d "$PAYLOAD")
  ANCHOR="${FILE_PATH}:${LINE}"

elif [[ -n "$FILE_PATH" ]]; then
  PAYLOAD=$(python3 - "$BODY" "$FILE_PATH" <<'PY'
import json, sys
body, path = sys.argv[1], sys.argv[2]
print(json.dumps({"body": f"**`{path}`**\n\n{body}"}))
PY
)
  RESPONSE=$(curl -sSL --fail-with-body -K <(curl_bearer_auth "$GITHUB_TOKEN") -H "Accept: application/vnd.github+json" \
    -X POST "${REPO_BASE}/issues/${PR_ID}/comments" -d "$PAYLOAD")
  ANCHOR="${FILE_PATH}:file-level"

else
  PAYLOAD=$(python3 - "$BODY" <<'PY'
import json, sys
print(json.dumps({"body": sys.argv[1]}))
PY
)
  RESPONSE=$(curl -sSL --fail-with-body -K <(curl_bearer_auth "$GITHUB_TOKEN") -H "Accept: application/vnd.github+json" \
    -X POST "${REPO_BASE}/issues/${PR_ID}/comments" -d "$PAYLOAD")
  ANCHOR="general"
fi

python3 - "$RESPONSE" "$ANCHOR" <<'PY'
import json, sys
resp = json.loads(sys.argv[1])
print(json.dumps({"id": resp["id"], "anchor": sys.argv[2]}))
PY
