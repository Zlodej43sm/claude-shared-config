#!/usr/bin/env python3
"""
extract_pr_links — extract Jira ticket keys, Confluence page IDs, and external
repo hints from the combined PR text surface (title, description, branch, commits).

SCHEMA_IN
  stdin   concatenated text (title + description + source_branch + commit_messages)
  env     JIRA_BASE_URL           (used to scope Confluence URL matching)
          CONFLUENCE_BASE_URL     (optional; falls back to JIRA_BASE_URL host)
          PR_REVIEW_CACHE_DIR     (required — per-invocation cache dir, see pr-review SKILL.md Step 0)

SCHEMA_OUT  stdout JSON
  {
    "jira_keys":     [{ "key": "MA-22", "via": "pr-text" | "commit" }, ...],
    "conf_page_ids": [{ "id": "12345",  "via": "pr-text" | "commit" }, ...],
    "external_repos": ["../sibling-service", ...]
  }
  Side-effects: writes $PR_REVIEW_CACHE_DIR/link_registry.json (initialises via-map for downstream tools)

EXIT  0=ok  1=missing-cache-dir
"""

import json, os, re, sys

cache_dir = os.environ.get("PR_REVIEW_CACHE_DIR")
if not cache_dir:
    print("ERROR: PR_REVIEW_CACHE_DIR must be set (see pr-review SKILL.md Step 0)", file=sys.stderr)
    sys.exit(1)
os.makedirs(cache_dir, exist_ok=True)

text = sys.stdin.read()

jira_base = os.environ.get("JIRA_BASE_URL", "")
conf_base = os.environ.get("CONFLUENCE_BASE_URL", jira_base)

# ── helpers ──────────────────────────────────────────────────────────────────

def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else ""

jira_host = _host(jira_base)
conf_host  = _host(conf_base) or jira_host

# Split into "PR text" (everything before a separator marker) vs commit messages.
# Convention: caller prefixes commit messages with "|||COMMITS|||".
if "|||COMMITS|||" in text:
    pr_part, commit_part = text.split("|||COMMITS|||", 1)
else:
    pr_part, commit_part = text, ""

# ── Jira keys ────────────────────────────────────────────────────────────────

seen_keys: dict[str, str] = {}  # key → via

for key in re.findall(r"\b([A-Z]+-\d+)\b", pr_part):
    if key not in seen_keys:
        seen_keys[key] = "pr-text"

for key in re.findall(r"\b([A-Z]+-\d+)\b", commit_part):
    if key not in seen_keys:
        seen_keys[key] = "commit"

# ── Confluence page IDs ───────────────────────────────────────────────────────

seen_pages: dict[str, str] = {}  # page_id → via

for url, pid in re.findall(r"(https?://[^\s\"'>]+/pages/(\d+))", pr_part):
    host = _host(url)
    if (jira_host and host == jira_host) or (conf_host and host == conf_host):
        if pid not in seen_pages:
            seen_pages[pid] = "pr-text"

for url, pid in re.findall(r"(https?://[^\s\"'>]+/pages/(\d+))", commit_part):
    host = _host(url)
    if (jira_host and host == jira_host) or (conf_host and host == conf_host):
        if pid not in seen_pages:
            seen_pages[pid] = "commit"

# ── External repo hints ───────────────────────────────────────────────────────

external_repos: list[str] = []
for path in re.findall(r"\.\./[\w.-]+", text):
    if path not in external_repos:
        external_repos.append(path)
for url in re.findall(r"bitbucket\.org/[\w-]+/[\w-]+", text):
    if url not in external_repos:
        external_repos.append(url)

# ── Output ────────────────────────────────────────────────────────────────────

result = {
    "jira_keys":     [{"key": k, "via": v} for k, v in seen_keys.items()],
    "conf_page_ids": [{"id":  p, "via": v} for p, v in seen_pages.items()],
    "external_repos": external_repos,
}

# Initialise link registry for downstream tools
registry = {f"jira:{k}": v for k, v in seen_keys.items()}
registry.update({f"conf:{p}": v for p, v in seen_pages.items()})
with open(os.path.join(cache_dir, "link_registry.json"), "w") as f:
    json.dump(registry, f)

print(json.dumps(result))
