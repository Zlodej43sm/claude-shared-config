#!/usr/bin/env bash
# Wire a project's .claude/ to this shared skills/agents/tools/hooks/workflows source of truth.
#
# Usage: bin/link-project.sh [--refresh-mcp] [--dry-run] <path-to-project-repo>
#
# - Symlinks .claude/{skills,agents,tools,hooks,workflows} to this repo's copies.
# - Generates <project>/.mcp.json from mcp.json.template (a real file, not a
#   symlink, in case an MCP client requires that). An existing .mcp.json that
#   differs from the template is refused, unless --refresh-mcp is given: then the
#   old copy is backed up under this repo's .backups/ and replaced (per-project
#   values belong in .claude/.env, which the template's {{VAR}} placeholders read).
# - Generates <project>/.claude/settings.json from settings.json.template the
#   same way, only if one doesn't already exist — once generated, a project is
#   free to diverge from the template (different permissions, extra hooks) and
#   this script will never overwrite it silently.
# - Appends to <project>/.gitignore whichever of .claude/.env,
#   .claude/settings.local.json and .mcp.json git does not already ignore: they
#   hold per-project values and the session's ANTHROPIC_API_KEY.
# - Records the project in this repo's .linked-projects (gitignored), which
#   bin/sync-projects.sh reads to refresh every linked project at once.
# - Never touches .claude/.env, .claude/settings.local.json, or anything else
#   project-specific.
# - --dry-run prints what would change and changes nothing.
set -euo pipefail

SHARED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Every top-level directory a project's .claude/ links to. Add new shared
# folders here; bin/sync-projects.sh picks them up for all linked projects.
LINK_DIRS=(skills agents tools hooks workflows)
REGISTRY="$SHARED_DIR/.linked-projects"

usage() { echo "Usage: link-project.sh [--refresh-mcp] [--dry-run] <path-to-project-repo>" >&2; exit 2; }

REFRESH_MCP=0
DRY_RUN=0
PROJECT_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --refresh-mcp) REFRESH_MCP=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [ -z "$PROJECT_DIR" ] || usage; PROJECT_DIR="$1" ;;
  esac
  shift
done
[ -n "$PROJECT_DIR" ] || usage
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
CLAUDE_DIR="$PROJECT_DIR/.claude"

if [ "$PROJECT_DIR" = "$SHARED_DIR" ]; then
  echo "refusing to link the shared config repo into itself" >&2
  exit 1
fi

# would <message>: in --dry-run, report and return 1 so the caller skips the action.
would() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "would $*"
    return 1
  fi
  return 0
}

if [ ! -d "$CLAUDE_DIR" ] && would "create $CLAUDE_DIR"; then
  mkdir -p "$CLAUDE_DIR"
fi

for name in "${LINK_DIRS[@]}"; do
  target="$CLAUDE_DIR/$name"
  if [ -L "$target" ]; then
    link_dest="$(readlink "$target")"
    if [ "$link_dest" != "$SHARED_DIR/$name" ]; then
      echo "refusing to replace symlink with a different destination: $target -> $link_dest" >&2
      exit 1
    fi
    # Already linked correctly. Do NOT fall through to `ln -s` below — since
    # $target is a symlink to a directory, `ln -s SRC $target` would silently
    # place a new symlink named "$name" *inside* that directory instead of
    # erroring, nesting it (e.g. hooks/hooks -> hooks) on every re-run.
    echo "already linked: $target -> $SHARED_DIR/$name"
    continue
  elif [ -e "$target" ]; then
    echo "refusing to overwrite existing non-symlink: $target (remove/merge it manually first)" >&2
    exit 1
  fi
  if would "link $target -> $SHARED_DIR/$name"; then
    ln -s "$SHARED_DIR/$name" "$target"
    echo "linked $target -> $SHARED_DIR/$name"
  fi
done

if [ -e "$PROJECT_DIR/.mcp.json" ]; then
  if cmp -s "$SHARED_DIR/mcp.json.template" "$PROJECT_DIR/.mcp.json"; then
    echo "existing .mcp.json matches template; left unchanged"
  elif [ "$REFRESH_MCP" -eq 1 ]; then
    backup_dir="$SHARED_DIR/.backups/$(basename "$PROJECT_DIR")"
    backup="$backup_dir/mcp.json.$(date +%Y%m%d-%H%M%S)"
    if would "replace diverged .mcp.json with mcp.json.template (old copy backed up to $backup)"; then
      mkdir -p "$backup_dir"
      cp "$PROJECT_DIR/.mcp.json" "$backup"
      cp "$SHARED_DIR/mcp.json.template" "$PROJECT_DIR/.mcp.json"
      echo "refreshed .mcp.json from mcp.json.template (old copy: $backup)"
    fi
  else
    echo "refusing to overwrite existing .mcp.json: $PROJECT_DIR/.mcp.json (re-run with --refresh-mcp to replace it, keeping a backup)" >&2
    exit 1
  fi
elif would "generate $PROJECT_DIR/.mcp.json from mcp.json.template"; then
  cp "$SHARED_DIR/mcp.json.template" "$PROJECT_DIR/.mcp.json"
  echo "generated $PROJECT_DIR/.mcp.json from mcp.json.template"
fi

if [ -e "$CLAUDE_DIR/settings.json" ]; then
  if cmp -s "$SHARED_DIR/settings.json.template" "$CLAUDE_DIR/settings.json"; then
    echo "existing .claude/settings.json matches template; left unchanged"
  else
    echo "existing .claude/settings.json diverges from template; left unchanged (this is expected once a project customizes it)"
  fi
elif would "generate $CLAUDE_DIR/settings.json from settings.json.template"; then
  cp "$SHARED_DIR/settings.json.template" "$CLAUDE_DIR/settings.json"
  echo "generated $CLAUDE_DIR/settings.json from settings.json.template"
fi

if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  missing=()
  for path in .claude/.env .claude/settings.local.json .mcp.json; do
    git -C "$PROJECT_DIR" check-ignore -q --no-index "$path" || missing+=("/$path")
  done
  if [ "${#missing[@]}" -gt 0 ] && would "add to .gitignore: ${missing[*]}"; then
    if [ -s "$PROJECT_DIR/.gitignore" ] && [ -n "$(tail -c1 "$PROJECT_DIR/.gitignore")" ]; then
      echo >>"$PROJECT_DIR/.gitignore"
    fi
    printf '%s\n' "# Claude Code per-project config (bin/link-project.sh)" "${missing[@]}" >>"$PROJECT_DIR/.gitignore"
    echo "added to .gitignore: ${missing[*]}"
  fi
fi

if [ ! -f "$CLAUDE_DIR/.env" ]; then
  if would "write $CLAUDE_DIR/.env.example (no .claude/.env yet)"; then
    cp "$SHARED_DIR/env.example" "$CLAUDE_DIR/.env.example"
    echo "no .claude/.env found — wrote $CLAUDE_DIR/.env.example; copy it to .claude/.env and fill in per-project values"
  fi
else
  # Keys env.example documents (set or commented out) that .claude/.env doesn't
  # mention at all — names only, values are never read out.
  new_keys="$(
    comm -23 \
      <(sed -nE 's/^#?[[:space:]]*([A-Z][A-Z0-9_]*)=.*/\1/p' "$SHARED_DIR/env.example" | sort -u) \
      <(sed -nE 's/^#?[[:space:]]*(export[[:space:]]+)?([A-Z][A-Z0-9_]*)=.*/\2/p' "$CLAUDE_DIR/.env" | sort -u) |
      tr '\n' ' '
  )"
  if [ -n "$new_keys" ]; then
    echo "note: env.example has keys .claude/.env doesn't mention (optional unless a skill needs them): $new_keys"
  fi
fi

if ! grep -qxF "$PROJECT_DIR" "$REGISTRY" 2>/dev/null && would "register $PROJECT_DIR in .linked-projects"; then
  echo "$PROJECT_DIR" >>"$REGISTRY"
fi
