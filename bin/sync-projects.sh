#!/usr/bin/env bash
# Re-link every project attached to this repo: adds symlinks for shared folders
# added since a project was linked, refreshes stale .mcp.json copies from
# mcp.json.template (backing the old copy up under .backups/), and reports
# settings.json drift and new env.example keys. Runs bin/link-project.sh on each.
#
# Usage: bin/sync-projects.sh [--dry-run] [--keep-mcp] [--verify] [--scan DIR]... [PROJECT...]
#
#   PROJECT...   sync only these projects (they're registered for future runs)
#   --scan DIR   also look under DIR (6 levels deep) for projects whose .claude/
#                links into this repo; repeatable. Default when no PROJECT is
#                given: the registry (.linked-projects) plus a scan of this
#                repo's parent directory.
#   --keep-mcp   leave a diverged .mcp.json alone (report it instead of refreshing)
#   --dry-run    show what would change, change nothing
#   --verify     after syncing, start a minimal headless Claude Code session in
#                each project and check every shared skill and agent is loaded
#                (one short model call per project)
#
# A project that keeps its own real .claude/{skills,...} directory (e.g. committed
# to its repo) gets each shared entry linked into it individually; its own
# same-named entries win. Such a project is only found by the scan once it has at
# least one of those links — link it the first time with bin/link-project.sh.
set -euo pipefail

SHARED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINK_SCRIPT="$SHARED_DIR/bin/link-project.sh"
REGISTRY="$SHARED_DIR/.linked-projects"

DRY_RUN=0
VERIFY=0
KEEP_MCP=0
scan_roots=()
explicit=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --keep-mcp) KEEP_MCP=1 ;;
    --verify) VERIFY=1 ;;
    --scan) [ $# -ge 2 ] || { echo "--scan needs a directory" >&2; exit 2; }; scan_roots+=("$2"); shift ;;
    -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) explicit+=("$1") ;;
  esac
  shift
done

candidates="$(mktemp)"
trap 'rm -f "$candidates"' EXIT

if [ "${#explicit[@]}" -gt 0 ]; then
  for p in "${explicit[@]}"; do
    (cd "$p" 2>/dev/null && pwd) >>"$candidates" || echo "skip: not a directory: $p" >&2
  done
else
  [ -f "$REGISTRY" ] && cat "$REGISTRY" >>"$candidates"
  [ "${#scan_roots[@]}" -gt 0 ] || scan_roots=("$(dirname "$SHARED_DIR")")
fi

# A project is "linked" when any symlink under its .claude/ points into this
# repo: .claude/<dir> itself, or .claude/<dir>/<entry> in merge mode.
for root in ${scan_roots[@]+"${scan_roots[@]}"}; do
  [ -d "$root" ] || { echo "skip scan: not a directory: $root" >&2; continue; }
  find "$root" -maxdepth 6 \( -name node_modules -o -name .git -o -name vendor \) -prune \
    -o -type l -path '*/.claude/*' -print 2>/dev/null |
    while IFS= read -r link; do
      case "$(readlink "$link")" in
        "$SHARED_DIR"/*) echo "${link%%/.claude/*}" ;;
      esac
    done >>"$candidates"
done

projects=()
while IFS= read -r p; do
  [ -n "$p" ] && [ "$p" != "$SHARED_DIR" ] && projects+=("$p")
done < <(sort -u "$candidates")

if [ "${#projects[@]}" -eq 0 ]; then
  echo "no linked projects found (link one with bin/link-project.sh <path>, or pass --scan DIR)"
  exit 0
fi

link_args=()
[ "$DRY_RUN" -eq 1 ] && link_args+=(--dry-run)
[ "$KEEP_MCP" -eq 1 ] || link_args+=(--refresh-mcp)

# verify_project <dir>: read the init event of a headless session (it lists the
# skills and agents Claude Code discovered) and compare with this repo's.
verify_project() {
  local out
  out="$(cd "$1" && claude -p "reply ok" --output-format stream-json --verbose --max-turns 1 2>/dev/null)" || true
  printf '%s\n' "$out" | python3 -I -c '
import json, os, sys
shared = sys.argv[1]
skills = {d for d in os.listdir(f"{shared}/skills") if os.path.isfile(f"{shared}/skills/{d}/SKILL.md")}
agents = {f[:-3] for f in os.listdir(f"{shared}/agents") if f.endswith(".md")}
for line in sys.stdin:
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if d.get("type") == "system" and d.get("subtype") == "init":
        miss_s = sorted(skills - set(d.get("skills") or []))
        miss_a = sorted(agents - set(d.get("agents") or []))
        print(f"verify: skills {len(skills) - len(miss_s)}/{len(skills)}, agents {len(agents) - len(miss_a)}/{len(agents)} loaded")
        for kind, miss in (("skills", miss_s), ("agents", miss_a)):
            if miss:
                print("verify: NOT loaded " + kind + ": " + " ".join(miss))
        sys.exit(1 if miss_s or miss_a else 0)
print("verify: no init event from `claude -p` (not installed or failed to start?)")
sys.exit(1)
' "$SHARED_DIR"
}

ok=()
failed=()
gone=()
for p in "${projects[@]}"; do
  echo
  echo "=== $p"
  if [ ! -d "$p" ]; then
    echo "project directory no longer exists"
    gone+=("$p")
    continue
  fi
  if "$LINK_SCRIPT" ${link_args[@]+"${link_args[@]}"} "$p"; then
    if [ "$VERIFY" -eq 1 ] && [ "$DRY_RUN" -eq 0 ] && ! verify_project "$p"; then
      failed+=("$p")
      continue
    fi
    ok+=("$p")
  else
    failed+=("$p")
  fi
done

if [ "${#gone[@]}" -gt 0 ] && [ -f "$REGISTRY" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo
    echo "would drop ${#gone[@]} missing project(s) from .linked-projects"
  else
    tmp="$(mktemp)"
    grep -vxF -f <(printf '%s\n' "${gone[@]}") "$REGISTRY" >"$tmp" || true
    mv "$tmp" "$REGISTRY"
  fi
fi

echo
echo "synced: ${#ok[@]}  failed: ${#failed[@]}  missing: ${#gone[@]}$([ "$DRY_RUN" -eq 1 ] && echo '  (dry run)')"
for p in ${failed[@]+"${failed[@]}"}; do echo "  failed: $p"; done
[ "${#failed[@]}" -eq 0 ]
