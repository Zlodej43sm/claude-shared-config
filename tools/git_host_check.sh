#!/usr/bin/env bash
# git_host_check — verify the git-hosting connection for this project
#
# SCHEMA_IN
#   env GIT_HOST (optional)  BITBUCKET_WORKSPACE  BITBUCKET_REPO_SLUG  BITBUCKET_EMAIL  BITBUCKET_API_TOKEN
#   env GITHUB_OWNER  GITHUB_REPO  GITHUB_TOKEN  GITHUB_API_URL (optional)
#   reads $CLAUDE_PROJECT_DIR/.mcp.json (or ./.mcp.json) to report MCP wiring
#
# SCHEMA_OUT  stdout JSON
#   { "host": "bitbucket"|"github"|null,
#     "env":  { "missing": [KEY...], "placeholder": [KEY...], "unresolved_op": [KEY...] },
#     "api":  { "checked": bool, "status": int|null, "ok": bool, "detail": string },
#     "mcp":  { "file": bool, "expected": "github"|null, "configured": bool } }
#   Never prints a credential value. Read-only (one GET against the repo endpoint).
#
# EXIT  0=connected  1=problem (see JSON)  2=host undeterminable

set -uo pipefail

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST=$("$TOOLS_DIR/detect_git_host.sh" 2>/dev/null) || {
  echo '{"host":null,"env":{"missing":[],"placeholder":[],"unresolved_op":[]},"api":{"checked":false,"status":null,"ok":false,"detail":"git host undeterminable - set GIT_HOST=bitbucket|github"},"mcp":{"file":false,"expected":null,"configured":false}}'
  exit 2
}
export HOST

python3 - <<'PY'
import base64, json, os, urllib.error, urllib.request
from pathlib import Path

host = os.environ["HOST"]
keys = {
    "bitbucket": ["BITBUCKET_WORKSPACE", "BITBUCKET_REPO_SLUG", "BITBUCKET_EMAIL", "BITBUCKET_API_TOKEN"],
    "github": ["GITHUB_OWNER", "GITHUB_REPO", "GITHUB_TOKEN"],
}[host]
PLACEHOLDERS = ("replace-with-", "your-", "your.name@", "_here")

missing, placeholder, unresolved = [], [], []
for k in keys:
    v = os.environ.get(k, "")
    if not v:
        missing.append(k)
    elif v.startswith("op://"):
        unresolved.append(k)
    elif any(p in v.lower() for p in PLACEHOLDERS):
        placeholder.append(k)

api = {"checked": False, "status": None, "ok": False, "detail": ""}
if missing or placeholder or unresolved:
    api["detail"] = "skipped: fix env keys first"
else:
    if host == "github":
        base = os.environ.get("GITHUB_API_URL") or "https://api.github.com"
        url = f"{base}/repos/{os.environ['GITHUB_OWNER']}/{os.environ['GITHUB_REPO']}"
        headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
    else:
        url = ("https://api.bitbucket.org/2.0/repositories/"
               f"{os.environ['BITBUCKET_WORKSPACE']}/{os.environ['BITBUCKET_REPO_SLUG']}")
        cred = base64.b64encode(f"{os.environ['BITBUCKET_EMAIL']}:{os.environ['BITBUCKET_API_TOKEN']}".encode()).decode()
        headers = {"Authorization": f"Basic {cred}"}
    api["checked"] = True
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
            api["status"] = r.status
            api["ok"] = True
            body = json.load(r)
            if host == "github" and isinstance(body.get("permissions"), dict):
                perms = body["permissions"]
                api["detail"] = "repo reachable; token permissions: " + ", ".join(k for k, v in perms.items() if v)
            else:
                api["detail"] = "repo reachable"
    except urllib.error.HTTPError as e:
        api["status"] = e.code
        api["detail"] = {
            401: "credentials rejected (401) - check the token" + ("/email" if host == "bitbucket" else ""),
            403: "forbidden (403) - token lacks access/scope for this repo",
            404: "not found (404) - check " + ("workspace/slug" if host == "bitbucket" else "owner/repo"),
        }.get(e.code, f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        api["detail"] = f"network error: {getattr(e, 'reason', e)}"

project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
mcp = {"file": False, "expected": "github" if host == "github" else None, "configured": host != "github"}
mcp_path = project / ".mcp.json"
if mcp_path.is_file():
    mcp["file"] = True
    try:
        servers = json.loads(mcp_path.read_text()).get("mcpServers", {})
        if host == "github":
            mcp["configured"] = "github" in servers
    except json.JSONDecodeError:
        mcp["configured"] = False

print(json.dumps({
    "host": host,
    "env": {"missing": missing, "placeholder": placeholder, "unresolved_op": unresolved},
    "api": api,
    "mcp": mcp,
}))
ok = api["ok"] and mcp["configured"]
raise SystemExit(0 if ok else 1)
PY
