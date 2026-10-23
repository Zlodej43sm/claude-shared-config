#!/usr/bin/env bash
# notion_fetch_page — fetch a Notion page (or verify the token) via the REST API
#
# SCHEMA_IN
#   $1  Notion page or database URL/ID (32 hex chars, dashes optional; notion.so,
#       app.notion.com/p/<ws>/..., *.notion.site, "?v=<view>" database views) — or "--check"
#   env NOTION_TOKEN          internal-integration secret; the page must be shared with the integration
#   env NOTION_WORKSPACE_ID   optional; --check reports whether the token's workspace matches it
#
# SCHEMA_OUT  stdout JSON
#   page:     { "kind": "page", "id", "title", "url", "markdown",
#               "linked_pages": [ { "id", "url" } ... ], "truncated": bool }
#   database: { "kind": "database", "id", "title", "url", "markdown",
#               "rows": [ { "id", "title", "url" } ... ], "linked_pages": [], "truncated": bool }
#   --check:  { "ok": true, "bot": string, "workspace": string|null,
#               "workspace_id": string|null, "workspace_match": bool|null }
#   Never prints the token. Read-only. Nested blocks are followed to depth 4 and
#   at most 500 blocks per page (truncated=true when the cap is hit); databases list
#   at most 50 rows.
#
# EXIT  0=ok  1=bad-args/missing-token  2=http-error (401 bad token, 404 not found
#       or not shared with the integration — or a different workspace, 429 rate limited)

set -uo pipefail

ARG="${1:?ERROR: notion_fetch_page.sh requires a Notion page URL/ID or --check as \$1}"
: "${NOTION_TOKEN:?ERROR: NOTION_TOKEN is not set (add it to .claude/.env)}"
export ARG

python3 - <<'PY'
import json, os, re, sys, time, urllib.error, urllib.request

TOKEN = os.environ["NOTION_TOKEN"]
ARG = os.environ["ARG"]
API = "https://api.notion.com/v1"
MAX_BLOCKS, MAX_DEPTH = 500, 4


def fail(code, msg):
    sys.stderr.write(f"ERROR: {msg}\n")
    raise SystemExit(code)


HINTS = {
    401: "token rejected - check NOTION_TOKEN",
    404: "not found: the page is not shared with the integration (page menu > Connections), "
         "or it lives in a different workspace than the token's (compare --check workspace_id)",
    429: "rate limited",
}


class HttpError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def request(path, method="GET", body=None, retries=2):
    req = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 429 and retries:
            time.sleep(int(e.headers.get("Retry-After", "1")))
            return request(path, method, body, retries - 1)
        raise HttpError(e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        fail(2, f"network error: {getattr(e, 'reason', e)}")


def get(path, method="GET", body=None):
    try:
        return request(path, method, body)
    except HttpError as e:
        fail(2, f"Notion HTTP {e.code} for {path.split('?')[0]} {HINTS.get(e.code, '')}".strip())


def norm_id(value):
    return (value or "").replace("-", "").lower()


if ARG == "--check":
    me = get("/users/me")
    bot = me.get("bot") or {}
    ws_id = bot.get("workspace_id")
    expected = norm_id(os.environ.get("NOTION_WORKSPACE_ID", ""))
    print(json.dumps({
        "ok": True,
        "bot": me.get("name") or me.get("id"),
        "workspace": bot.get("workspace_name"),
        "workspace_id": ws_id,
        "workspace_match": (norm_id(ws_id) == expected) if (expected and ws_id) else None,
    }))
    raise SystemExit(0)

# A 32-hex run or a dashed UUID, not glued to other hex digits. Dashes must not be
# stripped first: URLs carry a title slug ("...-Page-<id>") whose last letters can
# be hex and would merge into the id.
ID_RE = re.compile(
    r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?![0-9a-fA-F])"
)


def find_ids(text):
    return [i.replace("-", "").lower() for i in ID_RE.findall(text)]


ids = find_ids(ARG.split("?")[0])
if not ids:
    fail(1, f"no Notion page id found in {ARG!r}")
page_id = ids[-1]


def plain(rich):
    out = []
    for t in rich or []:
        s = t.get("plain_text", "")
        a = t.get("annotations", {})
        if a.get("code"):
            s = f"`{s}`"
        if a.get("bold"):
            s = f"**{s}**"
        if a.get("italic"):
            s = f"*{s}*"
        if t.get("href"):
            s = f"[{s}]({t['href']})"
        out.append(s)
    return "".join(out)


linked = {}
state = {"blocks": 0, "truncated": False}
NOTION_LINK = re.compile(
    r"https?://(?:(?:www\.)?notion\.so|app\.notion\.com|[\w-]+\.notion\.site)/[^\s)>\]]+"
)


def note_links(text):
    for url in NOTION_LINK.findall(text):
        ids = find_ids(url.split("?")[0])
        if ids and ids[-1] != page_id:
            linked.setdefault(ids[-1], url)


def render(block_id, depth):
    lines, cursor = [], None
    while True:
        q = f"/blocks/{block_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        data = get(q)
        for b in data["results"]:
            if state["blocks"] >= MAX_BLOCKS:
                state["truncated"] = True
                return lines
            state["blocks"] += 1
            t = b["type"]
            body = b.get(t, {})
            text = plain(body.get("rich_text"))
            indent = "  " * depth
            if t == "heading_1": lines.append(f"# {text}")
            elif t == "heading_2": lines.append(f"## {text}")
            elif t == "heading_3": lines.append(f"### {text}")
            elif t == "bulleted_list_item": lines.append(f"{indent}- {text}")
            elif t == "numbered_list_item": lines.append(f"{indent}1. {text}")
            elif t == "to_do": lines.append(f"{indent}- [{'x' if body.get('checked') else ' '}] {text}")
            elif t == "quote": lines.append(f"> {text}")
            elif t == "callout": lines.append(f"> {text}")
            elif t == "code": lines.append(f"```{body.get('language', '')}\n{text}\n```")
            elif t == "divider": lines.append("---")
            elif t == "toggle": lines.append(f"{indent}- {text}")
            elif t == "child_page":
                lines.append(f"[child page: {body.get('title', '')}]")
                linked.setdefault(b["id"].replace("-", ""), "")
            elif t == "child_database": lines.append(f"[child database: {body.get('title', '')}]")
            elif t in ("link_to_page",):
                tid = body.get(body.get("type", ""), "")
                if tid:
                    linked.setdefault(str(tid).replace("-", ""), "")
                lines.append(f"[link to page {tid}]")
            elif t in ("bookmark", "embed", "link_preview"):
                lines.append(body.get("url", ""))
            elif t == "paragraph": lines.append(text)
            else:
                lines.append(f"[unsupported block: {t}]" if not text else text)
            note_links(json.dumps(body))
            if b.get("has_children") and depth < MAX_DEPTH and t != "child_page":
                lines.extend(render(b["id"], depth + 1))
            if t not in ("bulleted_list_item", "numbered_list_item", "to_do", "toggle"):
                lines.append("")
        if not data.get("has_more"):
            return lines
        cursor = data["next_cursor"]


def title_of(properties):
    for prop in (properties or {}).values():
        if prop.get("type") == "title":
            return plain(prop.get("title"))
    return ""


def print_database():
    """A database or a saved view of one (the view id after ?v= is ignored: REST has no view API)."""
    db = get(f"/databases/{page_id}")
    title = plain(db.get("title"))
    data = get(f"/databases/{page_id}/query", "POST", {"page_size": 50})
    rows = [{"id": norm_id(r["id"]), "title": title_of(r.get("properties")), "url": r.get("url", "")}
            for r in data.get("results", [])]
    props = ", ".join(f"{name} ({p.get('type')})" for name, p in (db.get("properties") or {}).items())
    md = "\n".join([f"Properties: {props}", ""] + [f"- [{r['title'] or r['id']}]({r['url']})" for r in rows])
    print(json.dumps({
        "kind": "database",
        "id": page_id,
        "title": title,
        "url": db.get("url", ""),
        "markdown": md,
        "rows": rows,
        "linked_pages": [],
        "truncated": bool(data.get("has_more")),
    }))
    raise SystemExit(0)


# "?v=<view>" marks a database view. Otherwise try a page first: the API answers 400
# ("is a database") or 404 when the id is a database, so fall back to /databases.
if re.search(r"[?&]v=", ARG):
    print_database()
try:
    page = request(f"/pages/{page_id}")
except HttpError as e:
    if e.code not in (400, 404):
        fail(2, f"Notion HTTP {e.code} for /pages/{page_id} {HINTS.get(e.code, '')}".strip())
    print_database()

lines = render(page_id, 0)
md = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
print(json.dumps({
    "kind": "page",
    "id": page_id,
    "title": title_of(page.get("properties")),
    "url": page.get("url", ""),
    "markdown": md,
    "linked_pages": [{"id": i, "url": u} for i, u in linked.items()],
    "truncated": state["truncated"],
}))
PY
