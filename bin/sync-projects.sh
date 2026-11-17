#!/usr/bin/env bash
# Re-link every project attached to this repo: adds symlinks for shared folders
# added since a project was linked, refreshes stale .mcp.json copies from
# mcp.json.template (backing the old copy up under .backups/), and reports
# settings.json drift and new env.example keys. Runs bin/link-project.sh on each.
#
# Usage: bin/sync-projects.sh [--dry-run] [--keep-mcp] [--scan DIR]... [PROJECT...]
#
#   PROJECT...   sync only these projects (they're registered for future runs)
#   --scan DIR   also look under DIR (5 levels deep) for projects whose .claude/
#                links into this repo; repeatable. Default when no PROJECT is
#                given: the registry (.linked-projects) plus a scan of this
#                repo's parent directory.
#   --keep-mcp   leave a diverged .mcp.json alone (report it instead of refreshing)
#   --dry-run    show what would change, change nothing
#
# A project whose .claude/{skills,...} are real directories (an old copy, not
# symlinks) isn't found by the scan, and fails if named explicitly: converting
# it deletes files the project may track in git, so do that by hand.
set -euo pipefail

SHARED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINK_SCRIPT="$SHARED_DIR/bin/link-project.sh"
REGISTRY="$SHARED_DIR/.linked-projects"

DRY_RUN=0
KEEP_MCP=0
scan_roots=()
explicit=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --keep-mcp) KEEP_MCP=1 ;;
    --scan) [ $# -ge 2 ] || { echo "--scan needs a directory" >&2; exit 2; }; scan_roots+=("$2"); shift ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# A project is "linked" when any .claude/<dir> symlink points into this repo.
for root in ${scan_roots[@]+"${scan_roots[@]}"}; do
  [ -d "$root" ] || { echo "skip scan: not a directory: $root" >&2; continue; }
  find "$root" -maxdepth 5 \( -name node_modules -o -name .git -o -name vendor \) -prune \
    -o -type l -path '*/.claude/*' -print 2>/dev/null |
    while IFS= read -r link; do
      case "$(readlink "$link")" in
        "$SHARED_DIR"/*) dirname "$(dirname "$link")" ;;
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
