#!/usr/bin/env python3
"""
workspace_docs — mechanical helper for the workspace-docs skill. Works on a
"workspace root": a folder holding several independent git repos plus a
root CLAUDE.md index and a docs/ library of chunks (<=4 KB, YAML frontmatter
with summary/keywords/verified). Standard library only.

The skill does the judgment (reading code, writing facts); this script does
the deterministic parts: inventory, validation, staleness, retrieval,
scaffolding new chunks and maintaining the links registry.

USAGE (root = --root, else $CLAUDE_PROJECT_DIR, else cwd). The writing commands (scaffold, link add/remove,
baseline --set) always refuse a root inside the shared Claude config repo (this script's repo, also reached
through a project's .claude/ symlinks) and, without --root, a root inside any git work tree.
  workspace_docs.py inventory                 JSON: repos (remote, branch, HEAD, version/lock/CI/agent files),
                                              non-repo entries, existing chunks (size, verified)
  workspace_docs.py check [--json]            validate the library; exit 1 on any FAIL
  workspace_docs.py status [--fetch]          per-repo staleness: commits on the default branch (origin/HEAD, else
                                              origin/main|master|develop) since the baseline commit, missing/orphan docs;
                                              --fetch runs `git fetch` first. The local checkout is never used.
  workspace_docs.py sync [--repos a,b]        `git pull --ff-only` every repo on its default branch: fetch, then
                                              fast-forward the default branch (the checkout when it is on it and
                                              clean; else the branch ref only). Never stashes, resets, rebases,
                                              switches branches or creates merge commits; skips with a reason.
  workspace_docs.py changes [--fetch] [--repos a,b] [--json]
                                              what changed on each repo's default branch since its baseline: commits,
                                              files, CORE changes (manifests, runtime, CI, Docker, agent docs, top-level
                                              and module layout, renames, default branch/remote), chunks that cite a
                                              changed path, and backticked paths in its service chunks that no longer exist
  workspace_docs.py baseline [--set] [--repos a,b]
                                              show, or record after a refresh, the default-branch commit each repo's docs
                                              were verified against (docs/baseline.json)
  workspace_docs.py find <words...> [-n N]    rank chunks for a question (frontmatter weighted); prints path + summary
  workspace_docs.py audit <backup.tgz>        no-content-loss check after align/refresh: backticked identifiers of
                                              the backup that no longer appear anywhere in CLAUDE.md + docs/
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


SHARED_REPO = Path(__file__).resolve().parents[1]


def unsafe_root(root, explicit):
    """Why `root` must not be written to, or None. A workspace root holds repos; it is not inside one.
    The shared config repo is refused even with an explicit --root."""
    if root.resolve().is_relative_to(SHARED_REPO):
        return f"it is inside the shared Claude config repo ({SHARED_REPO})"
    if not explicit:
        try:
            top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True, timeout=15)
        except Exception:
            top = None
        if top is not None and top.returncode == 0:
            return f"it is inside the git repo {top.stdout.strip()}"
    return None


def writes(a):
    """True for the subcommands that write docs/ or CLAUDE.md."""
    return a.cmd == "scaffold" or (a.cmd == "link" and a.action != "list") or (a.cmd == "baseline" and a.set)


def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def origin_url(repo):
    """origin's URL without any user:password@ part, so a token never reaches docs or output."""
    return re.sub(r"(https?://)[^/@\s]+@", r"\1", git(repo, "remote", "get-url", "origin"))


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
            "remote": origin_url(r),
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


# ---------------------------------------------------------------- default branch and baseline
BASELINE = "docs/baseline.json"
MANIFESTS = ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "go.mod", "Cargo.toml",
             "Gemfile", "composer.json", *LOCK_FILES)
CORE_RULES = (  # (label, predicate on a repo-relative path); first match wins
    ("agent docs", lambda p: p in AGENT_FILES or p.startswith((".claude/", ".cursor/", ".github/copilot"))),
    ("runtime version", lambda p: p in VERSION_FILES),
    ("manifest", lambda p: p.rsplit("/", 1)[-1] in MANIFESTS and p.count("/") <= 2),
    ("ci", lambda p: any(p == f or p.startswith(f + "/") for f in CI_FILES)),
    ("docker/deploy", lambda p: re.search(r"(^|/)(Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|helm/.*|\.dockerignore)$", p)),
    ("build/tooling", lambda p: p in ("Makefile", "tsconfig.json", ".npmrc", ".yarnrc.yml", "CODEOWNERS", ".github/CODEOWNERS")
        or re.match(r"(eslint|vite|vitest|jest|babel|webpack|next|tsconfig)[^/]*\.(c?js|mjs|ts|json)$", p)),
    ("migrations", lambda p: re.match(r"(.+/)?migrations?/", p)),
    ("config", lambda p: p.startswith("config/")),
    ("readme/docs", lambda p: p.rsplit("/", 1)[-1].upper().startswith("README") or p.startswith(("docs/", "guidelines/"))),
)


def default_ref(repo):
    """origin's default branch as a ref (origin/HEAD, else origin/main|master|develop|trunk); '' if none."""
    head = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head
    for b in ("main", "master", "develop", "trunk"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{b}"):
            return f"origin/{b}"
    return ""


def load_baseline(root):
    p = root / BASELINE
    try:
        return json.loads(p.read_text()) if p.is_file() else {}
    except ValueError:
        raise SystemExit(f"{BASELINE} is not valid JSON; fix or delete it")


def fetch_all(root, names=None):
    for r in repos(root):
        if not names or r.name in names:
            git(r, "fetch", "--quiet", "--prune", "origin")


def git_rc(repo, *args, timeout=180):
    """Run git, return (returncode, combined output) — for commands whose failure must be reported."""
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:
        return 1, str(e)


def cmd_sync(root, a):
    names = repo_filter(a)
    for r in repos(root):
        if names and r.name not in names:
            continue
        rc, out = git_rc(r, "fetch", "--prune", "origin")
        if rc:
            print(f"{r.name:32} SKIP fetch failed: {out.splitlines()[-1] if out else rc}"); continue
        ref = default_ref(r)
        if not ref:
            print(f"{r.name:32} SKIP no origin default branch"); continue
        b = ref.split("/", 1)[1]
        cur = git(r, "rev-parse", "--abbrev-ref", "HEAD")
        local = git(r, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}")
        if not local:
            print(f"{r.name:32} SKIP no local {b} branch (docs read {ref} anyway)"); continue
        if git(r, "rev-list", "--count", f"{ref}..{b}") != "0":
            print(f"{r.name:32} SKIP local {b} has commits not on {ref} (diverged; resolve by hand)"); continue
        behind = git(r, "rev-list", "--count", f"{b}..{ref}")
        if behind == "0":
            print(f"{r.name:32} ok      {b} up to date ({git(r, 'rev-parse', '--short', b)})"); continue
        old = git(r, "rev-parse", "--short", b)
        if cur == b:
            if git(r, "status", "--porcelain", "--untracked-files=no"):
                print(f"{r.name:32} SKIP on {b} with uncommitted changes ({behind} behind; commit or stash yourself)"); continue
            rc, out = git_rc(r, "merge", "--ff-only", "--quiet", ref)
        else:  # fast-forward the branch ref without touching the checked-out branch
            rc, out = git_rc(r, "fetch", "--quiet", "origin", f"{b}:{b}")
        new = git(r, "rev-parse", "--short", b)
        if rc:
            print(f"{r.name:32} FAIL    {out.splitlines()[-1] if out else rc}")
        else:
            note = "" if cur == b else f"  (checkout stays on {cur})"
            print(f"{r.name:32} pulled  {b} {old}..{new} (+{behind}){note}")
    return 0


def repo_filter(a):
    return {n.strip() for n in (getattr(a, "repos", None) or "").split(",") if n.strip()}


def cmd_baseline(root, a):
    base, names = load_baseline(root), repo_filter(a)
    if a.set:
        for r in repos(root):
            if names and r.name not in names:
                continue
            ref = default_ref(r)
            if not ref:
                print(f"{r.name}: no origin default branch, skipped"); continue
            base[r.name] = {"remote": origin_url(r), "branch": ref.split("/", 1)[1],
                            "commit": git(r, "rev-parse", ref), "date": git(r, "log", "-1", "--format=%cs", ref),
                            "recorded": TODAY}
        for gone in [n for n in base if not (root / n / ".git").exists()]:
            del base[gone]
        (root / BASELINE).write_text(json.dumps(dict(sorted(base.items())), indent=1) + "\n")
        print(f"wrote {BASELINE} ({len(base)} repos)")
    for n, b in sorted(base.items()):
        if not names or n in names:
            print(f"{n:40} {b['branch']:8} {b['commit'][:10]} {b['date']}  recorded {b['recorded']}")
    return 0


# ---------------------------------------------------------------- status
def cmd_status(root, a):
    svc, base = root / "docs/services", load_baseline(root)
    if a.fetch:
        fetch_all(root)
    print(f"{'repo':40} {'default':16} {'HEAD':10} {'verified':10} state")
    for r in repos(root):
        ref = default_ref(r)
        head = git(r, "log", "-1", "--format=%cs", ref) if ref else ""
        docs_for = list(svc.glob(f"{r.name}.md")) + list(svc.glob(f"{r.name}--*.md"))
        dates = [(frontmatter(d)[0] or {}).get("verified", "") for d in docs_for]
        ver = min((d for d in dates if d), default="")
        b = base.get(r.name)
        if not docs_for:
            state = "MISSING DOC"
        elif not ref:
            state = "no origin default branch"
        elif b and not git(r, "rev-parse", "--verify", "--quiet", b["commit"] + "^{commit}"):
            state = "baseline commit not found (history rewritten?): full re-check"
        elif b:
            n = git(r, "rev-list", "--count", f"{b['commit']}..{ref}")
            state = "ok" if n == "0" else f"stale ({n} commits since baseline)"
            if b.get("branch") and b["branch"] != ref.split("/", 1)[1]:
                state += f"  CORE: default branch {b['branch']} -> {ref.split('/', 1)[1]}"
        else:
            state = ("stale" if head and ver and head > ver else "ok" if ver else "no verified") + "  (no baseline: run baseline --set after refresh)"
        print(f"{r.name:40} {ref:16} {head:10} {ver:10} {state}")
    for c in svc.glob("*.md"):
        if c.name != "README.md" and not (root / service_repo(c) / ".git").exists():
            print(f"{c.name:40} {'':10} {'':10} ORPHAN DOC (repo gone)")
    big = sorted(((c.stat().st_size, rel(root, c)) for c in chunks(root)), reverse=True)[:3]
    print("largest chunks:", ", ".join(f"{p} {s}B" for s, p in big))
    fails = run_checks(root)
    print(f"check: {'OK' if not fails else f'{len(fails)} FAIL (run check)'}")
    return 0


# ---------------------------------------------------------------- changes
PATH_TOKEN = re.compile(r"`([A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@\[\]-]+)+/?)(?::\d[\d,-]*)?`")


def layout(repo, ref, depth):
    """Directory set of `ref` down to `depth` levels (module layout), ignoring dot-dirs below the top level."""
    out = set()
    for line in git(repo, "ls-tree", "-r", "-d", "--name-only", ref).splitlines():
        parts = line.split("/")
        if len(parts) <= depth and not any(p.startswith(".") for p in parts[1:]):
            out.add(line)
    return out


def repo_changes(root, r, base, texts):
    ref = default_ref(r)
    b = base.get(r.name)
    res = {"repo": r.name, "ref": ref, "head": git(r, "rev-parse", "--short", ref) if ref else "", "core": {}}
    if not ref:
        res["error"] = "no origin default branch"; return res
    if b and b.get("remote") and b["remote"] != origin_url(r):
        res["core"]["remote"] = [f"{b['remote']} -> {origin_url(r)}"]
    if b and b.get("branch") and b["branch"] != ref.split("/", 1)[1]:
        res["core"]["default branch"] = [f"{b['branch']} -> {ref.split('/', 1)[1]}"]
    if not b or not git(r, "rev-parse", "--verify", "--quiet", b["commit"] + "^{commit}"):
        res["error"] = "no usable baseline: re-verify the whole repo, then baseline --set"
        return res
    rng = f"{b['commit']}..{ref}"
    res["base"] = b["commit"][:10]
    res["commits"] = git(r, "log", "--no-merges", "--format=%h %cs %s", rng).splitlines()
    status = [l.split("\t") for l in git(r, "diff", "-M", "--name-status", b["commit"], ref).splitlines() if l]
    res["files"] = len(status)
    changed = []
    for st in status:
        kind, paths = st[0][0], st[1:]
        changed += paths
        if kind == "R":
            res["core"].setdefault("renamed", []).append(f"{paths[0]} -> {paths[1]}")
        for p in paths:
            for label, pred in CORE_RULES:
                if pred(p):
                    res["core"].setdefault(label, []).append(f"{kind} {p}")
                    break
    old_l, new_l = layout(r, b["commit"], 2), layout(r, ref, 2)
    if old_l != new_l:
        res["core"]["layout"] = [f"+ {d}/" for d in sorted(new_l - old_l)] + [f"- {d}/" for d in sorted(old_l - new_l)]
    # chunks that cite a changed path (full repo-relative path, or a file name of 8+ chars)
    cited = {}
    for p in set(changed):
        name = p.rsplit("/", 1)[-1]
        for path, text in texts.items():
            if f"`{p}" in text or (len(name) >= 8 and f"{name}`" in text and r.name in text):
                cited.setdefault(path, set()).add(p)
    res["chunks_citing_changed"] = {k: sorted(v)[:8] for k, v in sorted(cited.items())}
    # backticked paths in this repo's service chunks that do not exist on the default branch any more
    # a token counts as a path when it names a file (has an extension) or a dir (trailing slash); docs may
    # abbreviate paths (relative to src/ or a module), so any tree entry ending with it is a match
    entries = ["/" + p for p in git(r, "ls-tree", "-r", "--name-only", ref).splitlines()]
    entries += ["/" + d + "/" for d in layout(r, ref, 99)]
    blob = "\n".join(entries) + "\n"
    missing = {}
    for c in sorted((root / "docs/services").glob(f"{r.name}*.md")):
        if service_repo(c) != r.name:
            continue
        for tok in set(PATH_TOKEN.findall(c.read_text(errors="replace"))):
            t = tok.removeprefix(f"{r.name}/").removeprefix("./")
            is_dir, is_file = t.endswith("/"), re.search(r"\.[A-Za-z]{1,5}$", t)
            if not (is_dir or is_file) or t.startswith(("docs/", "http", "@", "~", "origin/")) or "…" in t:
                continue
            if ("/" + t + ("" if is_dir else "\n")) not in blob:
                missing.setdefault(rel(root, c), []).append(t)
    if missing:  # generated / local-only files are gitignored on purpose: not stale
        flat = sorted({t for v in missing.values() for t in v})
        try:
            ign = set(subprocess.run(["git", "-C", str(r), "check-ignore", "--no-index", "--stdin"], input="\n".join(
                t.rstrip("/") + ("/x" if t.endswith("/") else "") for t in flat), capture_output=True, text=True,
                timeout=15).stdout.split())
        except Exception:
            ign = set()
        missing = {k: [t for t in v if (t.rstrip("/") + ("/x" if t.endswith("/") else "")) not in ign]
                   for k, v in missing.items()}
        missing = {k: v for k, v in missing.items() if v}
    res["stale_paths_in_docs"] = {k: sorted(v) for k, v in missing.items()}
    return res


def cmd_changes(root, a):
    names = repo_filter(a)
    if a.fetch:
        fetch_all(root, names)
    base = load_baseline(root)
    texts = {rel(root, c): c.read_text(errors="replace") for c in chunks(root)}
    claude = root / "CLAUDE.md"
    if claude.is_file():
        texts["CLAUDE.md"] = claude.read_text()
    out = [repo_changes(root, r, base, texts) for r in repos(root) if not names or r.name in names]
    for n in sorted(set(base) - {r.name for r in repos(root)}):
        out.append({"repo": n, "error": "REPO GONE: run remove-repo"})
    if a.json:
        print(json.dumps(out, indent=1)); return 0
    for res in out:
        print(f"\n## {res['repo']}  {res.get('ref', '')} {res.get('base', '?')}..{res.get('head', '')}")
        if res.get("error"):
            print("  !", res["error"])
        if "commits" in res:
            print(f"  {len(res['commits'])} commits, {res['files']} files" + ("" if res["commits"] else "  (unchanged)"))
            for c in res["commits"][:25]:
                print("   ", c)
            if len(res["commits"]) > 25:
                print(f"    … {len(res['commits']) - 25} more")
        for label, items in res.get("core", {}).items():
            print(f"  CORE {label}: " + "; ".join(items[:12]) + (f" … +{len(items) - 12}" if len(items) > 12 else ""))
        for path, files in res.get("chunks_citing_changed", {}).items():
            print(f"  cites changed: {path}: " + ", ".join(files))
        for path, toks in res.get("stale_paths_in_docs", {}).items():
            print(f"  STALE PATH in {path}: " + ", ".join(toks))
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


# ---------------------------------------------------------------- audit
def lib_texts(base):
    paths = [base / "CLAUDE.md", *sorted((base / "docs").rglob("*.md"))] if (base / "docs").is_dir() else [base / "CLAUDE.md"]
    return [p.read_text(errors="replace") for p in paths if p.is_file()]


def cmd_audit(root, a):
    """No-content-loss check: every `backticked` identifier of the backup must still appear in the library."""
    import tarfile, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(a.backup) as tf:
            members = [m for m in tf.getmembers() if m.isfile() and not m.name.startswith(("/", "..")) and ".." not in m.name]
            try:
                tf.extractall(tmp, members=members, filter="data")
            except TypeError:  # Python < 3.12 has no extraction filters
                tf.extractall(tmp, members=members)
        old = set()
        for text in lib_texts(Path(tmp)):
            old |= set(re.findall(r"`([^`\n]{3,80})`", text))
    new = "\n".join(lib_texts(root))
    norm = lambda s: re.sub(r"\\\|", "|", s)
    lost = sorted(i for i in old if i not in new and norm(i) not in new and not re.search(r"[*§]|^[\s.,;:)]|[\s(,;:]$", i))
    print(f"{len(old)} identifiers in backup; {len(lost)} not found in the current library")
    for i in lost:
        print("  missing:", i)
    return 1 if lost else 0


# ---------------------------------------------------------------- scaffold
STUBS = {
    "service": ("docs/services/{name}.md", "# {name}\n\n**What it is:** {summary}. (family: <family>)\n**Top review risks:** <risks>\n**Related:** <`docs/services/x.md`>\n**Code:** `{name}/` · **Index:** `docs/services/README.md` · **Workspace map:** root `CLAUDE.md` §2-§3 · **Lookups:** `docs/lookups.md`\n\n---\n\n- **Stack:** <>\n- **CI/deploy:** <>\n- **Structure:** <>\n- **Data:** <>\n- **Auth:** <>\n- **Commands:** <>; single `<>`\n- **Review hotspots:** <>\n- **Drift:** <>\n"),
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


NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(--[A-Za-z0-9_][A-Za-z0-9_.-]*)?$")


def cmd_scaffold(root, a):
    path_t, body_t = STUBS[a.kind]
    name = a.name.removesuffix(".md")
    if not NAME_RE.match(name) or ".." in name:
        print(f"refusing: invalid name {a.name!r} (letters, digits, _ . -, optional <repo>--<part>; no / or ..)",
              file=sys.stderr); return 2
    title = a.title or name.replace("-", " ").capitalize()
    section = ""
    lookups_idx = root / "docs/lookups.md"
    if a.kind == "lookup" and lookups_idx.is_file():
        nums = [int(n) for n in re.findall(r"^\|\s*(\d+)\s*\|", lookups_idx.read_text(), re.M)]
        section = str(max(nums, default=0) + 1)
    path = root / path_t.format(name=name)
    if not path.resolve().is_relative_to((root / "docs").resolve()):
        print(f"refusing: {path} resolves outside {root / 'docs'}", file=sys.stderr); return 2
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
    rows = []
    for line in path.read_text().splitlines():
        if not line.startswith("| [") :
            continue
        m = ROW_RE.match(line)
        if not m:  # never drop a row we cannot parse: the next write would lose it
            raise SystemExit(f"unparsable row in {path.name}, fix it by hand first:\n{line}")
        rows.append(m.groupdict())
    return rows


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
        title = clean(a.title).replace("[", "(").replace("]", ")")
        rows.append({"title": title, "url": a.url.replace(")", "%29"), "why": clean(a.why),
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
    st = sub.add_parser("status"); st.add_argument("--fetch", action="store_true", help="git fetch each repo first")
    sy = sub.add_parser("sync"); sy.add_argument("--repos")
    ch = sub.add_parser("changes"); ch.add_argument("--fetch", action="store_true"); ch.add_argument("--repos")
    ch.add_argument("--json", action="store_true")
    bl = sub.add_parser("baseline"); bl.add_argument("--set", action="store_true"); bl.add_argument("--repos")
    f = sub.add_parser("find"); f.add_argument("words", nargs="+"); f.add_argument("-n", type=int, default=5)
    au = sub.add_parser("audit"); au.add_argument("backup", help="docs-backup-*.tgz made before align/refresh")
    s = sub.add_parser("scaffold"); s.add_argument("kind", choices=sorted(STUBS)); s.add_argument("name")
    s.add_argument("--summary"); s.add_argument("--keywords"); s.add_argument("--title")
    l = sub.add_parser("link"); l.add_argument("action", choices=["add", "remove", "list"]); l.add_argument("url", nargs="?")
    l.add_argument("--title"); l.add_argument("--why"); l.add_argument("--tags"); l.add_argument("--pin", action="store_true")
    a = p.parse_args()
    root = root_dir(a.root)
    why = writes(a) and unsafe_root(root, bool(a.root))
    if why:
        print(f"refusing to write to {root}: {why}. Run from the workspace root (the folder holding the repos) "
              "or pass --root <workspace-root> explicitly.", file=sys.stderr)
        return 2
    return {"inventory": cmd_inventory, "check": cmd_check, "status": cmd_status, "sync": cmd_sync, "changes": cmd_changes,
            "baseline": cmd_baseline, "find": cmd_find, "audit": cmd_audit,
            "scaffold": cmd_scaffold, "link": cmd_link}[a.cmd](root, a)


if __name__ == "__main__":
    sys.exit(main())
