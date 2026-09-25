#!/usr/bin/env python3
"""
extract_secondary_links — mine already-fetched Jira and Confluence files for
secondary linked resources (remote links, issue links, Confluence body links).

SCHEMA_IN
  --fetched-keys=K1,K2,...   Comma-separated Jira keys already fetched (skip these)
  --fetched-pages=P1,P2,...  Comma-separated Confluence page IDs already fetched (skip)
  Reads  $PR_REVIEW_CACHE_DIR/jira_{KEY}.json              — ticket data
         $PR_REVIEW_CACHE_DIR/jira_remotelinks_{KEY}.json  — Jira remote (web) links
         $PR_REVIEW_CACHE_DIR/conf_{PAGE_ID}.json          — Confluence pages
         $PR_REVIEW_CACHE_DIR/link_registry.json           — via-map written by extract_pr_links.py
  env    JIRA_BASE_URL  CONFLUENCE_BASE_URL (optional)
         PR_REVIEW_CACHE_DIR (required — per-invocation cache dir, see pr-review SKILL.md Step 0)

SCHEMA_OUT  stdout JSON
  {
    "new_jira_keys":     [{ "key": "MA-21", "via": "issue-link:MA-22" }, ...],
    "new_conf_page_ids": [{ "id": "67890",  "via": "jira-remotelink:MA-22" }, ...]
  }
  Side-effects: appends new entries to $PR_REVIEW_CACHE_DIR/link_registry.json

EXIT  0=ok  1=missing-cache-dir
"""

import json, os, re, glob, sys

cache_dir = os.environ.get("PR_REVIEW_CACHE_DIR")
if not cache_dir:
    print("ERROR: PR_REVIEW_CACHE_DIR must be set (see pr-review SKILL.md Step 0)", file=sys.stderr)
    sys.exit(1)
os.makedirs(cache_dir, exist_ok=True)

# ── Args ──────────────────────────────────────────────────────────────────────

fetched_keys:  set[str] = set()
fetched_pages: set[str] = set()

for arg in sys.argv[1:]:
    if arg.startswith("--fetched-keys="):
        fetched_keys = {k.strip() for k in arg.split("=", 1)[1].split(",") if k.strip()}
    elif arg.startswith("--fetched-pages="):
        fetched_pages = {p.strip() for p in arg.split("=", 1)[1].split(",") if p.strip()}

# ── Setup ─────────────────────────────────────────────────────────────────────

jira_base = os.environ.get("JIRA_BASE_URL", "")
conf_base = os.environ.get("CONFLUENCE_BASE_URL", jira_base)

def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else ""

jira_host = _host(jira_base)
conf_host  = _host(conf_base) or jira_host

registry: dict[str, str] = {}
try:
    registry = json.load(open(os.path.join(cache_dir, "link_registry.json")))
except (FileNotFoundError, json.JSONDecodeError):
    pass

new_keys:  list[dict[str, str]] = []
new_pages: list[dict[str, str]] = []

SKIP_LINK_TYPES = {"cloners", "duplicates", "is duplicated by", "is cloned by", "is cloned from"}

def _add_key(key: str, via: str) -> None:
    if key and key not in fetched_keys and f"jira:{key}" not in registry:
        new_keys.append({"key": key, "via": via})
        fetched_keys.add(key)
        registry[f"jira:{key}"] = via

def _add_page(pid: str, via: str) -> None:
    if pid and pid not in fetched_pages and f"conf:{pid}" not in registry:
        new_pages.append({"id": pid, "via": via})
        fetched_pages.add(pid)
        registry[f"conf:{pid}"] = via

# ── 1. Jira remote links → new Confluence page IDs ───────────────────────────

for path in glob.glob(os.path.join(cache_dir, "jira_remotelinks_*.json")):
    key = re.search(r"jira_remotelinks_(.+)\.json$", path)
    if not key:
        continue
    ticket_key = key.group(1)
    try:
        links = json.load(open(path))
        for link in links if isinstance(links, list) else []:
            url = link.get("object", {}).get("url", "")
            m = re.search(r"/pages/(\d+)", url)
            if m:
                host = _host(url)
                if not host or (jira_host and host == jira_host) or (conf_host and host == conf_host):
                    _add_page(m.group(1), f"jira-remotelink:{ticket_key}")
    except (json.JSONDecodeError, OSError):
        pass

# ── 2. Jira issuelinks + parent + epic → new Jira keys ───────────────────────

for path in glob.glob(os.path.join(cache_dir, "jira_*.json")):
    if "remotelinks" in path:
        continue
    key_match = re.search(r"jira_(.+)\.json$", path)
    if not key_match:
        continue
    source_key = key_match.group(1)
    try:
        d = json.load(open(path))
        fields = d.get("fields", {})

        for link in fields.get("issuelinks", []):
            ltype = link.get("type", {}).get("name", "").lower()
            if ltype in SKIP_LINK_TYPES:
                continue
            for direction in ("inwardIssue", "outwardIssue"):
                linked_key = link.get(direction, {}).get("key", "")
                _add_key(linked_key, f"issue-link:{source_key}")

        parent_key = (fields.get("parent") or {}).get("key", "")
        _add_key(parent_key, f"parent:{source_key}")

        # Epic link — classic Jira projects
        epic_key = fields.get("customfield_10014") or ""
        if isinstance(epic_key, str):
            _add_key(epic_key, f"epic:{source_key}")

    except (json.JSONDecodeError, OSError):
        pass

# ── 3. Confluence page bodies → new Confluence page IDs (1 level deep) ────────

for path in glob.glob(os.path.join(cache_dir, "conf_*.json")):
    pid_match = re.search(r"conf_(\d+)\.json$", path)
    if not pid_match:
        continue
    source_pid = pid_match.group(1)
    try:
        d = json.load(open(path))
        body = d.get("body", {}).get("export_view", {}).get("value", "")
        for url, linked_pid in re.findall(r"(https?://[^\s\"'>]+/pages/(\d+))", body):
            host = _host(url)
            if not host or (jira_host and host == jira_host) or (conf_host and host == conf_host):
                _add_page(linked_pid, f"conf-link:{source_pid}")
    except (json.JSONDecodeError, OSError):
        pass

# ── Output ────────────────────────────────────────────────────────────────────

with open(os.path.join(cache_dir, "link_registry.json"), "w") as f:
    json.dump(registry, f)

print(json.dumps({"new_jira_keys": new_keys, "new_conf_page_ids": new_pages}))
