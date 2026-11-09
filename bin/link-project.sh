#!/usr/bin/env bash
# Wire a project's .claude/ to this shared skills/agents/tools/hooks/workflows source of truth.
#
# Usage: bin/link-project.sh <path-to-project-repo>
#
# - Symlinks .claude/{skills,agents,tools,hooks,workflows} to this repo's copies.
# - Generates <project>/.mcp.json from mcp.json.template (a real file, not a
#   symlink, in case an MCP client requires that).
# - Generates <project>/.claude/settings.json from settings.json.template the
#   same way, only if one doesn't already exist — once generated, a project is
#   free to diverge from the template (different permissions, extra hooks) and
#   this script will never overwrite it silently.
# - Appends to <project>/.gitignore whichever of .claude/.env,
#   .claude/settings.local.json and .mcp.json git does not already ignore: they
#   hold per-project values and the session's ANTHROPIC_API_KEY.
# - Never touches .claude/.env, .claude/settings.local.json, or anything else
#   project-specific.
set -euo pipefail

SHARED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${1:?Usage: link-project.sh <path-to-project-repo>}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
CLAUDE_DIR="$PROJECT_DIR/.claude"

mkdir -p "$CLAUDE_DIR"

for name in skills agents tools hooks workflows; do
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
  ln -s "$SHARED_DIR/$name" "$target"
  echo "linked $target -> $SHARED_DIR/$name"
done

if [ -e "$PROJECT_DIR/.mcp.json" ]; then
  if cmp -s "$SHARED_DIR/mcp.json.template" "$PROJECT_DIR/.mcp.json"; then
    echo "existing .mcp.json matches template; left unchanged"
  else
    echo "refusing to overwrite existing .mcp.json: $PROJECT_DIR/.mcp.json" >&2
    exit 1
  fi
else
  cp "$SHARED_DIR/mcp.json.template" "$PROJECT_DIR/.mcp.json"
  echo "generated $PROJECT_DIR/.mcp.json from mcp.json.template"
fi

if [ -e "$CLAUDE_DIR/settings.json" ]; then
  if cmp -s "$SHARED_DIR/settings.json.template" "$CLAUDE_DIR/settings.json"; then
    echo "existing .claude/settings.json matches template; left unchanged"
  else
    echo "existing .claude/settings.json diverges from template; left unchanged (this is expected once a project customizes it)"
  fi
else
  cp "$SHARED_DIR/settings.json.template" "$CLAUDE_DIR/settings.json"
  echo "generated $CLAUDE_DIR/settings.json from settings.json.template"
fi

if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  missing=()
  for path in .claude/.env .claude/settings.local.json .mcp.json; do
    git -C "$PROJECT_DIR" check-ignore -q --no-index "$path" || missing+=("/$path")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    if [ -s "$PROJECT_DIR/.gitignore" ] && [ -n "$(tail -c1 "$PROJECT_DIR/.gitignore")" ]; then
      echo >>"$PROJECT_DIR/.gitignore"
    fi
    printf '%s\n' "# Claude Code per-project config (bin/link-project.sh)" "${missing[@]}" >>"$PROJECT_DIR/.gitignore"
    echo "added to .gitignore: ${missing[*]}"
  fi
fi

if [ ! -f "$CLAUDE_DIR/.env" ]; then
  cp "$SHARED_DIR/env.example" "$CLAUDE_DIR/.env.example"
  echo "no .claude/.env found — wrote $CLAUDE_DIR/.env.example; copy it to .claude/.env and fill in per-project values"
fi
