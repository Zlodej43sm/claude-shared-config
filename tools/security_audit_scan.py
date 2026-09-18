#!/usr/bin/env python3
"""
security_audit_scan — mechanical first pass over a shared Claude Code config
tree (skills/agents/tools/hooks/workflows + mcp.json + settings.json +
env template). Finds high-confidence secret shapes, filesystem-write call
sites, and declared tool/permission scopes. Does NOT judge portability or
justify scope — that requires reading the file in context, which is the
security-audit skill's job, not this script's.

SCHEMA_IN
  argv[1]  path to the root directory to scan (required)

SCHEMA_OUT  stdout JSON
  {
    "root": "<resolved absolute path>",
    "files_scanned": ["<path relative to root>", ...],
    "secret_findings": [
      {"file": "...", "line": N, "pattern": "github_token", "redacted": "ghp_AB…89"}
    ],
    "write_findings": [
      {"file": "...", "line": N, "text": "<the matching line, stripped>"}
    ],
    "scope_findings": [
      {"file": "...", "kind": "agent-frontmatter" | "mcp-server" | "settings-hook",
       "detail": {...}}
    ],
    "identifier_candidates": [
      {"file": "...", "line": N, "kind": "url" | "email" | "local-path", "value": "..."}
    ]
  }

EXIT  0=ok  1=root does not exist / is not a directory
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".idea", ".cache", "plans", "reviews", "worktrees",
}
SKIP_FILES = {".env", "settings.local.json"}
SKIP_FILE_SUFFIXES = (".lock", ".log", ".min.js")

INCLUDE_DIRNAMES = {"skills", "agents", "tools", "hooks", "workflows", "commands", "output-styles"}
INCLUDE_ROOT_FILES = {
    "mcp.json", ".mcp.json", "mcp.json.template", "settings.json",
    ".env.example", "env.example", "CLAUDE.md",
}

MAX_FILE_BYTES = 2_000_000


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
    if len(set(v)) <= 2 and len(v) > 6:  # repeated-char filler like 0000000 or xxxxxxx
        return True
    return False


def redact(value: str) -> str:
    v = value.strip().strip("\"'")
    if len(v) <= 8:
        return "…" * len(v)
    return f"{v[:4]}…{v[-4:]}"


# (name, compiled regex with the secret value as the LAST capture group, whole-match-is-secret)
SECRET_PATTERNS = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), False),
    ("aws_secret_key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?([A-Za-z0-9/+=]{40})[\"']?"), True),
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b"), True),
    ("github_pat", re.compile(r"\b(github_pat_[A-Za-z0-9_]{22,})\b"), True),
    ("slack_token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"), True),
    ("slack_webhook", re.compile(r"(https://hooks\.slack\.com/services/T[0-9A-Za-z]+/B[0-9A-Za-z]+/[0-9A-Za-z]+)"), True),
    ("google_api_key", re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"), True),
    ("stripe_live_key", re.compile(r"\b(sk_live_[0-9A-Za-z]{20,})\b"), True),
    ("jwt", re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{10,})\b"), True),
    ("bearer_header", re.compile(r"(?i)Authorization:\s*Bearer\s+([A-Za-z0-9\-_.=]{20,})"), True),
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
PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")

WRITE_CALL_PATTERNS = re.compile(
    r"\.write_text\(|\bopen\([^)]*[\"']w[ab]?[\"']|fs\.writeFile|fs\.writeFileSync|json\.dump\(|"
    r"\bmkdir\s+|\bcp\s+[\"'/$.~-]|git\s+add\b|git\s+commit\b|(?:(?<=\s)|^)>{1,2}\s*[\"'$~./]"
)

URL_RE = re.compile(r"https?://[^\s\"'<>()\]]+")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
LOCAL_PATH_RE = re.compile(r"(?:/Users/[^\s\"'<>()\]]+|/home/[^\s\"'<>()\]]+|C:\\\\Users\\\\[^\s\"'<>()\]]+)")


def iter_target_files(root: Path):
    # A shared-config repo has skills/agents/tools/... directly at its root.
    # A linked project instead has them under .claude/ (usually symlinks back
    # into the shared repo), with .mcp.json / CLAUDE.md staying at the repo
    # root. Check both bases so either layout — or a self-audit of the
    # shared repo itself — resolves correctly.
    bases = [root]
    claude_dir = root / ".claude"
    if claude_dir.is_dir():
        bases.append(claude_dir)

    seen: set[Path] = set()

    def emit(path: Path):
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        return path

    for base in bases:
        for dirname in sorted(INCLUDE_DIRNAMES):
            d = base / dirname
            if not d.is_dir():
                continue
            for path in sorted(d.rglob("*")):
                if not path.is_file():
                    continue
                if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                    continue
                if path.name in SKIP_FILES or path.name.endswith(SKIP_FILE_SUFFIXES):
                    continue
                if emit(path):
                    yield path
        for name in sorted(INCLUDE_ROOT_FILES):
            f = base / name
            if f.is_file() and emit(f):
                yield f


def read_lines(path: Path) -> list[str] | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None


def scan_secrets(rel: str, lines: list[str], out: list[dict]) -> None:
    for lineno, line in enumerate(lines, start=1):
        if PRIVATE_KEY_BLOCK.search(line):
            out.append({"file": rel, "line": lineno, "pattern": "private_key_block", "redacted": "-----BEGIN … PRIVATE KEY-----"})
        for name, pattern, has_group in SECRET_PATTERNS:
            for m in pattern.finditer(line):
                value = m.group(1) if has_group else m.group(0)
                if is_placeholder(value):
                    continue
                out.append({"file": rel, "line": lineno, "pattern": name, "redacted": redact(value)})


def scan_writes(rel: str, lines: list[str], out: list[dict]) -> None:
    for lineno, line in enumerate(lines, start=1):
        if WRITE_CALL_PATTERNS.search(line):
            out.append({"file": rel, "line": lineno, "text": line.strip()[:200]})


def scan_identifiers(rel: str, lines: list[str], out: list[dict]) -> None:
    for lineno, line in enumerate(lines, start=1):
        for m in URL_RE.finditer(line):
            out.append({"file": rel, "line": lineno, "kind": "url", "value": m.group(0)})
        for m in EMAIL_RE.finditer(line):
            out.append({"file": rel, "line": lineno, "kind": "email", "value": m.group(0)})
        for m in LOCAL_PATH_RE.finditer(line):
            out.append({"file": rel, "line": lineno, "kind": "local-path", "value": m.group(0)})


def parse_agent_frontmatter(rel: str, lines: list[str], out: list[dict]) -> None:
    if not lines or lines[0].strip() != "---":
        return
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return
    block = "\n".join(lines[1:end])
    detail: dict[str, str] = {}
    for m in re.finditer(r"^(\w[\w-]*)\s*:\s*(.+)$", block, re.MULTILINE):
        detail[m.group(1)] = m.group(2).strip().strip("'\"")
    if detail:
        out.append({"file": rel, "kind": "agent-frontmatter", "detail": detail})


def scan_mcp_json(rel: str, path: Path, out: list[dict]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return
    for server_name, cfg in (data.get("mcpServers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        out.append({
            "file": rel,
            "kind": "mcp-server",
            "detail": {
                "server": server_name,
                "command": cfg.get("command"),
                "args": cfg.get("args"),
                "env_keys": sorted((cfg.get("env") or {}).keys()) if isinstance(cfg.get("env"), dict) else [],
            },
        })


def scan_settings_json(rel: str, path: Path, out: list[dict]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            out.append({"file": rel, "kind": "settings-hook", "detail": {"event": event, "config": entries}})
    perms = data.get("permissions")
    if perms is not None:
        out.append({"file": rel, "kind": "settings-permissions", "detail": perms})


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: security_audit_scan.py <root-dir>\n")
        return 1
    root = Path(sys.argv[1]).expanduser().resolve()
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 1

    files_scanned: list[str] = []
    secret_findings: list[dict] = []
    write_findings: list[dict] = []
    scope_findings: list[dict] = []
    identifier_candidates: list[dict] = []

    for path in iter_target_files(root):
        rel = str(path.relative_to(root))
        lines = read_lines(path)
        if lines is None:
            continue
        files_scanned.append(rel)

        scan_secrets(rel, lines, secret_findings)
        scan_writes(rel, lines, write_findings)
        scan_identifiers(rel, lines, identifier_candidates)

        if path.suffix == ".md" and (path.parent.name == "agents" or "agents" in path.parts):
            parse_agent_frontmatter(rel, lines, scope_findings)
        if path.name in ("mcp.json", "mcp.json.template"):
            scan_mcp_json(rel, path, scope_findings)
        if path.name == "settings.json":
            scan_settings_json(rel, path, scope_findings)

    print(json.dumps({
        "root": str(root),
        "files_scanned": files_scanned,
        "secret_findings": secret_findings,
        "write_findings": write_findings,
        "scope_findings": scope_findings,
        "identifier_candidates": identifier_candidates,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
