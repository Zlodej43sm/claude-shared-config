#!/usr/bin/env bash
# import_graph — cross-package @findfix/* import edges + tsconfig/package.json
# reference-sync check between the files changed in a diff range.
#
# Used by the split-pr skill to find out which "concerns" in a large diff
# actually depend on which other concerns (via real imports), instead of
# trusting file-name or commit-message guesses. This is deterministic —
# no LLM call — because it is a mechanical grep+parse job and getting the
# dependency direction wrong here silently produces a broken split order.
#
# SCHEMA_IN
#   $1  BASE_REF   e.g. develop or origin/develop
#   $2  HEAD_REF   e.g. feat/MA-207 (defaults to HEAD if omitted)
#
# SCHEMA_OUT  stdout  JSON {
#   "changed_files": ["packages/pipeline/src/activities.ts", ...],
#   "packages_touched": ["pipeline", "remediation", ...],
#   "edges": [
#     {"file": "packages/pipeline/src/activities.ts", "from_package": "pipeline",
#      "imports_package": "remediation", "specifiers": ["emitLibraryScript", "formatScript"]}
#   ],
#   "intra_package_edges": [
#     {"file": "packages/pipeline/src/kafka/workflowClient.ts",
#      "target_file": "packages/pipeline/src/workflows.ts", "package": "pipeline",
#      "specifiers": ["FindFixWorkflow"], "value_import": true}
#   ],
#   "reference_mismatches": [
#     {"package": "pipeline",
#      "issue": "package.json depends on @findfix/remediation but tsconfig.json has no matching project reference"}
#   ]
# }
#
# `edges` covers cross-package (@findfix/*) imports AND re-exports (an
# `export {X} from '@findfix/pkg'` creates the same build-ordering dependency
# as an import). `intra_package_edges` covers relative imports (`./x`, `../x`)
# between two files that are BOTH changed in this diff and in the SAME
# package — this repo builds each package as one `tsc -b` unit, so splitting
# such a pair across two PRs can leave the earlier one uncompilable even
# though no @findfix/* edge exists between them. `value_import: false` means
# the import was `import type`/`export type` (erased at build time — a lower-
# risk ordering constraint than a value import, but still worth checking).
#
# EXIT  0=ok  1=bad-args  2=git-error

set -euo pipefail

BASE_REF="${1:?ERROR: import_graph.sh requires BASE_REF as \$1}"
HEAD_REF="${2:-HEAD}"

if ! git rev-parse --verify "${BASE_REF}" >/dev/null 2>&1; then
  echo "ERROR: base ref '${BASE_REF}' not found" >&2
  exit 2
fi
if ! git rev-parse --verify "${HEAD_REF}" >/dev/null 2>&1; then
  echo "ERROR: head ref '${HEAD_REF}' not found" >&2
  exit 2
fi

NAME_STATUS_FILE=$(mktemp)
trap 'rm -f "$NAME_STATUS_FILE"' EXIT
git diff --name-status "${BASE_REF}...${HEAD_REF}" >"$NAME_STATUS_FILE"

python3 - "$HEAD_REF" "$NAME_STATUS_FILE" <<'PYEOF'
import json
import re
import subprocess
import sys

head_ref = sys.argv[1]
with open(sys.argv[2]) as fh:
    name_status_raw = fh.read()

changed_files = []
for line in name_status_raw.splitlines():
    if not line.strip():
        continue
    parts = line.split("\t")
    status, paths = parts[0], parts[1:]
    # Renames/copies (R100, C075, ...) report old-path, new-path; keep the new path.
    path = paths[-1]
    changed_files.append({"status": status[0], "path": path})

PKG_RE = re.compile(r"^packages/([^/]+)/")
packages_touched = sorted({
    m.group(1) for f in changed_files if (m := PKG_RE.match(f["path"]))
})

def show(ref, path):
    """Return file content at ref, or None if it doesn't exist there (e.g. deleted)."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else None

# Matches both `import {X} from '@findfix/pkg'` and `export {X} from '@findfix/pkg'`
# (a re-export creates the exact same build-ordering dependency as an import, but a
# plain "import"-only regex misses it — see LESSONS.md's git-ops/scriptSafety entry).
FINDFIX_IMPORT_RE = re.compile(
    r"(?:import|export)\s+(?:type\s+)?"
    r"(?:\{([^}]*)\}|([A-Za-z_$][\w$]*))"
    r"\s+from\s+['\"]@findfix/([a-zA-Z0-9_-]+)['\"]",
    re.DOTALL,
)

# Matches `import`/`export` ... `from './relative'` or `'../relative'` — used to
# catch INTRA-package ordering constraints (see below): this repo builds each
# package as one `tsc -b` unit, so a relative import between two files that are
# both changed in this diff can force one to land before the other even though
# they're in the same @findfix/* package and never show up as a cross-package edge.
RELATIVE_IMPORT_RE = re.compile(
    r"(import|export)\s+(type\s+)?"
    r"(?:\{([^}]*)\}|([A-Za-z_$][\w$]*))"
    r"\s+from\s+['\"](\.\.?/[^'\"]+)['\"]",
    re.DOTALL,
)

def parse_specifiers(named, default):
    if named:
        specifiers = []
        for s in named.split(","):
            s = s.strip().split(" as ")[0].strip()
            if s.startswith("type "):
                s = s[len("type "):].strip()
            if s:
                specifiers.append(s)
        return specifiers
    return [default] if default else []

def resolve_relative_import(importer_path, spec):
    """Resolve a './x' or '../x' import from importer_path to a repo-relative
    .ts path. Imports use explicit .js extensions (NodeNext ESM); source is .ts."""
    joined = posixpath = __import__("posixpath")
    base_dir = posixpath.dirname(importer_path)
    target = posixpath.normpath(posixpath.join(base_dir, spec))
    if target.endswith(".js"):
        target = target[: -len(".js")] + ".ts"
    elif not target.endswith(".ts") and not target.endswith(".tsx"):
        target = target + ".ts"
    return target

changed_paths = {f["path"] for f in changed_files}

edges = []
intra_package_edges = []
for f in changed_files:
    if f["status"] == "D":
        continue
    m = PKG_RE.match(f["path"])
    if not m:
        continue
    from_package = m.group(1)
    content = show(head_ref, f["path"])
    if content is None:
        continue

    for named, default, imported_pkg in FINDFIX_IMPORT_RE.findall(content):
        if imported_pkg not in packages_touched or imported_pkg == from_package:
            continue
        specifiers = parse_specifiers(named, default)
        edges.append({
            "file": f["path"],
            "from_package": from_package,
            "imports_package": imported_pkg,
            "specifiers": specifiers,
        })

    for keyword, type_kw, named, default, rel_spec in RELATIVE_IMPORT_RE.findall(content):
        target_path = resolve_relative_import(f["path"], rel_spec)
        if target_path == f["path"] or target_path not in changed_paths:
            continue
        target_m = PKG_RE.match(target_path)
        if not target_m or target_m.group(1) != from_package:
            continue  # only intra-PACKAGE edges belong here; cross-package relative imports don't exist in this workspace
        specifiers = parse_specifiers(named, default)
        intra_package_edges.append({
            "file": f["path"],
            "target_file": target_path,
            "package": from_package,
            "specifiers": specifiers,
            "value_import": not bool(type_kw),
        })

reference_mismatches = []
for pkg in packages_touched:
    pkg_json_raw = show(head_ref, f"packages/{pkg}/package.json")
    tsconfig_raw = show(head_ref, f"packages/{pkg}/tsconfig.json")
    if pkg_json_raw is None or tsconfig_raw is None:
        continue
    try:
        pkg_json = json.loads(pkg_json_raw)
    except json.JSONDecodeError:
        reference_mismatches.append({"package": pkg, "issue": "package.json did not parse as JSON at head_ref"})
        continue
    try:
        # tsconfig.json is JSONC (// line comments, trailing commas allowed);
        # strip both before parsing since json.loads rejects them.
        jsonc_stripped = re.sub(r"^\s*//.*$", "", tsconfig_raw, flags=re.MULTILINE)
        jsonc_stripped = re.sub(r",(\s*[}\]])", r"\1", jsonc_stripped)
        tsconfig = json.loads(jsonc_stripped)
    except json.JSONDecodeError:
        reference_mismatches.append({"package": pkg, "issue": "tsconfig.json did not parse even after stripping // comments and trailing commas"})
        continue

    deps = {**pkg_json.get("dependencies", {}), **pkg_json.get("devDependencies", {})}
    findfix_deps = {d.split("/", 1)[1] for d in deps if d.startswith("@findfix/")}
    ref_paths = {
        r.get("path", "").split("/")[-1]
        for r in tsconfig.get("references", [])
        if isinstance(r, dict)
    }
    for dep in sorted(findfix_deps - ref_paths):
        reference_mismatches.append({
            "package": pkg,
            "issue": f"package.json depends on @findfix/{dep} but tsconfig.json has no matching project reference",
        })

print(json.dumps({
    "changed_files": [f["path"] for f in changed_files],
    "packages_touched": packages_touched,
    "edges": edges,
    "intra_package_edges": intra_package_edges,
    "reference_mismatches": reference_mismatches,
}, indent=2))
PYEOF
