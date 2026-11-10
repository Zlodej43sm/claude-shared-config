#!/usr/bin/env python3
"""
security_audit_scan — mechanical first pass for the security-audit skill.

--mode=config (default): a Claude Code config tree (skills/agents/tools/hooks/
workflows + mcp.json + settings.json + their templates + env template; for a
shared source-of-truth repo also bin/ and README.md; inside those dirs, files git
ignores and binary files are skipped). Finds high-confidence
secret shapes, filesystem-write call sites, and declared tool/permission scopes.

--mode=code: an application's source (files git does not ignore when the root is a git
repo, minus .claude/ and vendored/build dirs). Finds secret shapes, risky sink
call sites per category, HTTP route definitions and dependency manifests.

Neither mode judges anything — whether a hit is reachable, exploitable or
already guarded needs the file read in context, which is the skill's job.

SCHEMA_IN
  argv     [--mode=config|code] <root-dir>

SCHEMA_OUT  stdout JSON, --mode=config
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
      {"file": "...", "kind": "agent-frontmatter" | "mcp-server" | "settings-hook" | "settings-permissions",
       "detail": {...}}
    ],
    "identifier_candidates": [
      {"file": "...", "line": N, "kind": "url" | "email" | "local-path", "value": "..."}
    ]
  }

SCHEMA_OUT  stdout JSON, --mode=code
  {
    "root": "...", "mode": "code",
    "files_scanned": [...],
    "secret_findings": [ same shape as config mode, plus "test": bool ],
    "sink_findings": [
      {"file": "...", "line": N, "category": "injection" | "deserialization" | "ssrf" |
       "path-traversal" | "xss" | "crypto" | "tls" | "auth-token" | "security-config" |
       "sensitive-logging" | "open-redirect" | "container",
       "pattern": "<name>", "text": "<line, secrets masked, max 200 chars>", "test": bool}
    ],
    "route_candidates": [{"file": "...", "line": N, "text": "..."}],
    "dependency_manifests": ["<path relative to root>", ...]
  }
  "test" is true for files under test/tests/__tests__/spec dirs or named
  test_*, *_test.*, *.test.*, *.spec.*.

EXIT  0=ok  1=bad usage / root does not exist / is not a directory
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Directories skipped at any depth (directory names only, never a file's own name).
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea",
}
# Config mode keeps build/ and dist/: config folders are small and named by humans, so a
# skills/build/ or tools/dist/ folder is real content, not build output.
CONFIG_SKIP_DIRS = SKIP_DIRS - {"build", "dist"}
# Claude Code runtime output: skipped only directly under .claude/, so a skills/x/reviews/
# folder in the config tree is still scanned.
CLAUDE_RUNTIME_DIRS = {"plans", "reviews", "worktrees", ".cache"}
SKIP_FILES = {".env", "settings.local.json"}
SKIP_FILE_SUFFIXES = (".lock", ".log", ".min.js")

INCLUDE_DIRNAMES = {"skills", "agents", "tools", "hooks", "workflows", "commands", "output-styles"}
INCLUDE_ROOT_FILES = {
    "mcp.json", ".mcp.json", "mcp.json.template", "settings.json",
    "settings.json.template", ".env.example", "env.example", "CLAUDE.md",
}
# Only in a shared source-of-truth repo (skills/ at the root): its README and
# bin/ scripts ship to every linked project. A linked project's own README is
# project-specific by design, so it is not scanned.
SHARED_REPO_DIRNAMES = {"bin"}
SHARED_REPO_ROOT_FILES = {"README.md"}
SETTINGS_FILES = ("settings.json", "settings.json.template")

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
            r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|access[_-]?key|private[_-]?key|credential)s?\s*[:=]\s*[\"']?([A-Za-z0-9/+_.\-]{12,})(?![A-Za-z0-9/+_.\-]*\()[\"']?"
        ),
        True,
    ),
]
PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")

WRITE_CALL_PATTERNS = re.compile(
    r"\.write_text\(|\bopen\([^)]*[\"'](?:[wax][bt+]*|r[bt]?\+[bt]?)[\"']|fs\.writeFile|fs\.writeFileSync|json\.dump\(|"
    r"\bos\.(?:fdopen|open|makedirs)\(|\.mkdir\(|\.extractall\(|\bln\s+-s|"
    r"\bmkdir\s+|\bcp\s+[\"'/$.~-]|git\s+add\b|git\s+commit\b|(?:(?<=\s)|^)>{1,2}\s*[\"'$~./]|"
    r"\btempfile\.(?:mkstemp|NamedTemporaryFile)\(|\bos\.(?:replace|rename)\(|\bshutil\.(?:copy\w*|move)\(|"
    r"\.write_bytes\(|\btee\s+(?:-a\s+)?[\"'/$.~\w-]|\bmv\s+(?:-[A-Za-z]+\s+)*[\"'$~./\w-]*[\"'/$.]|"
    r"\btouch\s+[\"'$~./\w-]*[\"'/$.]|\bsed\s+(?:-[A-Za-z]+\s+)*(?:-[A-Za-z]*i|--in-place)\b"
)

URL_RE = re.compile(r"https?://[^\s\"'<>()\]]+")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
LOCAL_PATH_RE = re.compile(r"(?:/Users/[^\s\"'<>()\]]+|/home/[^\s\"'<>()\]]+|C:\\\\Users\\\\[^\s\"'<>()\]]+)")


def skipped_dir(parts: tuple[str, ...]) -> bool:
    """`parts`: a file's path relative to the root; its last part is the file name."""
    if any(part in CONFIG_SKIP_DIRS for part in parts[:-1]):
        return True
    return len(parts) > 2 and parts[0] == ".claude" and parts[1] in CLAUDE_RUNTIME_DIRS


def git_ignored(directory: Path, paths: list[Path]) -> set[Path]:
    """The `paths` (all under `directory`) that git ignores. Empty when `directory`
    is not in a git work tree or git fails (e.g. a path beyond a symlink)."""
    if not paths:
        return set()
    d = directory.resolve()
    rels = [str(p.resolve().relative_to(d)) for p in paths if p.resolve().is_relative_to(d)]
    try:
        out = subprocess.run(
            ["git", "-C", str(d), "check-ignore", "-z", "--stdin"],
            input="\0".join(rels).encode() + b"\0", capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode not in (0, 1):
        return set()
    ignored = {d / r for r in out.stdout.decode("utf-8", "ignore").split("\0") if r}
    return {p for p in paths if p.resolve() in ignored}


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return b"\0" in fh.read(8192)
    except OSError:
        return True


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

    shared_repo = (root / "skills").is_dir()

    for base in bases:
        dirnames = INCLUDE_DIRNAMES | (SHARED_REPO_DIRNAMES if shared_repo and base == root else set())
        root_files = INCLUDE_ROOT_FILES | (SHARED_REPO_ROOT_FILES if shared_repo and base == root else set())
        for dirname in sorted(dirnames):
            d = base / dirname
            if not d.is_dir():
                continue
            candidates = [
                path for path in sorted(d.rglob("*"))
                if path.is_file()
                and not skipped_dir(path.relative_to(root).parts)
                and path.name not in SKIP_FILES and not path.name.endswith(SKIP_FILE_SUFFIXES)
            ]
            # git-ignored files (.DS_Store, caches) never ship; binaries have nothing to read
            ignored = git_ignored(d, candidates)
            for path in candidates:
                if path not in ignored and not is_binary(path) and emit(path):
                    yield path
        # Named config files are scanned even when git ignores them (a generated .mcp.json).
        for name in sorted(root_files):
            f = base / name
            if f.is_file() and not is_binary(f) and emit(f):
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


# ---------------------------------------------------------------------------
# --mode=code
# ---------------------------------------------------------------------------

CODE_SKIP_DIRS = SKIP_DIRS | {
    ".cache", ".claude", "vendor", "third_party", "coverage", ".next", ".nuxt", "out",
    "target", ".terraform", ".gradle", "bower_components", "site-packages",
}
CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".go", ".java", ".kt", ".scala", ".rb", ".php", ".cs", ".rs", ".sh",
    ".html", ".htm", ".njk", ".hbs", ".ejs", ".jinja", ".j2",
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".tf", ".sql", ".graphql", ".gql",
}
CODE_NAMES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Makefile", ".env.example", "env.example"}
MANIFEST_NAMES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock",
    "go.mod", "go.sum", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "Gemfile.lock",
    "composer.json", "composer.lock", "Cargo.toml", "Cargo.lock",
}
TEST_DIR_PARTS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "features", "fixtures", "__mocks__"}
TEST_NAME_RE = re.compile(r"(^test_.*|.*_test\.[^.]+|.*\.(test|spec)\.[^.]+)$")

# (category, name, regex). One hit per line per pattern. These are leads, not
# verdicts: the skill decides reachability and whether a guard already exists.
_HTTP_CALL = r"(?:\bfetch|\baxios(?:\.(?:get|post|put|patch|delete|request))?|\bgot(?:\.\w+)?|\bsuperagent\.\w+|\bhttps?\.(?:get|request)|\brequests\.(?:get|post|put|patch|delete|request|head)|\bhttpx\.(?:get|post|put|patch|delete|request|stream)|\burlopen|\bnew\s+URL)\("
_USER_INPUT = r"(?:\breq(?:uest)?\.(?:params|query|body|args|form|files|GET|POST|headers|cookies)\b|\bctx\.(?:params|query|request)\b|\bevent\.(?:body|queryStringParameters|pathParameters)\b|@(?:Param|Query|Body)\()"
SINK_PATTERNS = [
    # injection
    ("injection", "sql_interpolation", re.compile(r"(?i)(?:f[\"']|`|[\"'])[^\"'`]*\b(?:select\s.+\sfrom|insert\s+into|update\s+\w+\s+set|delete\s+from)\b[^\"'`]*(?:\{|\$\{|%s|%\(|\"\s*\+|'\s*\+|`\s*\+)")),
    ("injection", "sql_format_call", re.compile(r"(?i)\b(?:select|insert|update|delete)\b.*[\"']\s*(?:%\s*[\w(]|\.format\()")),
    ("injection", "raw_query_api", re.compile(r"\.(?:raw|\$queryRawUnsafe|\$executeRawUnsafe|unsafe)\(|\bsequelize\.literal\(|\bknex\.raw\(|\btext\(\s*f[\"']")),
    ("injection", "shell_command", re.compile(r"\bchild_process\b|\bexecSync\(|\bexec\(\s*[`\"'\w]|\bspawn(?:Sync)?\([^)]*shell\s*:\s*true|\bsubprocess\.\w+\([^)]*shell\s*=\s*True|\bos\.(?:system|popen)\(|Runtime\.getRuntime\(\)\.exec|\bProcessBuilder\(")),
    ("injection", "dynamic_eval", re.compile(r"(?<![\w.])eval\(|\bnew\s+Function\(|\bvm\.runIn\w*\(|\bsetTimeout\(\s*[\"'`]|\bexec\(\s*compile\(|\b__import__\(\s*(?![\"'])|(?:^|[;&|]\s*)eval\s+[\"'$]")),
    ("injection", "nosql_operator", re.compile(r"[\"']\$where[\"']|\$where\s*:")),
    ("injection", "template_from_input", re.compile(r"\brender_template_string\(|\bTemplate\(\s*" + _USER_INPUT)),
    # deserialization
    ("deserialization", "unsafe_deserialize", re.compile(r"\bpickle\.loads?\(|\bcPickle\.loads?\(|\bmarshal\.loads?\(|\bshelve\.open\(|\bjsonpickle\.decode\(|\bdill\.loads?\(|\bObjectInputStream\(|\bunserialize\(|node-serialize|\byaml\.(?:load|load_all)\((?![^)]*Safe)|\bYAML\.load\(|\btorch\.load\((?![^)]*weights_only\s*=\s*True)")),
    # ssrf / outbound
    ("ssrf", "outbound_with_input", re.compile(_HTTP_CALL + r"[^)\n]*" + _USER_INPUT)),
    ("ssrf", "outbound_templated_url", re.compile(_HTTP_CALL + r"\s*(?:`[^`]*\$\{|f[\"'][^\"']*\{)")),
    # path traversal / files
    ("path-traversal", "file_access_with_input", re.compile(r"(?:readFile(?:Sync)?|createReadStream|writeFile(?:Sync)?|sendFile|res\.download|\bopen|send_file|send_from_directory|FileResponse|Path|path\.(?:join|resolve)|os\.path\.join|unlink(?:Sync)?|rm(?:Sync)?)\([^)\n]*" + _USER_INPUT)),
    ("path-traversal", "archive_extract", re.compile(r"\.extractall\(|\bunzipper\b|\badm-zip\b|\btar\.x\(|\bextract-zip\b")),
    # xss / output
    ("xss", "raw_html_sink", re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*=|\.outerHTML\s*=|\binsertAdjacentHTML\(|\bv-html\b|\{@html\b|\[innerHTML\]|bypassSecurityTrust\w*\(|\bdocument\.write\(|\|\s*safe\b|\bmark_safe\(|\bMarkup\(|<%-")),
    ("open-redirect", "redirect_with_input", re.compile(r"(?:\bredirect|\bres\.redirect|\bRedirectResponse|\bHttpResponseRedirect|window\.location(?:\.href)?\s*=)\s*\(?[^)\n;]*" + _USER_INPUT)),
    # crypto
    ("crypto", "weak_hash", re.compile(r"(?i)\bhashlib\.(?:md5|sha1)\(|createHash\(\s*[\"'](?:md5|sha1)[\"']|MessageDigest\.getInstance\(\s*\"(?:MD5|SHA-?1)\"|\bmd5\(|\bsha1\(")),
    ("crypto", "weak_cipher", re.compile(r"(?i)\bcreateCipher\(|\b(?:DES|3DES|RC4|Blowfish)\b|\bAES/ECB\b|\bMODE_ECB\b|['\"]aes-\d+-ecb['\"]")),
    ("crypto", "non_crypto_random_for_secret", re.compile(r"(?i)(?:Math\.random\(\)|\brandom\.(?:random|randint|choice|choices|getrandbits)\(|\bnew\s+Random\().*\b(?:token|secret|password|passwd|nonce|otp|salt|session|apikey|api_key|reset|verification|invite)\b|\b(?:token|secret|password|nonce|otp|salt|session|reset|verification|invite)\w*\s*[=:].*(?:Math\.random\(\)|\brandom\.(?:random|randint|choice|choices|getrandbits)\()")),
    # tls
    ("tls", "tls_verification_off", re.compile(r"\bverify\s*=\s*False\b|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED|InsecureSkipVerify\s*:\s*true|_create_unverified_context|\bCERT_NONE\b|check_hostname\s*=\s*False|strictSSL\s*:\s*false")),
    ("tls", "plain_http_url", re.compile(r"[\"'`]http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|www\.w3\.org|schemas\.|json-schema\.org|example\.)[^\"'`\s]+")),
    # auth tokens
    ("auth-token", "jwt_unverified", re.compile(r"(?i)algorithms?\s*[:=]\s*\[?\s*[\"']none[\"']|verify_signature[\"']?\s*:\s*False|jwt\.decode\([^)]*verify\s*=\s*False|ignoreExpiration\s*:\s*true|\bjwt\.decode\((?![^)]*(?:algorithms|key|secret))|\.decode\(\s*\w+\s*,\s*options\s*=\s*\{[^}]*verify")),
    ("auth-token", "timing_unsafe_compare", re.compile(r"(?i)\b(?:token|secret|signature|hmac|api_?key|password|digest)\w*\s*(?:===?|!==?)\s*\w+|\b\w+\s*(?:===?|!==?)\s*\w*(?:token|secret|signature|hmac|api_?key|digest)\b")),
    # security config
    ("security-config", "cors_wildcard", re.compile(r"(?i)origin\s*:\s*[\"']\*[\"']|origin\s*:\s*true\b|Access-Control-Allow-Origin[\"']?\s*[,:]\s*[\"']\*|allow_origins\s*=\s*\[\s*[\"']\*|CORS_ALLOW_ALL_ORIGINS\s*=\s*True|AllowAnyOrigin\(")),
    ("security-config", "cookie_flags_off", re.compile(r"(?i)httpOnly\s*[:=]\s*false|\bsecure\s*[:=]\s*false|sameSite\s*[:=]\s*[\"']none[\"']|SESSION_COOKIE_SECURE\s*=\s*False|CSRF_COOKIE_SECURE\s*=\s*False")),
    ("security-config", "debug_enabled", re.compile(r"\bDEBUG\s*=\s*True\b|\.run\([^)]*debug\s*=\s*True|app\.debug\s*=\s*True")),
    ("security-config", "csrf_disabled", re.compile(r"(?i)csrf_exempt|csrf\(\)\.disable\(|WTF_CSRF_ENABLED\s*=\s*False|csrf\s*:\s*false")),
    ("security-config", "bind_all_interfaces", re.compile(r"[\"']0\.0\.0\.0[\"']")),
    # logging
    ("sensitive-logging", "secret_in_log", re.compile(r"(?i)(?:\blog(?:ger)?|\bconsole|\blogging|\bprint)\b[\w.]*\(.*\b(?:password|passwd|token|secret|authorization|cookie|api_?key|card_?number|cvv|iban|ssn)\b")),
    # containers
    ("container", "docker_latest_or_root", re.compile(r"^\s*FROM\s+\S+:latest\b|^\s*FROM\s+[^\s:@]+\s*(?:AS\s+\w+)?\s*$|^\s*USER\s+root\b", re.IGNORECASE)),
]
TEMPLATE_SUFFIXES = {".hbs", ".handlebars", ".mustache", ".html", ".htm"}
TEMPLATE_RAW_RE = re.compile(r"\{\{\{[^}]+\}\}\}")  # Handlebars/Mustache unescaped output
ROUTE_RE = re.compile(
    r"@(?:\w+\.)?(?:route|get|post|put|patch|delete|api_route|websocket)\(|"
    r"\b(?:app|router|server|api|route[rs]?)\.(?:get|post|put|patch|delete|all|use|route)\(\s*[\"'`/]|"
    r"@(?:Get|Post|Put|Patch|Delete|Request)Mapping\b|@(?:Get|Post|Put|Patch|Delete|All)\(|"
    r"\bpath\(\s*[\"']|\bre_path\(|\bHandleFunc\(|\bfastify\.(?:get|post|put|patch|delete|route)\(|"
    r"\bexport\s+(?:async\s+)?function\s+(?:GET|POST|PUT|PATCH|DELETE)\b|\bResolver\(|@(?:Query|Mutation)\("
)


def mask_secrets(text: str) -> str:
    for _name, pattern, has_group in SECRET_PATTERNS:
        def _sub(m):
            value = m.group(1) if has_group else m.group(0)
            return m.group(0) if is_placeholder(value) else m.group(0).replace(value, redact(value))
        text = pattern.sub(_sub, text)
    return text


def is_test_path(rel: Path) -> bool:
    return any(p.lower() in TEST_DIR_PARTS for p in rel.parts[:-1]) or bool(TEST_NAME_RE.match(rel.name))


def _has_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def iter_code_files(root: Path):
    rels: list[Path] | None = None
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8", "ignore")
        rels = [Path(p) for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        rels = None
    if rels is None:
        rels = [p.relative_to(root) for p in root.rglob("*") if p.is_file()]
    own = Path(__file__).resolve()
    for rel in sorted(set(rels)):
        if any(part in CODE_SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if (root / rel).resolve() == own:  # its pattern table matches every rule
            continue
        name = rel.name
        if name in SKIP_FILES or name.endswith(SKIP_FILE_SUFFIXES):
            continue
        if rel.suffix in CODE_SUFFIXES or name in CODE_NAMES or name.startswith("Dockerfile") or name in MANIFEST_NAMES or (not rel.suffix and _has_shebang(root / rel)):
            path = root / rel
            if path.is_file():
                yield rel, path


def run_code_mode(root: Path) -> dict:
    files_scanned: list[str] = []
    secret_findings: list[dict] = []
    sink_findings: list[dict] = []
    route_candidates: list[dict] = []
    manifests: list[str] = []

    for rel, path in iter_code_files(root):
        rel_s = str(rel)
        if rel.name in MANIFEST_NAMES:
            manifests.append(rel_s)
            if rel.name not in {"package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "Pipfile"}:
                continue  # lockfiles: list only
        lines = read_lines(path)
        if lines is None:
            continue
        files_scanned.append(rel_s)
        test = is_test_path(rel)

        found: list[dict] = []
        scan_secrets(rel_s, lines, found)
        for f in found:
            f["test"] = test
        secret_findings.extend(found)

        for lineno, line in enumerate(lines, start=1):
            if len(line) > 1000:  # minified or generated
                continue
            hits = [(c, n) for c, n, pat in SINK_PATTERNS if pat.search(line)]
            if rel.suffix in TEMPLATE_SUFFIXES and TEMPLATE_RAW_RE.search(line):
                hits.append(("xss", "raw_html_sink"))
            for category, name in hits:
                sink_findings.append({
                    "file": rel_s, "line": lineno, "category": category, "pattern": name,
                    "text": mask_secrets(line.strip())[:200], "test": test,
                })
            if not test and ROUTE_RE.search(line):
                route_candidates.append({"file": rel_s, "line": lineno, "text": mask_secrets(line.strip())[:200]})

    return {
        "root": str(root),
        "mode": "code",
        "files_scanned": files_scanned,
        "secret_findings": secret_findings,
        "sink_findings": sink_findings,
        "route_candidates": route_candidates,
        "dependency_manifests": manifests,
    }


def main() -> int:
    usage = "usage: security_audit_scan.py [--mode=config|code] <root-dir>\n"
    mode = "config"
    positional: list[str] = []
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        else:
            positional.append(arg)
    if mode not in ("config", "code") or len(positional) != 1:
        sys.stderr.write(usage)
        return 1
    root = Path(positional[0]).expanduser().resolve()
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 1

    if mode == "code":
        print(json.dumps(run_code_mode(root)))
        return 0

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
        if path.name in ("mcp.json", ".mcp.json", "mcp.json.template"):
            scan_mcp_json(rel, path, scope_findings)
        if path.name in SETTINGS_FILES:
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
