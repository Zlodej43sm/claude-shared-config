#!/usr/bin/env python3
"""
build_prefetch_context — build the ---PREFETCHED_CONTEXT_START--- block from
all fetched Jira and Confluence files.

SCHEMA_IN
  --pr-id=N
  --title=TEXT
  --source-branch=BRANCH
  --dest-branch=BRANCH
  --source-commit=HASH
  --author=NAME
  Reads  /tmp/jira_{KEY}.json     — ticket data (all, skipping remotelinks files)
         /tmp/conf_{PAGE_ID}.json — Confluence pages
         /tmp/link_registry.json  — via-map (key: "jira:KEY"|"conf:ID", value: via)
  env    JIRA_BASE_URL  (for constructing Confluence page URLs)

SCHEMA_OUT  stdout
  ---PREFETCHED_CONTEXT_START---
  ...
  ---PREFETCHED_CONTEXT_END---

EXIT  0=ok  1=bad-args
"""

import glob, html, json, os, re, sys
from html.parser import HTMLParser

# ── Args ──────────────────────────────────────────────────────────────────────

args: dict[str, str] = {}
for arg in sys.argv[1:]:
    if "=" in arg:
        k, v = arg.lstrip("-").split("=", 1)
        args[k] = v

required = ["pr-id", "title", "source-branch", "dest-branch", "source-commit", "author"]
missing = [r for r in required if r not in args]
if missing:
    print(f"ERROR: missing args: {', '.join('--' + m for m in missing)}", file=sys.stderr)
    sys.exit(1)

jira_base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")

# ── Load via-map ──────────────────────────────────────────────────────────────

registry: dict[str, str] = {}
try:
    registry = json.load(open("/tmp/link_registry.json"))
except (FileNotFoundError, json.JSONDecodeError):
    pass

def via(resource_key: str) -> str:
    return registry.get(resource_key, "unknown")

# ── HTML → plain text ─────────────────────────────────────────────────────────

class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
    def handle_data(self, data: str) -> None:
        self.parts.append(data)

def strip_html(raw: str) -> str:
    s = _Stripper()
    s.feed(raw)
    text = " ".join(s.parts)
    return re.sub(r"\s{3,}", "\n\n", text).strip()

# ── Confluence page classification ────────────────────────────────────────────

SPEC_WORDS    = {"specification", "design", "architecture", "data model", "schema",
                 "flow", "contract", "interface", "adr"}
AC_WORDS      = {"acceptance criteria", " ac ", "definition of done", "requirements"}
RUNBOOK_WORDS = {"runbook", "oncall", "playbook", "incident"}

def classify_page(title: str, snippet: str) -> str:
    combined = (title + " " + snippet[:500]).lower()
    types: list[str] = []
    if any(w in combined for w in SPEC_WORDS):    types.append("spec")
    if any(w in combined for w in AC_WORDS):      types.append("ac")
    if any(w in combined for w in RUNBOOK_WORDS): types.append("runbook")
    return "/".join(types) if types else "reference"

# ── ADF → plain text (Jira description) ──────────────────────────────────────

def adf_text(node: object) -> str:
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    t = node.get("type", "")
    content = node.get("content", [])
    text = node.get("text", "")
    if t == "text":        return text
    if t == "hardBreak":   return "\n"
    if t == "paragraph":   return adf_text(content) + "\n"
    if t in ("bulletList", "orderedList", "listItem"): return adf_text(content)
    if t == "heading":     return "#" * node.get("attrs", {}).get("level", 1) + " " + adf_text(content) + "\n"
    if t == "codeBlock":   return "```\n" + adf_text(content) + "\n```\n"
    if t == "inlineCard":  return node.get("attrs", {}).get("url", "")
    return adf_text(content)

def extract_ac(description_text: str) -> list[str]:
    lines = description_text.splitlines()
    in_ac = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.search(r"acceptance.criteria|definition.of.done", stripped, re.I):
            in_ac = True
            continue
        if in_ac:
            if re.match(r"^#{1,3} ", stripped) and not re.search(r"acceptance|criteria", stripped, re.I):
                break
            if stripped.startswith("- "):
                items.append(stripped[2:])
    return items

# ── Cross-service signal detection ────────────────────────────────────────────

SIGNAL_PATTERNS = [
    ("kafka-topic",     re.compile(r'\b([\w-]+-(?:topic|events?|snapshots?|stream))\b')),
    ("avro-schema",     re.compile(r'\b([\w.-]+\.avsc)\b')),
    ("s3-path",         re.compile(r's3://[\w.-]+(?:/[\w./-]*)?')),
    ("external-repo",   re.compile(r'\.\./[\w.-]+|bitbucket\.org/[\w-]+/[\w-]+')),
]

def detect_signals(texts: list[tuple[str, str]]) -> list[str]:
    seen: set[str] = set()
    signals: list[str] = []
    for pattern_type, pattern in SIGNAL_PATTERNS:
        for text, location in texts:
            for match in pattern.finditer(text):
                key = f"{pattern_type}:{match.group(0)}"
                if key not in seen:
                    seen.add(key)
                    signals.append(f"  - {pattern_type}: `{match.group(0)}` — found in {location}")
    return signals

# ── Build output ──────────────────────────────────────────────────────────────

lines: list[str] = []
lines.append("---PREFETCHED_CONTEXT_START---")
lines.append(f"PR: #{args['pr-id']} — {args['title']}")
lines.append(f"Source: {args['source-branch']} → {args['dest-branch']}")
lines.append(f"Author: {args['author']}")
lines.append(f"Commit: {args['source-commit'][:8]}")
lines.append("")

signal_texts: list[tuple[str, str]] = []

# ── Jira tickets ──────────────────────────────────────────────────────────────

for path in sorted(glob.glob("/tmp/jira_*.json")):
    if "remotelinks" in path:
        continue
    key_match = re.search(r"jira_(.+)\.json$", path)
    if not key_match:
        continue
    ticket_key = key_match.group(1)
    try:
        d = json.load(open(path))
    except (json.JSONDecodeError, OSError):
        continue

    fields  = d.get("fields", {})
    status  = fields.get("status", {}).get("name", "unknown")
    itype   = fields.get("issuetype", {}).get("name", "unknown")
    summary = fields.get("summary", "")
    desc_adf = fields.get("description")
    desc_text = adf_text(desc_adf)[:5000] if desc_adf else ""
    ticket_via = via(f"jira:{ticket_key}")

    lines.append(f"JIRA: {ticket_key} · {status} · {itype} · via {ticket_via}")
    lines.append(f"Summary: {summary}")

    ac_items = extract_ac(desc_text)
    if ac_items:
        lines.append("Acceptance Criteria:")
        for item in ac_items:
            lines.append(f"  - {item}")
    else:
        lines.append("Acceptance Criteria: (none found — check Confluence AC docs below)")

    if desc_text:
        lines.append("Description (excerpt):")
        lines.append(desc_text[:2000])

    lines.append("")
    signal_texts.append((desc_text, f"jira:{ticket_key}"))

# ── Confluence pages table ────────────────────────────────────────────────────

conf_files = sorted(glob.glob("/tmp/conf_*.json"))
if conf_files:
    lines.append("CONFLUENCE PAGES:")
    lines.append("| ID | Title | Type | Via | URL |")
    lines.append("|----|-------|------|-----|-----|")
    for path in conf_files:
        pid_match = re.search(r"conf_(\d+)\.json$", path)
        if not pid_match:
            continue
        pid = pid_match.group(1)
        try:
            d = json.load(open(path))
        except (json.JSONDecodeError, OSError):
            continue
        title   = d.get("title", "unknown")
        body    = d.get("body", {}).get("export_view", {}).get("value", "")
        ptype   = classify_page(title, strip_html(body[:500]))
        page_via = via(f"conf:{pid}")
        url     = f"{jira_base}/wiki/spaces/{d.get('space',{}).get('key','')}/pages/{pid}"
        lines.append(f"| {pid} | {title} | {ptype} | {page_via} | {url} |")
    lines.append("")

    for path in conf_files:
        pid_match = re.search(r"conf_(\d+)\.json$", path)
        if not pid_match:
            continue
        pid = pid_match.group(1)
        try:
            d = json.load(open(path))
        except (json.JSONDecodeError, OSError):
            continue
        title    = d.get("title", "unknown")
        body     = d.get("body", {}).get("export_view", {}).get("value", "")
        plain    = strip_html(body)[:6000]
        ptype    = classify_page(title, plain[:500])
        page_via = via(f"conf:{pid}")
        lines.append(f"CONFLUENCE: {title} [{ptype}] [via {page_via}]")
        lines.append(plain)
        if len(plain) >= 6000:
            url = f"{jira_base}/wiki/spaces/{d.get('space',{}).get('key','')}/pages/{pid}"
            lines.append(f"<truncated — full page at {url}>")
        lines.append("")
        signal_texts.append((plain, f"conf:{pid}"))

# ── Cross-service signals ─────────────────────────────────────────────────────

signals = detect_signals(signal_texts)
lines.append("CROSS-SERVICE SIGNALS:")
if signals:
    lines.extend(signals)
else:
    lines.append("  none detected")

lines.append("---PREFETCHED_CONTEXT_END---")

print("\n".join(lines))
