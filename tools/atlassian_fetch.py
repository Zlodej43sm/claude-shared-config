#!/usr/bin/env python3
"""
atlassian_fetch — REST fallback for the Atlassian MCP server: read a Jira issue
or a Confluence page as Markdown, or verify the credentials.

SCHEMA_IN
  argv  jira <KEY>                       e.g. MA-22
        confluence <PAGE_URL | PAGE_ID>  .../wiki/spaces/<SPACE>/pages/<ID>[/title] or bare ID
        attachments <KEY> --dir DIR [--max N]   download the issue's image attachments
        check
  env   JIRA_BASE_URL  JIRA_EMAIL  JIRA_API_TOKEN
        CONFLUENCE_BASE_URL  optional, default $JIRA_BASE_URL/wiki

SCHEMA_OUT  stdout JSON
  jira:       { "key", "summary", "status", "priority", "assignee"|null,
                "description": markdown, "subtasks": [{key,status,summary}],
                "comments": [{author,created,body}]   (last 5, markdown),
                "issue_links": [{key,type,summary}],
                "remote_links": [url...],
                "attachments": [{id,filename,mime,size,author,created}] }  (metadata only)
  attachments: { "key", "dir", "images": [{id,filename,mime,size,author,created,path}],
                "skipped": [{filename,reason}] }
                Only raster images (png/jpeg/gif/webp), at most N (default 8) of at most
                5 MB each, oldest first; everything else is listed in "skipped". The Jira
                credentials are sent only to JIRA_BASE_URL — the redirect to Atlassian's
                media host is followed without them.
  confluence: { "id", "title", "space", "url", "markdown",
                "links": [absolute http(s) urls in the body],
                "confluence_links": [the subset that are Confluence page urls] }
  check:      { "ok": bool, "jira": {"status", "user"}, "confluence": {"status"} }
  Never prints a credential. Read-only (GETs only).

EXIT  0=ok  1=bad-args / missing env  2=http or network error (message on stderr:
      401 bad email/token, 403 no access, 404 not found)
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


def fail(code: int, msg: str) -> None:
    sys.stderr.write(f"ERROR: {msg}\n")
    raise SystemExit(code)


# ----------------------------------------------------------------- HTML -> Markdown

class Html2Md(HTMLParser):
    """Small, dependency-free converter for the HTML Jira (renderedFields) and
    Confluence (body.export_view) return: headings, paragraphs, nested lists, links,
    emphasis, code, quotes and tables. Unknown tags are transparent."""

    SKIP = {"script", "style"}

    def __init__(self, base: str = ""):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.buf: list[str] = []
        self.stack: list[tuple[str, list[str]]] = []  # (kind, saved buffer)
        self.lists: list[list] = []                   # [tag, counter]
        self.hrefs: list[str | None] = []
        self.tables: list[list[list[str]]] = []
        self.pre = 0
        self.skip = 0
        self.links: list[str] = []

    # buffers
    def push(self, kind: str) -> None:
        self.stack.append((kind, self.buf))
        self.buf = []

    def pop(self) -> str:
        text = "".join(self.buf)
        _, self.buf = self.stack.pop()
        return text

    def block(self) -> None:
        text = "".join(self.buf)
        if text and not text.endswith("\n\n"):
            self.buf.append("\n" if text.endswith("\n") else "\n\n")

    # parser callbacks
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif re.fullmatch(r"h[1-6]", tag):
            self.block()
            self.buf.append("#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "section", "article"):
            self.block()
        elif tag in ("ul", "ol"):
            if not self.lists:
                self.block()
            elif not "".join(self.buf).endswith("\n"):
                self.buf.append("\n")
            self.lists.append([tag, 0])
        elif tag == "li" and self.lists:
            lst = self.lists[-1]
            lst[1] += 1
            marker = "- " if lst[0] == "ul" else f"{lst[1]}. "
            if self.buf and not "".join(self.buf[-1:]).endswith("\n"):
                self.buf.append("\n")
            self.buf.append("  " * (len(self.lists) - 1) + marker)
        elif tag == "a":
            href = (a.get("href") or "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                href = urljoin(self.base, href)
                self.links.append(href)
                self.hrefs.append(href)
                self.buf.append("[")
            else:
                self.hrefs.append(None)
        elif tag in ("strong", "b"):
            self.buf.append("**")
        elif tag in ("em", "i"):
            self.buf.append("*")
        elif tag == "code" and not self.pre:
            self.buf.append("`")
        elif tag == "pre":
            self.block()
            self.buf.append("```\n")
            self.pre += 1
        elif tag == "br":
            self.buf.append("\n")
        elif tag == "hr":
            self.block()
            self.buf.append("---\n\n")
        elif tag == "img":
            alt = a.get("alt") or a.get("title") or ""
            self.buf.append(f"[image: {alt}]" if alt else "[image]")
        elif tag == "blockquote":
            self.block()
            self.push("quote")
        elif tag == "table":
            self.block()
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.tables[-1].append([])
        elif tag in ("td", "th") and self.tables:
            self.push("cell")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif re.fullmatch(r"h[1-6]", tag):
            self.buf.append("\n\n")
        elif tag in ("p", "div", "section", "article"):
            self.buf.append("\n" if self.lists else "\n\n")
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            if not self.lists:
                self.buf.append("\n")
        elif tag == "li":
            if not "".join(self.buf[-1:]).endswith("\n"):
                self.buf.append("\n")
        elif tag == "a" and self.hrefs:
            href = self.hrefs.pop()
            if href:
                self.buf.append(f"]({href})")
        elif tag in ("strong", "b"):
            self.buf.append("**")
        elif tag in ("em", "i"):
            self.buf.append("*")
        elif tag == "code" and not self.pre:
            self.buf.append("`")
        elif tag == "pre" and self.pre:
            self.pre -= 1
            self.buf.append("\n```\n\n")
        elif tag == "blockquote" and self.stack and self.stack[-1][0] == "quote":
            text = self.pop().strip()
            self.buf.append("\n".join(f"> {line}" if line else ">" for line in text.splitlines()) + "\n\n")
        elif tag in ("td", "th") and self.stack and self.stack[-1][0] == "cell" and self.tables:
            cell = re.sub(r"\s+", " ", self.pop()).strip().replace("|", "\\|")
            if self.tables[-1]:
                self.tables[-1][-1].append(cell)
        elif tag == "table" and self.tables:
            rows = [r for r in self.tables.pop() if r]
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                self.buf.append("\n".join(lines) + "\n\n")

    def handle_data(self, data):
        if self.skip:
            return
        self.buf.append(data if self.pre else re.sub(r"\s+", " ", data))

    def result(self) -> str:
        while self.stack:  # unclosed quote/cell in malformed HTML: keep the text
            text = self.pop()
            self.buf.append(text)
        text = "".join(self.buf)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_md(html: str, base: str = "") -> tuple[str, list[str]]:
    parser = Html2Md(base)
    parser.feed(html or "")
    parser.close()
    return parser.result(), list(dict.fromkeys(parser.links))


# ---------------------------------------------------------------------------- HTTP

def env(name: str, required: bool = True) -> str:
    value = os.environ.get(name, "").strip()
    if required and not value:
        fail(1, f"{name} is not set (add it to .claude/.env)")
    if value.startswith("op://"):
        fail(1, f"{name} is an unresolved op:// reference (is `op` installed and signed in? restart the session so sync-env.py resolves it)")
    return value.rstrip("/")


def get(url: str):
    cred = base64.b64encode(f"{env('JIRA_EMAIL')}:{env('JIRA_API_TOKEN')}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {cred}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        hint = {401: "credentials rejected - check JIRA_EMAIL / JIRA_API_TOKEN",
                403: "forbidden - no access to this resource",
                404: "not found"}.get(e.code, "")
        fail(2, f"HTTP {e.code} for {urlsplit(url).path} {hint}".strip())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        fail(2, f"network error: {getattr(e, 'reason', e)}")


def confluence_base() -> str:
    return env("CONFLUENCE_BASE_URL", required=False) or env("JIRA_BASE_URL") + "/wiki"


# --------------------------------------------------------------------- subcommands

def attachment_meta(a: dict) -> dict:
    return {"id": str(a.get("id", "")), "filename": a.get("filename", ""), "mime": a.get("mimeType", ""),
            "size": a.get("size", 0), "author": (a.get("author") or {}).get("displayName", ""),
            "created": a.get("created", "")}


def cmd_jira(key: str) -> dict:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-\d+", key):
        fail(1, f"{key!r} is not a Jira issue key")
    base = env("JIRA_BASE_URL")
    fields = "summary,status,priority,assignee,description,subtasks,comment,issuelinks,attachment"
    issue = get(f"{base}/rest/api/3/issue/{key}?expand=renderedFields&fields={fields}")
    f, rendered = issue.get("fields", {}), issue.get("renderedFields", {})

    def md(html):
        return html_to_md(html or "", base)[0]

    comments = []
    rendered_comments = (rendered.get("comment") or {}).get("comments", [])
    for c, rc in list(zip((f.get("comment") or {}).get("comments", []), rendered_comments))[-5:]:
        comments.append({"author": (c.get("author") or {}).get("displayName", ""),
                         "created": c.get("created", ""), "body": md(rc.get("body"))})

    links = []
    for link in f.get("issuelinks", []):
        other = link.get("outwardIssue") or link.get("inwardIssue") or {}
        kind = (link.get("type") or {}).get("outward" if link.get("outwardIssue") else "inward", "")
        links.append({"key": other.get("key", ""), "type": kind,
                      "summary": (other.get("fields") or {}).get("summary", "")})

    remote = get(f"{base}/rest/api/3/issue/{key}/remotelink")
    remote_urls = [r.get("object", {}).get("url", "") for r in (remote if isinstance(remote, list) else [])]

    return {
        "key": issue.get("key", key),
        "summary": f.get("summary", ""),
        "status": (f.get("status") or {}).get("name", ""),
        "priority": (f.get("priority") or {}).get("name", ""),
        "assignee": (f.get("assignee") or {}).get("displayName"),
        "description": md(rendered.get("description")),
        "subtasks": [{"key": s.get("key", ""), "status": ((s.get("fields") or {}).get("status") or {}).get("name", ""),
                      "summary": (s.get("fields") or {}).get("summary", "")} for s in f.get("subtasks", [])],
        "comments": comments,
        "issue_links": links,
        "remote_links": [u for u in remote_urls if u],
        "attachments": [attachment_meta(a) for a in f.get("attachment", [])],
    }


IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download(url: str, dest: str, max_bytes: int) -> str | None:
    """Fetch `url` (Jira attachment content) into `dest`. Returns None on success or a
    reason string. Jira answers 303 with a signed media-API URL: follow it manually and
    WITHOUT the Authorization header, so the credentials never leave JIRA_BASE_URL."""
    cred = base64.b64encode(f"{env('JIRA_EMAIL')}:{env('JIRA_API_TOKEN')}".encode()).decode()
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {cred}"})
    try:
        try:
            resp = opener.open(req, timeout=30)
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            if not location:
                return f"HTTP {e.code}"
            target = urljoin(url, location)
            if urlsplit(target).scheme != "https" and urlsplit(target).netloc != urlsplit(url).netloc:
                return "refused non-https redirect"
            same_host = urlsplit(target).netloc == urlsplit(url).netloc
            resp = urllib.request.urlopen(
                urllib.request.Request(target, headers={"Authorization": f"Basic {cred}"} if same_host else {}),
                timeout=30)
        with resp:
            data = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return f"network error: {getattr(e, 'reason', e)}"
    if len(data) > max_bytes:
        return f"larger than {max_bytes // (1024 * 1024)} MB"
    with open(dest, "wb") as fh:
        fh.write(data)
    return None


def cmd_attachments(key: str, directory: str, limit: int) -> dict:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-\d+", key):
        fail(1, f"{key!r} is not a Jira issue key")
    base = env("JIRA_BASE_URL")
    issue = get(f"{base}/rest/api/3/issue/{key}?fields=attachment")
    items = sorted((issue.get("fields") or {}).get("attachment", []), key=lambda a: a.get("created", ""))
    os.makedirs(directory, exist_ok=True)
    images, skipped = [], []
    for a in items:
        meta = attachment_meta(a)
        if meta["mime"] not in IMAGE_MIMES:
            skipped.append({"filename": meta["filename"], "reason": f"not a supported image ({meta['mime'] or 'unknown type'})"})
        elif meta["size"] > MAX_IMAGE_BYTES:
            skipped.append({"filename": meta["filename"], "reason": f"larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB"})
        elif len(images) >= limit:
            skipped.append({"filename": meta["filename"], "reason": f"over the {limit}-image limit"})
        else:
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", meta["filename"]) or "image"
            path = os.path.join(directory, f"{meta['id']}_{safe}")
            # built from the id, never from the response's own `content` URL, so the
            # credentials can only go to JIRA_BASE_URL
            reason = download(f"{base}/rest/api/3/attachment/content/{meta['id']}", path, MAX_IMAGE_BYTES)
            if reason:
                skipped.append({"filename": meta["filename"], "reason": reason})
            else:
                images.append({**meta, "path": path})
    return {"key": key, "dir": directory, "images": images, "skipped": skipped}


def page_id_from(arg: str) -> str:
    if re.fullmatch(r"\d+", arg):
        return arg
    m = re.search(r"/pages/(\d+)", arg) or re.search(r"[?&]pageId=(\d+)", arg)
    if not m:
        fail(1, f"no Confluence page id found in {arg!r} (short /wiki/x/ links can't be resolved - open the page and copy its full URL)")
    return m.group(1)


def cmd_confluence(arg: str) -> dict:
    page_id = page_id_from(arg)
    base = confluence_base()
    page = get(f"{base}/rest/api/content/{page_id}?expand=body.export_view,space")
    links_meta = page.get("_links", {})
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
    # webui is relative to _links.base, which already includes /wiki
    url = (links_meta.get("base", base) + links_meta.get("webui", "")) if links_meta.get("webui") else ""
    markdown, links = html_to_md(page.get("body", {}).get("export_view", {}).get("value", ""), origin + "/")
    return {
        "id": str(page.get("id", page_id)),
        "title": page.get("title", ""),
        "space": (page.get("space") or {}).get("name", ""),
        "url": url,
        "markdown": markdown,
        "links": links,
        "confluence_links": [u for u in links if re.search(r"/wiki/spaces/[^/]+/pages/\d+", u)],
    }


def cmd_check() -> dict:
    base = env("JIRA_BASE_URL")
    me = get(f"{base}/rest/api/3/myself")
    conf = {"status": "ok"}
    try:
        get(f"{confluence_base()}/rest/api/space?limit=1")
    except SystemExit:
        conf = {"status": "unreachable (Confluence access missing, or wrong CONFLUENCE_BASE_URL)"}
    return {"ok": True, "jira": {"status": "ok", "user": me.get("displayName", "")}, "confluence": conf}


def main(argv: list[str]) -> int:
    usage = "usage: atlassian_fetch.py jira <KEY> | confluence <URL|ID> | attachments <KEY> --dir DIR [--max N] | check"
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "check" and not rest:
        out = cmd_check()
    elif cmd == "jira" and len(rest) == 1:
        out = cmd_jira(rest[0])
    elif cmd == "confluence" and len(rest) == 1:
        out = cmd_confluence(rest[0])
    elif cmd == "attachments" and rest and rest[0][:1] != "-":
        opts = rest[1:]
        if len(opts) % 2 or any(o not in ("--dir", "--max") for o in opts[::2]):
            fail(1, usage)
        o = dict(zip(opts[::2], opts[1::2]))
        if "--dir" not in o or not o.get("--max", "8").isdigit():
            fail(1, usage)
        out = cmd_attachments(rest[0], o["--dir"], int(o.get("--max", "8")))
    else:
        fail(1, usage)
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
