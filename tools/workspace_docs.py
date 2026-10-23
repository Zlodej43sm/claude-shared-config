#!/usr/bin/env python3
"""
workspace_docs — mechanical helper for the workspace-docs skill. Works on a
"workspace root": a folder holding several independent git repos plus a
root CLAUDE.md index and a docs/ library of chunks (<=4 KB, YAML frontmatter
with summary/keywords/verified). Standard library only.

The skill does the judgment (reading code, writing facts); this script does
the deterministic parts: inventory, validation, staleness, retrieval,
scaffolding new chunks and maintaining the links registry.

USAGE (root = --root, else $CLAUDE_PROJECT_DIR, else cwd)
  workspace_docs.py inventory                 JSON: repos (remote, branch, HEAD, version/lock/CI/agent files),
                                              non-repo entries, existing chunks (size, verified)
  workspace_docs.py check [--json]            validate the library; exit 1 on any FAIL
  workspace_docs.py status [--fetch]          per-repo staleness (HEAD date vs doc verified), missing/orphan docs;
                                              --fetch compares the upstream branch instead of the local checkout
  workspace_docs.py find <words...> [-n N]    rank chunks for a question (frontmatter weighted); prints path + summary
  workspace_docs.py scaffold <kind> <name> [--summary S] [--keywords a,b] [--title T]
                                              kind: service|recipe|lookup|connection|topic; writes a stub chunk
                                              and registers it in its index (recipes/README.md, lookups.md)
  workspace_docs.py link add <url> --title T --why W [--tags a,b] [--pin]
  workspace_docs.py link remove <url>
  workspace_docs.py link list                 links registry docs/links.md; --pin mirrors into CLAUDE.md
"""
import argparse, datetime, json, os, re, subprocess, sys
from pathlib import Path

MAX_CHUNK = int(os.environ.get("MAX_CHUNK", 4096))
MAX_ROOT = int(os.environ.get("MAX_ROOT", 8192))
MAX_PINNED = 10
REQUIRED_KEYS = ("summary", "keywords", "verified")
TOP_LEVEL = "lookups|commands|conventions|checklist|change-map[A-Za-z0-9_-]*|security|drift|links"
LIB_RE = re.compile(r"docs/(?:(?:services|lookups|connections|recipes|tools|links)/[A-Za-z0-9_.-]+|(?:%s)\.md)" % TOP_LEVEL)
VERSION_FILES = (".nvmrc", ".node-version", ".python-version", ".tool-versions", ".java-version", ".ruby-version")
LOCK_FILES = {"package-lock.json": "npm", "yarn.lock": "yarn", "pnpm-lock.yaml": "pnpm", "uv.lock": "uv",
              "poetry.lock": "poetry", "Pipfile.lock": "pipenv", "pom.xml": "maven", "build.gradle": "gradle",
              "build.gradle.kts": "gradle", "go.sum": "go", "Cargo.lock": "cargo", "Gemfile.lock": "bundler"}
CI_FILES = ("bitbucket-pipelines.yml", ".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml", ".github/workflows", ".circleci")
AGENT_FILES = ("CLAUDE.md", "AGENTS.md", ".cursor", ".cursorrules", ".github/copilot-instructions.md", "CONTEXT.md")
SECRET_HINT = re.compile(r"(\.env$|\.env\.|credential|accesskey|secret|\.pem$|\.key$)", re.I)
TODAY = datetime.date.today().isoformat()


def root_dir(arg):
    return Path(arg or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def repos(root):
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())


def frontmatter(path):
    text = path.read_text(errors="replace")
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end < 0:
        return None, text
    fm = {}
    for line in text[4:end].splitlines():
        k, sep, v = line.partition(":")
        if sep:
            fm[k.strip()] = v.strip()
    return fm, text[end + 4:]


def chunks(root):
    docs = root / "docs"
    return sorted(docs.rglob("*.md")) if docs.is_dir() else []


def rel(root, p):
    return str(p.relative_to(root))


def service_repo(path):
    return path.stem.split("--")[0]


# ---------------------------------------------------------------- inventory
def cmd_inventory(root, _a):
    out = {"root": str(root), "repos": [], "other_entries": [], "chunks": []}
    for r in repos(root):
        out["repos"].append({
            "name": r.name,
            "remote": git(r, "remote", "get-url", "origin"),
            "branch": git(r, "rev-parse", "--abbrev-ref", "HEAD"),
            "head": git(r, "log", "-1", "--format=%h %cs %s"),
            "head_date": git(r, "log", "-1", "--format=%cs"),
            "version_files": {f: (r / f).read_text().strip()[:40] for f in VERSION_FILES if (r / f).is_file()},
            "package_managers": sorted({m for f, m in LOCK_FILES.items() if (r / f).exists()}),
            "ci": [f for f in CI_FILES if (r / f).exists()],
            "agent_docs": [f for f in AGENT_FILES if (r / f).exists()],
            "has_helm": (r / "helm").is_dir(),
            "doc": f"docs/services/{r.name}.md" if (root / "docs/services" / f"{r.name}.md").is_file() else None,
        })
    for p in sorted(root.iterdir()):
        if p.name.startswith(".") or (p.is_dir() and (p / ".git").exists()) or p.name in ("docs", "CLAUDE.md"):
            continue
        out["other_entries"].append({"name": p.name, "type": "dir" if p.is_dir() else "file",
                                     "sensitive": bool(SECRET_HINT.search(p.name))})
    for c in chunks(root):
        fm, _ = frontmatter(c)
        out["chunks"].append({"path": rel(root, c), "bytes": c.stat().st_size,
                              "verified": (fm or {}).get("verified")})
    print(json.dumps(out, indent=1))
    return 0


# ---------------------------------------------------------------- check
def run_checks(root):
    fails = []
    docs, claude = root / "docs", root / "CLAUDE.md"
    if not (docs / "services").is_dir():
        return ["docs/services/ missing (run the skill in init mode)"]
    for c in chunks(root):
        size = c.stat().st_size
        if size > MAX_CHUNK:
            fails.append(f"{rel(root, c)} is {size} bytes (max {MAX_CHUNK})")
        fm, _ = frontmatter(c)
        if fm is None:
            fails.append(f"{rel(root, c)} has no frontmatter")
            continue
        for k in REQUIRED_KEYS:
            if not fm.get(k) or fm.get(k) in ("[]", '""'):
                fails.append(f"{rel(root, c)} frontmatter missing '{k}'")
            elif "<" in fm[k] and ">" in fm[k]:
                fails.append(f"{rel(root, c)} frontmatter '{k}' still has a template placeholder")
    claude_text = claude.read_text() if claude.is_file() else ""
    if not claude_text:
        fails.append("root CLAUDE.md missing")
    idx = docs / "services/README.md"
    idx_text = idx.read_text() if idx.is_file() else ""
    for r in repos(root):
        if not (docs / "services" / f"{r.name}.md").is_file():
            fails.append(f"repo {r.name} has no docs/services/{r.name}.md")
        if f"`{r.name}`" not in claude_text:
            fails.append(f"repo {r.name} missing from root CLAUDE.md")
        if f"({r.name}.md)" not in idx_text:
            fails.append(f"repo {r.name} missing from docs/services/README.md")
    for c in (docs / "services").glob("*.md"):
        if c.name != "README.md" and not (root / service_repo(c) / ".git").exists():
            fails.append(f"docs/services/{c.name} has no matching repo '{service_repo(c)}'")
    refs = set(LIB_RE.findall(claude_text))
    for c in chunks(root):
        refs.update(LIB_RE.findall(c.read_text(errors="replace")))
    fails += [f"dangling link: {ref}" for ref in sorted(refs) if not (root / ref).exists()]
    if claude_text and len(claude_text.encode()) > MAX_ROOT:
        fails.append(f"root CLAUDE.md is {len(claude_text.encode())} bytes (keep it an index, max {MAX_ROOT})")
    return fails


def cmd_check(root, a):
    fails = run_checks(root)
    if a.json:
        print(json.dumps({"ok": not fails, "fails": fails, "chunks": len(chunks(root))}))
    else:
        for f in fails:
            print("FAIL:", f)
        if not fails:
            print(f"OK: docs library valid ({len(chunks(root))} chunks)")
    return 1 if fails else 0


# ---------------------------------------------------------------- status
def cmd_status(root, a):
    svc = root / "docs/services"
    print(f"{'repo':40} {'HEAD':10} {'verified':10} state" + ("   (HEAD = upstream after fetch)" if a.fetch else ""))
    for r in repos(root):
        if a.fetch:
            git(r, "fetch", "--quiet")
        head = (a.fetch and git(r, "log", "-1", "--format=%cs", "@{upstream}")) or git(r, "log", "-1", "--format=%cs")
        docs_for = list(svc.glob(f"{r.name}.md")) + list(svc.glob(f"{r.name}--*.md"))
        dates = [(frontmatter(d)[0] or {}).get("verified", "") for d in docs_for]
        ver = min((d for d in dates if d), default="")
        state = "MISSING DOC" if not docs_for else ("stale" if head and ver and head > ver else "ok" if ver else "no verified")
        branch = git(r, "rev-parse", "--abbrev-ref", "HEAD")
        print(f"{r.name:40} {head:10} {ver:10} {state}{'' if branch in ('main', 'master', 'develop', 'dev', 'trunk') else f'  (on {branch})'}")
    for c in svc.glob("*.md"):
        if c.name != "README.md" and not (root / service_repo(c) / ".git").exists():
            print(f"{c.name:40} {'':10} {'':10} ORPHAN DOC (repo gone)")
    big = sorted(((c.stat().st_size, rel(root, c)) for c in chunks(root)), reverse=True)[:3]
    print("largest chunks:", ", ".join(f"{p} {s}B" for s, p in big))
    fails = run_checks(root)
    print(f"check: {'OK' if not fails else f'{len(fails)} FAIL (run check)'}")
    return 0


# ---------------------------------------------------------------- find
def cmd_find(root, a):
    words = [w for w in re.split(r"[^\w./@-]+", " ".join(a.words).lower()) if len(w) > 1]
    if not words:
        print("give some words to search for"); return 2
    scored = []
    for c in chunks(root):
        fm, body = frontmatter(c)
        fm = fm or {}
        head = " ".join([fm.get("keywords", ""), c.stem]).lower()
        summ = fm.get("summary", "").lower()
        title = next((l for l in body.splitlines() if l.startswith("# ")), "").lower()
        low = body.lower()
        score = 0
        for w in words:
            score += 5 * head.count(w) + 3 * summ.count(w) + 3 * title.count(w) + min(low.count(w), 5)
        hits = sum(1 for w in words if w in head or w in summ or w in low)
        if score:
            scored.append((hits, score, rel(root, c), fm.get("summary", "")))
    scored.sort(reverse=True)
    for hits, score, path, summ in scored[: a.n]:
        print(f"{hits}/{len(words)} {score:4}  {path}\n          {summ}")
    if not scored:
        print("no chunk matches; try synonyms, or grep the repos directly")
    return 0


# ---------------------------------------------------------------- scaffold
STUBS = {
    "service": ("docs/services/{name}.md", "# {name}\n\n**What it is:** {summary}. (family: <family>)\n**Top review risks:** <risks>\n**Related:** <`docs/services/x.md`>\n**Code:** `{root}/{name}/` · **Index:** `docs/services/README.md` · **Workspace map:** root `CLAUDE.md` §2-§3 · **Lookups:** `docs/lookups.md`\n\n---\n\n- **Stack:** <>\n- **CI/deploy:** <>\n- **Structure:** <>\n- **Data:** <>\n- **Auth:** <>\n- **Commands:** <>; single `<>`\n- **Review hotspots:** <>\n- **Drift:** <>\n"),
    "recipe": ("docs/recipes/{name}.md", "# Recipe: {title}\n\nIndex: `docs/recipes/README.md`. Source: <page title + link>, read {today}.\n\n1. <step with exact command>\n\n## Gotchas\n- <>\n"),
    "lookup": ("docs/lookups/{name}.md", "# Lookups §{section}: {title}\n\nIndex: `docs/lookups.md`.\n\n| <Key> | Owner / producer | Also touched by / consumer | Notes |\n|---|---|---|---|\n"),
    "connection": ("docs/connections/{name}.md", "# Connections: {title}\n\nRoot `CLAUDE.md` §3. Tables: `docs/lookups.md`.\n\n```\n<caller> ─<mechanism>─► <callee>\n```\n\n## Points that bite\n- **<name>:** <>\n"),
    "topic": ("docs/{name}.md", "# {title}\n\nRoot `CLAUDE.md` §5.\n\n- <>\n"),
}


def append_table_row(index, row):
    lines = index.read_text().splitlines()
    last = max((i for i, l in enumerate(lines) if l.startswith("|")), default=None)
    if last is None:
        lines += ["", row]
    else:
        lines.insert(last + 1, row)
    index.write_text("\n".join(lines) + "\n")


def cmd_scaffold(root, a):
    path_t, body_t = STUBS[a.kind]
    name = a.name.removesuffix(".md")
    title = a.title or name.replace("-", " ").capitalize()
    section = ""
    lookups_idx = root / "docs/lookups.md"
    if a.kind == "lookup" and lookups_idx.is_file():
        nums = [int(n) for n in re.findall(r"^\|\s*(\d+)\s*\|", lookups_idx.read_text(), re.M)]
        section = str(max(nums, default=0) + 1)
    path = root / path_t.format(name=name)
    if path.exists():
        print(f"exists: {rel(root, path)}"); return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = a.summary or f"<one line: what {name} answers>"
    keywords = ", ".join(k.strip() for k in (a.keywords or "").split(",") if k.strip()) or "<keywords>"
    fm = f"---\nsummary: {summary}\nkeywords: [{keywords}]\nverified: {TODAY}\n---\n"
    path.write_text(fm + body_t.format(name=name, title=title, summary=summary, root=root, today=TODAY, section=section))
    print(f"created {rel(root, path)}")
    if a.kind == "recipe" and (root / "docs/recipes/README.md").is_file():
        append_table_row(root / "docs/recipes/README.md", f"| {summary} | `docs/recipes/{name}.md` | <source> |")
        print("registered in docs/recipes/README.md")
    elif a.kind == "lookup" and lookups_idx.is_file():
        append_table_row(lookups_idx, f"| {section} | {title} | `docs/lookups/{name}.md` |")
        print(f"registered as §{section} in docs/lookups.md")
    else:
        print("now add a pointer: service → docs/services/README.md row + CLAUDE.md §2; connection → CLAUDE.md §3; topic → CLAUDE.md Quick navigation")
    return 0


# ---------------------------------------------------------------- links
LINKS_HEAD = ("---\nsummary: Registry of useful external links (dashboards, Confluence/Notion pages, tickets, runbooks) "
              "and when to open each\nkeywords: [links, urls, dashboards, confluence, notion, jira, runbook, reference]\n"
              "verified: {today}\n---\n# Useful links\n\nRoot `CLAUDE.md` §7. Pinned rows are mirrored into root `CLAUDE.md`. "
              "Never store tokens or credentials in a URL.\n\n| Link | What it is / when to open | Tags | Pinned |\n|---|---|---|---|\n")
PIN_START, PIN_END = "<!-- pinned-links:start -->", "<!-- pinned-links:end -->"
ROW_RE = re.compile(r"^\| \[(?P<title>[^\]]*)\]\((?P<url>[^)]*)\) \| (?P<why>.*?) \| (?P<tags>.*?) \| (?P<pin>yes|no) \|$")


def read_links(path):
    if not path.is_file():
        return []
    return [m.groupdict() for m in map(ROW_RE.match, path.read_text().splitlines()) if m]


def write_links(root, rows):
    path = root / "docs/links.md"
    text = LINKS_HEAD.format(today=TODAY) + "".join(
        f"| [{r['title']}]({r['url']}) | {r['why']} | {r['tags']} | {r['pin']} |\n" for r in rows)
    if len(text.encode()) > MAX_CHUNK:
        raise SystemExit(f"docs/links.md would be {len(text.encode())} bytes (> {MAX_CHUNK}): move a tag group to "
                         "docs/links/<tag>.md (scaffold topic) before adding more")
    path.write_text(text)
    pinned = [r for r in rows if r["pin"] == "yes"]
    claude = root / "CLAUDE.md"
    if not claude.is_file():
        return
    items = "".join(f"- [{r['title']}]({r['url']}) — {r['why']}\n" for r in pinned) or "- none pinned\n"
    block = PIN_START + "\n" + items + PIN_END
    ctext = claude.read_text()
    if PIN_START in ctext:
        ctext = re.sub(re.escape(PIN_START) + r".*?" + re.escape(PIN_END), block.replace("\\", "\\\\"), ctext, flags=re.S)
    elif pinned:
        m = re.search(r"^## 8\.", ctext, re.M)
        insert = f"Pinned links (full registry `docs/links.md`):\n{block}\n\n"
        ctext = ctext[: m.start()] + insert + ctext[m.start():] if m else ctext.rstrip() + "\n\n" + insert
    claude.write_text(ctext)


def cmd_link(root, a):
    path = root / "docs/links.md"
    rows = read_links(path)
    if a.action == "list":
        for r in rows:
            print(f"{'*' if r['pin'] == 'yes' else ' '} {r['title']}  {r['url']}\n    {r['why']}  [{r['tags']}]")
        return 0
    if not a.url:
        print("url required"); return 2
    if re.search(r"(token|key|secret|password|sig)=", a.url, re.I):
        print("refusing: URL looks like it carries a credential"); return 2
    rows = [r for r in rows if r["url"] != a.url]
    if a.action == "add":
        if not (a.title and a.why):
            print("--title and --why are required"); return 2
        if a.pin and sum(r["pin"] == "yes" for r in rows) >= MAX_PINNED:
            print(f"already {MAX_PINNED} pinned links; unpin one first (keeps CLAUDE.md lean)"); return 2
        clean = lambda s: s.replace("|", "/").strip()
        rows.append({"title": clean(a.title), "url": a.url, "why": clean(a.why),
                     "tags": clean(a.tags or ""), "pin": "yes" if a.pin else "no"})
    write_links(root, rows)
    print(f"{a.action}: {a.url} ({len(rows)} links, {sum(r['pin'] == 'yes' for r in rows)} pinned)")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--root")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory")
    c = sub.add_parser("check"); c.add_argument("--json", action="store_true")
    st = sub.add_parser("status"); st.add_argument("--fetch", action="store_true", help="git fetch each repo and compare upstream HEAD")
    f = sub.add_parser("find"); f.add_argument("words", nargs="+"); f.add_argument("-n", type=int, default=5)
    s = sub.add_parser("scaffold"); s.add_argument("kind", choices=sorted(STUBS)); s.add_argument("name")
    s.add_argument("--summary"); s.add_argument("--keywords"); s.add_argument("--title")
    l = sub.add_parser("link"); l.add_argument("action", choices=["add", "remove", "list"]); l.add_argument("url", nargs="?")
    l.add_argument("--title"); l.add_argument("--why"); l.add_argument("--tags"); l.add_argument("--pin", action="store_true")
    a = p.parse_args()
    root = root_dir(a.root)
    return {"inventory": cmd_inventory, "check": cmd_check, "status": cmd_status, "find": cmd_find,
            "scaffold": cmd_scaffold, "link": cmd_link}[a.cmd](root, a)


if __name__ == "__main__":
    sys.exit(main())
