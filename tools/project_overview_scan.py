#!/usr/bin/env python3
"""
project_overview_scan — mechanical first pass over an arbitrary software
repository for the project-overview skill. Walks the tree once, classifies
files by category (metadata/manifests/entry points/CI/infra/config/tests),
parses manifests it recognizes, and best-effort shells out to optional local
tools (tokei/scc/cloc for language stats, syft for a cross-ecosystem
dependency+license summary) when they happen to be installed. Every optional
tool is feature-detected and silently skipped when absent — this script has
NO required third-party dependencies and always produces a full result using
only the Python standard library.

This is evidence gathering, not judgment. It does not infer architecture,
classify runtime-dependency types, or decide what's "risky" — that reasoning
is the project-overview skill's job once it has this JSON.

SCHEMA_IN
  argv[1]            path to the repository root to scan (required)
  --related=P1,P2    comma-separated local paths to related repos (optional)
  --siblings         also inspect directories next to ROOT for sibling git
                      repos (optional; off by default — "only when relevant")

SCHEMA_OUT  stdout JSON
  {
    "root": "<resolved absolute path>",
    "git": {"is_repo": bool, "remotes": [{"name","url"}], "current_branch",
            "default_branch"},
    "metadata_files": [{"path","kind"}],
    "manifests": [{"path","ecosystem","kind","parsed": {...}|null}],
    "entry_point_candidates": [{"path","reason"}],
    "ci_cd_files": ["path", ...],
    "infra_deploy_files": ["path", ...],
    "config_files": [{"path","declared_keys": [...]|null}],
    "source_layout": [{"dir","file_count","subdirs": [...]}],
    "test_dirs": ["path", ...],
    "workspace_signals": [{"type","members": [...]|null,"evidence"}],
    "related_repos": [{"path","exists","is_git_repo","remotes": [...]}],
    "sibling_repos": [{"path","remotes": [...]}] | null,
    "loc_breakdown": {"tool","languages": [{"language","files","code",
                       "comments","blanks"}]} | null,
    "dependency_summary": {"tool","components": [{"name","version",
                            "ecosystem","license"}],"truncated": bool} | null,
    "secret_redactions": [{"file","line","pattern","redacted"}],
    "warnings": ["..."],
    "files_visited": N,
    "files_visited_capped": bool
  }

EXIT  0=ok  1=root does not exist / is not a directory
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from shutil import which
from xml.etree import ElementTree as ET

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", "out",
    ".venv", "venv", "__pycache__", ".idea", ".vscode", ".cache",
    ".terraform", "coverage", ".next", ".nuxt", "bin", "obj",
    ".claude", ".pytest_cache", ".mypy_cache", ".tox",
}
SKIP_FILES = {".env", ".env.local", "settings.local.json"}
MAX_DEPTH = 6
MAX_FILES = 50_000

# ---------------------------------------------------------------------------
# Secret redaction (deliberately duplicated from security_audit_scan.py's
# small helpers rather than cross-imported — keeps this script independently
# runnable with no path/import coupling to a sibling script's internals).
# ---------------------------------------------------------------------------

PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")
SECRET_PATTERNS = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), False),
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b"), True),
    ("slack_token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"), True),
    ("jwt", re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{10,})\b"), True),
    ("basic_auth_in_url", re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:\"']+:([^/\s@\"']+)@"), True),
    (
        "db_conn_string_creds",
        re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s\"']+:([^\s\"'@]+)@"),
        True,
    ),
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|access[_-]?key|private[_-]?key|credential)s?\s*[:=]\s*[\"']?([A-Za-z0-9/+_.\-]{12,})[\"']?"
        ),
        True,
    ),
]


def is_placeholder(value: str) -> bool:
    v = value.strip().strip("\"'")
    if not v:
        return True
    lowered = v.lower()
    if lowered.startswith("op://"):
        return True
    markers = (
        "replace-with", "replace_with", "your-", "your_", "yourname",
        "changeme", "change_me", "placeholder", "dummy", "sample",
        "redacted", "example", "<", ">", "${", "$(", "xxx", "todo", "fixme",
    )
    if any(m in lowered for m in markers):
        return True
    if re.match(r"^\$[A-Za-z_][A-Za-z0-9_]*$", v):
        return True
    if len(set(v)) <= 2 and len(v) > 6:
        return True
    return False


def redact(value: str) -> str:
    v = value.strip().strip("\"'")
    if len(v) <= 8:
        return "…" * len(v)
    return f"{v[:4]}…{v[-4:]}"


def scan_line_for_secrets(rel: str, lineno: int, line: str, out: list[dict]) -> None:
    if PRIVATE_KEY_BLOCK.search(line):
        out.append({"file": rel, "line": lineno, "pattern": "private_key_block", "redacted": "-----BEGIN … PRIVATE KEY-----"})
        return
    for name, pattern, has_group in SECRET_PATTERNS:
        for m in pattern.finditer(line):
            value = m.group(1) if has_group else m.group(0)
            if is_placeholder(value):
                continue
            out.append({"file": rel, "line": lineno, "pattern": name, "redacted": redact(value)})


# ---------------------------------------------------------------------------
# Filesystem walk + classification
# ---------------------------------------------------------------------------

METADATA_PATTERNS = [
    (re.compile(r"^readme(\..*)?$", re.I), "readme"),
    (re.compile(r"^contributing(\..*)?$", re.I), "contributing"),
    (re.compile(r"^changelog(\..*)?$", re.I), "changelog"),
    (re.compile(r"^license(\..*)?$", re.I), "license"),
    (re.compile(r"^codeowners$", re.I), "codeowners"),
    (re.compile(r"^\.editorconfig$"), "editorconfig"),
]

CI_PATTERNS = [
    re.compile(r"^\.github/workflows/.+\.ya?ml$"),
    re.compile(r"^\.gitlab-ci\.ya?ml$"),
    re.compile(r"^bitbucket-pipelines\.ya?ml$"),
    re.compile(r"^jenkinsfile$", re.I),
    re.compile(r"^azure-pipelines\.ya?ml$"),
    re.compile(r"^\.circleci/config\.ya?ml$"),
]

INFRA_PATTERNS = [
    re.compile(r"(^|/)dockerfile([.\-].*)?$", re.I),
    re.compile(r"(^|/)docker-compose.*\.ya?ml$"),
    re.compile(r"(^|/)(k8s|deploy|helm|charts)/.+\.ya?ml$"),
    re.compile(r"\.tf$"),
    re.compile(r"^serverless\.ya?ml$"),
    re.compile(r"^procfile$", re.I),
    re.compile(r"(^|/)chart\.ya?ml$", re.I),
]

CONFIG_PATTERNS = [
    re.compile(r"^\.env\.(example|template)$"),
    re.compile(r"^env\.(example|template)$"),
    re.compile(r"^config/.+"),
    re.compile(r"^application\.(ya?ml|properties)$"),
    re.compile(r"^appsettings.*\.json$"),
]

TEST_DIR_NAMES = {"test", "tests", "spec", "__tests__", "specs"}

CONVENTIONAL_ENTRY_FILES = {
    "main.py", "main.go", "app.py", "server.py", "server.js", "server.ts",
    "index.js", "index.ts", "app.js", "app.ts",
}

# filename/glob-suffix -> (ecosystem, kind)
MANIFEST_KIND = {
    "package.json": ("node", "manifest"),
    "package-lock.json": ("node", "lockfile"),
    "yarn.lock": ("node", "lockfile"),
    "pnpm-lock.yaml": ("node", "lockfile"),
    "pyproject.toml": ("python", "manifest"),
    "poetry.lock": ("python", "lockfile"),
    "requirements.txt": ("python", "manifest"),
    "pipfile": ("python", "manifest"),
    "pipfile.lock": ("python", "lockfile"),
    "go.mod": ("go", "manifest"),
    "go.sum": ("go", "lockfile"),
    "cargo.toml": ("rust", "manifest"),
    "cargo.lock": ("rust", "lockfile"),
    "pom.xml": ("java", "manifest"),
    "build.gradle": ("java", "manifest"),
    "build.gradle.kts": ("java", "manifest"),
    "gemfile": ("ruby", "manifest"),
    "gemfile.lock": ("ruby", "lockfile"),
    "composer.json": ("php", "manifest"),
    "composer.lock": ("php", "lockfile"),
}


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


ALLOWED_HIDDEN_DIRS = {".github", ".circleci"}


def walk_bounded(root: Path):
    """Single bounded-depth pass. Yields (Path, rel_str, depth). Does not cap
    file count itself — the caller (classify()) owns MAX_FILES enforcement so
    there is exactly one place that can silently truncate, and it reports it."""
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if entry.is_dir():
                if name in SKIP_DIRS:
                    continue
                if name.startswith(".") and name not in ALLOWED_HIDDEN_DIRS:
                    continue
                if depth + 1 <= MAX_DEPTH:
                    stack.append((entry, depth + 1))
            elif entry.is_file():
                yield entry, rel(root, entry), depth


def classify(root: Path):
    metadata_files, manifest_files, ci_files, infra_files, config_files = [], [], [], [], []
    test_dirs_set = set()
    entry_point_hits = []
    top_level = {}
    files_visited = 0
    capped = False

    for path, relp, depth in walk_bounded(root):
        if files_visited >= MAX_FILES:
            capped = True
            break
        files_visited += 1
        name = path.name
        lower = relp.lower()

        if depth <= 2:
            top = relp.split("/")[0] if depth >= 1 else "."
            top_level.setdefault(top, 0)
            top_level[top] += 1

        for pattern, kind in METADATA_PATTERNS:
            if pattern.match(name):
                metadata_files.append({"path": relp, "kind": kind})
                break

        key = name.lower()
        if key in MANIFEST_KIND:
            ecosystem, kind = MANIFEST_KIND[key]
            manifest_files.append({"path": relp, "ecosystem": ecosystem, "kind": kind})
        elif key.startswith("requirements") and key.endswith(".txt"):
            manifest_files.append({"path": relp, "ecosystem": "python", "kind": "manifest"})
        elif key.endswith(".csproj") or key.endswith(".sln"):
            manifest_files.append({"path": relp, "ecosystem": "dotnet", "kind": "manifest" if key.endswith(".csproj") else "solution"})

        if any(p.match(lower) for p in CI_PATTERNS):
            ci_files.append(relp)
        if any(p.search(lower) for p in INFRA_PATTERNS):
            infra_files.append(relp)
        if any(p.match(lower) for p in CONFIG_PATTERNS):
            config_files.append(relp)

        if name in CONVENTIONAL_ENTRY_FILES or re.match(r"^cmd/[^/]+/main\.go$", relp):
            entry_point_hits.append({"path": relp, "reason": "conventional entry filename"})
        if key.startswith("dockerfile"):
            entry_point_hits.append({"path": relp, "reason": "Dockerfile — see ENTRYPOINT/CMD"})
        if key == "procfile":
            entry_point_hits.append({"path": relp, "reason": "Procfile"})

        parts_lower = {p.lower() for p in relp.split("/")[:-1]}
        if parts_lower & TEST_DIR_NAMES:
            test_dirs_set.add("/".join(relp.split("/")[: -1]) or ".")

    source_layout = [
        {"dir": d, "file_count": c} for d, c in sorted(top_level.items(), key=lambda kv: -kv[1])
    ]
    return {
        "metadata_files": metadata_files,
        "manifest_files": manifest_files,
        "ci_cd_files": sorted(set(ci_files)),
        "infra_deploy_files": sorted(set(infra_files)),
        "config_file_paths": sorted(set(config_files)),
        "entry_point_hits": entry_point_hits,
        "test_dirs": sorted(test_dirs_set),
        "source_layout": source_layout,
        "files_visited": files_visited,
        "files_visited_capped": capped,
    }


# ---------------------------------------------------------------------------
# Manifest parsers — best-effort, never fatal
# ---------------------------------------------------------------------------

def cap_dict(d: dict, limit: int = 200) -> tuple[dict, bool]:
    if len(d) <= limit:
        return d, False
    return dict(list(d.items())[:limit]), True


def parse_package_json(path: Path, warnings: list[str]) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError) as e:
        warnings.append(f"failed to parse {path.name}: {e}")
        return None
    deps, truncated = cap_dict(data.get("dependencies") or {})
    dev_deps, dev_truncated = cap_dict(data.get("devDependencies") or {})
    return {
        "name": data.get("name"),
        "version": data.get("version"),
        "description": data.get("description"),
        "main": data.get("main"),
        "bin": data.get("bin"),
        "scripts": sorted((data.get("scripts") or {}).keys()),
        "dependencies": deps,
        "devDependencies": dev_deps,
        "workspaces": data.get("workspaces"),
        "dependencies_truncated": truncated or dev_truncated,
    }


def parse_pyproject_toml(path: Path, warnings: list[str]) -> dict | None:
    if tomllib is None:
        warnings.append(f"skipped {path.name}: tomllib unavailable (Python <3.11)")
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:  # noqa: BLE001 - any malformed TOML must not abort the scan
        warnings.append(f"failed to parse {path.name}: {e}")
        return None
    project = data.get("project") or {}
    poetry = ((data.get("tool") or {}).get("poetry")) or {}
    deps = project.get("dependencies") or []
    poetry_deps, truncated = cap_dict(poetry.get("dependencies") or {})
    return {
        "name": project.get("name") or poetry.get("name"),
        "version": project.get("version") or poetry.get("version"),
        "description": project.get("description") or poetry.get("description"),
        "dependencies": deps if deps else poetry_deps,
        "dependencies_truncated": truncated,
        "scripts": sorted((project.get("scripts") or {}).keys()),
    }


def parse_requirements_txt(path: Path, warnings: list[str]) -> dict | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as e:
        warnings.append(f"failed to read {path.name}: {e}")
        return None
    reqs = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    reqs, truncated = (reqs[:200], len(reqs) > 200)
    return {"requirements": reqs, "dependencies_truncated": truncated}


def parse_go_mod(path: Path, warnings: list[str]) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        warnings.append(f"failed to read {path.name}: {e}")
        return None
    module = re.search(r"^module\s+(\S+)", text, re.M)
    go_version = re.search(r"^go\s+(\S+)", text, re.M)
    requires = re.findall(r"^\s*([^\s/][\S]*)\s+(v\S+)\s*$", text, re.M)
    requires = [r for r in requires if r[0] not in {"module", "go", "require", "replace", "exclude", "retract"}]
    reqs, truncated = (requires[:200], len(requires) > 200)
    return {
        "module": module.group(1) if module else None,
        "go_version": go_version.group(1) if go_version else None,
        "require": [{"path": p, "version": v} for p, v in reqs],
        "dependencies_truncated": truncated,
    }


def parse_cargo_toml(path: Path, warnings: list[str]) -> dict | None:
    if tomllib is None:
        warnings.append(f"skipped {path.name}: tomllib unavailable (Python <3.11)")
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"failed to parse {path.name}: {e}")
        return None
    package = data.get("package") or {}
    deps, truncated = cap_dict(data.get("dependencies") or {})
    workspace = data.get("workspace") or {}
    return {
        "name": package.get("name"),
        "version": package.get("version"),
        "dependencies": {k: (v if isinstance(v, str) else v.get("version") if isinstance(v, dict) else str(v)) for k, v in deps.items()},
        "dependencies_truncated": truncated,
        "workspace_members": workspace.get("members"),
    }


def parse_pom_xml(path: Path, warnings: list[str]) -> dict | None:
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as e:
        warnings.append(f"failed to parse {path.name}: {e}")
        return None
    root_el = tree.getroot()
    ns = re.match(r"\{(.*)\}", root_el.tag)
    ns_uri = ns.group(1) if ns else ""
    def tag(name: str) -> str:
        return f"{{{ns_uri}}}{name}" if ns_uri else name
    def find_text(parent, name):
        el = parent.find(tag(name))
        return el.text.strip() if el is not None and el.text else None
    deps = []
    deps_el = root_el.find(tag("dependencies"))
    if deps_el is not None:
        for dep in deps_el.findall(tag("dependency")):
            deps.append({
                "groupId": find_text(dep, "groupId"),
                "artifactId": find_text(dep, "artifactId"),
                "version": find_text(dep, "version"),
            })
    deps, truncated = (deps[:200], len(deps) > 200)
    return {
        "groupId": find_text(root_el, "groupId"),
        "artifactId": find_text(root_el, "artifactId"),
        "version": find_text(root_el, "version"),
        "dependencies": deps,
        "dependencies_truncated": truncated,
    }


def parse_gemfile(path: Path, warnings: list[str]) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        warnings.append(f"failed to read {path.name}: {e}")
        return None
    gems = re.findall(r"^\s*gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", text, re.M)
    gems, truncated = (gems[:200], len(gems) > 200)
    return {"gems": [{"name": n, "version": v or None} for n, v in gems], "dependencies_truncated": truncated}


def parse_composer_json(path: Path, warnings: list[str]) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError) as e:
        warnings.append(f"failed to parse {path.name}: {e}")
        return None
    deps, truncated = cap_dict(data.get("require") or {})
    return {
        "name": data.get("name"),
        "version": data.get("version"),
        "description": data.get("description"),
        "require": deps,
        "dependencies_truncated": truncated,
    }


def parse_csproj(path: Path, warnings: list[str]) -> dict | None:
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as e:
        warnings.append(f"failed to parse {path.name}: {e}")
        return None
    refs = []
    for el in tree.getroot().iter():
        if el.tag.split("}")[-1] == "PackageReference":
            refs.append({"name": el.get("Include"), "version": el.get("Version")})
    refs, truncated = (refs[:200], len(refs) > 200)
    return {"package_references": refs, "dependencies_truncated": truncated}


MANIFEST_PARSERS = {
    "package.json": parse_package_json,
    "pyproject.toml": parse_pyproject_toml,
    "requirements.txt": parse_requirements_txt,
    "go.mod": parse_go_mod,
    "cargo.toml": parse_cargo_toml,
    "pom.xml": parse_pom_xml,
    "gemfile": parse_gemfile,
    "composer.json": parse_composer_json,
}


def parse_manifest(root: Path, entry: dict, warnings: list[str]) -> dict | None:
    path = root / entry["path"]
    name = path.name.lower()
    if entry["kind"] != "manifest":
        return None
    if name.startswith("requirements") and name.endswith(".txt"):
        return parse_requirements_txt(path, warnings)
    if name.endswith(".csproj"):
        return parse_csproj(path, warnings)
    parser = MANIFEST_PARSERS.get(name)
    if parser is None:
        return None
    return parser(path, warnings)


# ---------------------------------------------------------------------------
# Config declared-key extraction — key NAMES only, never values
# ---------------------------------------------------------------------------

def declared_keys(path: Path) -> list[str] | None:
    name = path.name.lower()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if name in {".env.example", ".env.template", "env.example", "env.template"}:
        keys = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", text, re.M)
        return sorted(set(keys))
    if name.endswith(".properties"):
        keys = re.findall(r"^([A-Za-z0-9_.\-]+)\s*=", text, re.M)
        return sorted(set(keys))
    if name.endswith(".json"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return sorted(data.keys())
        except json.JSONDecodeError:
            return None
    if name.endswith((".yml", ".yaml")):
        keys = re.findall(r"^([A-Za-z0-9_.\-]+):", text, re.M)
        return sorted(set(keys))
    return None


# ---------------------------------------------------------------------------
# Workspace / monorepo detection
# ---------------------------------------------------------------------------

def detect_workspace(root: Path, manifests: list[dict]) -> list[dict]:
    signals = []
    for m in manifests:
        if m["ecosystem"] == "node" and m["kind"] == "manifest" and m.get("parsed", {}).get("workspaces"):
            signals.append({"type": "npm-or-yarn-workspaces", "members": m["parsed"]["workspaces"], "evidence": m["path"]})
        if m["ecosystem"] == "rust" and m.get("parsed", {}).get("workspace_members"):
            signals.append({"type": "cargo-workspace", "members": m["parsed"]["workspace_members"], "evidence": m["path"]})
    if (root / "pnpm-workspace.yaml").is_file():
        signals.append({"type": "pnpm-workspace", "members": None, "evidence": "pnpm-workspace.yaml"})
    if (root / "go.work").is_file():
        try:
            text = (root / "go.work").read_text(encoding="utf-8", errors="ignore")
            members = re.findall(r"^\s*\./?(\S+)\s*$", text, re.M)
        except OSError:
            members = None
        signals.append({"type": "go-work", "members": members or None, "evidence": "go.work"})
    if (root / "lerna.json").is_file():
        try:
            data = json.loads((root / "lerna.json").read_text(encoding="utf-8", errors="ignore"))
            members = data.get("packages")
        except (OSError, json.JSONDecodeError):
            members = None
        signals.append({"type": "lerna", "members": members, "evidence": "lerna.json"})
    return signals


# ---------------------------------------------------------------------------
# git / related / sibling repo helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None, timeout: int = 15) -> str | None:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def git_remotes(path: Path) -> list[dict]:
    out = run(["git", "remote", "-v"], cwd=path)
    if not out:
        return []
    seen = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            seen[parts[0]] = parts[1]
    return [{"name": k, "url": v} for k, v in seen.items()]


def git_info(root: Path) -> dict:
    is_repo = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root) == "true"
    if not is_repo:
        return {"is_repo": False, "remotes": [], "current_branch": None, "default_branch": None}
    branch = run(["git", "branch", "--show-current"], cwd=root)
    default_ref = run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=root)
    default_branch = default_ref.rsplit("/", 1)[-1] if default_ref else None
    return {
        "is_repo": True,
        "remotes": git_remotes(root),
        "current_branch": branch or None,
        "default_branch": default_branch,
    }


def related_repo_info(raw_path: str) -> dict:
    p = Path(raw_path).expanduser()
    exists = p.is_dir()
    is_git = exists and run(["git", "rev-parse", "--is-inside-work-tree"], cwd=p) == "true"
    return {
        "path": str(p),
        "exists": exists,
        "is_git_repo": bool(is_git),
        "remotes": git_remotes(p) if is_git else [],
    }


def sibling_repos(root: Path, cap: int = 20) -> list[dict]:
    parent = root.parent
    results = []
    try:
        entries = sorted(parent.iterdir())
    except OSError:
        return results
    for entry in entries:
        if len(results) >= cap:
            break
        if entry == root or not entry.is_dir():
            continue
        if (entry / ".git").exists():
            results.append({"path": str(entry), "remotes": git_remotes(entry)})
    return results


# ---------------------------------------------------------------------------
# Optional accelerators — feature-detected, silently skipped when absent
# ---------------------------------------------------------------------------

def loc_breakdown(root: Path, warnings: list[str]) -> dict | None:
    if which("tokei"):
        out = run(["tokei", "-o", "json", str(root)])
        if out:
            try:
                data = json.loads(out)
                langs = [
                    {"language": lang, "files": len(v.get("reports", [])), "code": v.get("code", 0),
                     "comments": v.get("comments", 0), "blanks": v.get("blanks", 0)}
                    for lang, v in data.items() if isinstance(v, dict) and lang != "Total"
                ]
                return {"tool": "tokei", "languages": langs}
            except (json.JSONDecodeError, AttributeError) as e:
                warnings.append(f"tokei ran but output could not be parsed: {e}")
    if which("scc"):
        out = run(["scc", "--format", "json", str(root)])
        if out:
            try:
                data = json.loads(out)
                langs = [
                    {"language": item.get("Name"), "files": item.get("Count"), "code": item.get("Code"),
                     "comments": item.get("Comment"), "blanks": item.get("Blank")}
                    for item in data
                ]
                return {"tool": "scc", "languages": langs}
            except (json.JSONDecodeError, TypeError) as e:
                warnings.append(f"scc ran but output could not be parsed: {e}")
    if which("cloc"):
        out = run(["cloc", "--json", str(root)])
        if out:
            try:
                data = json.loads(out)
                langs = [
                    {"language": lang, "files": v.get("nFiles"), "code": v.get("code"),
                     "comments": v.get("comment"), "blanks": v.get("blank")}
                    for lang, v in data.items() if isinstance(v, dict) and lang not in {"header", "SUM"}
                ]
                return {"tool": "cloc", "languages": langs}
            except (json.JSONDecodeError, AttributeError) as e:
                warnings.append(f"cloc ran but output could not be parsed: {e}")
    return None


def _purl_ecosystem(purl: str | None) -> str | None:
    if not purl or not purl.startswith("pkg:"):
        return None
    return purl.split(":", 1)[1].split("/", 1)[0]


def dependency_summary(root: Path, warnings: list[str]) -> dict | None:
    if not which("syft"):
        return None
    invocations = [
        ["syft", str(root), "-o", "cyclonedx-json", "--quiet"],
        ["syft", "scan", str(root), "-o", "cyclonedx-json", "--quiet"],
        ["syft", "packages", str(root), "-o", "cyclonedx-json", "--quiet"],
    ]
    out = None
    for cmd in invocations:
        out = run(cmd, timeout=60)
        if out:
            break
    if not out:
        warnings.append("syft is installed but no known invocation form succeeded")
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        warnings.append(f"syft ran but output could not be parsed: {e}")
        return None
    components = data.get("components") or []
    parsed = []
    for c in components:
        licenses = c.get("licenses") or []
        license_id = None
        if licenses:
            first = licenses[0].get("license") or {}
            license_id = first.get("id") or first.get("name")
        parsed.append({
            "name": c.get("name"),
            "version": c.get("version"),
            "ecosystem": _purl_ecosystem(c.get("purl")),
            "license": license_id,
        })
    truncated = len(parsed) > 500
    return {"tool": "syft", "components": parsed[:500], "truncated": truncated}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    if not args:
        sys.stderr.write("usage: project_overview_scan.py <root-dir> [--related=P1,P2] [--siblings]\n")
        return 1

    root_arg = None
    related_raw: list[str] = []
    check_siblings = False
    for a in args:
        if a == "--siblings":
            check_siblings = True
        elif a.startswith("--related="):
            related_raw = [p.strip() for p in a[len("--related="):].split(",") if p.strip()]
        elif not a.startswith("--"):
            root_arg = a

    if root_arg is None:
        sys.stderr.write("usage: project_overview_scan.py <root-dir> [--related=P1,P2] [--siblings]\n")
        return 1

    root = Path(root_arg).expanduser().resolve()
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 1

    warnings: list[str] = []
    secret_redactions: list[dict] = []

    classified = classify(root)

    manifests_out = []
    for entry in classified["manifest_files"]:
        parsed = parse_manifest(root, entry, warnings)
        manifests_out.append({**entry, "parsed": parsed})

    config_files_out = []
    for entry in classified["config_file_paths"]:
        path = root / entry
        if path.name in SKIP_FILES:
            continue
        keys = None
        try:
            keys = declared_keys(path)
        except Exception:  # noqa: BLE001 - never let one bad config file abort the scan
            keys = None
        config_files_out.append({"path": entry, "declared_keys": keys})

    # Best-effort secret scan limited to the files this pass already classified
    # as metadata/manifests/config/infra — not a full-repo secret audit (that
    # is security-audit's job on the *shared config tree*, not an arbitrary
    # target repo).
    template_names = {".env.example", ".env.template", "env.example", "env.template"}
    for bucket in (classified["manifest_files"], config_files_out):
        for entry in bucket:
            path = root / entry["path"]
            if path.name in SKIP_FILES or path.name.lower() in template_names:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                scan_line_for_secrets(entry["path"], lineno, line, secret_redactions)

    workspace_signals = detect_workspace(root, manifests_out)

    related_repos_out = [related_repo_info(p) for p in related_raw]
    siblings_out = sibling_repos(root) if check_siblings else None

    result = {
        "root": str(root),
        "git": git_info(root),
        "metadata_files": classified["metadata_files"],
        "manifests": manifests_out,
        "entry_point_candidates": classified["entry_point_hits"],
        "ci_cd_files": classified["ci_cd_files"],
        "infra_deploy_files": classified["infra_deploy_files"],
        "config_files": config_files_out,
        "source_layout": classified["source_layout"],
        "test_dirs": classified["test_dirs"],
        "workspace_signals": workspace_signals,
        "related_repos": related_repos_out,
        "sibling_repos": siblings_out,
        "loc_breakdown": loc_breakdown(root, warnings),
        "dependency_summary": dependency_summary(root, warnings),
        "secret_redactions": secret_redactions,
        "warnings": warnings,
        "files_visited": classified["files_visited"],
        "files_visited_capped": classified["files_visited_capped"],
    }
    print(json.dumps(result, indent=None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
