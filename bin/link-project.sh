#!/usr/bin/env bash
# Wire a project's .claude/ to this shared skills/agents/tools/hooks/workflows source of truth.
#
# Usage: bin/link-project.sh <path-to-project-repo>
#
# - Symlinks .claude/{skills,agents,tools,hooks,workflows} to this repo's copies.
# - Generates <project>/.mcp.json from mcp.json.template (a real file, not a
#   symlink, in case an MCP client requires that).
# - Never touches .claude/.env, .claude/settings.json, .claude/settings.local.json,
#   or anything else project-specific.
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

if [ ! -f "$CLAUDE_DIR/.env" ]; then
  cp "$SHARED_DIR/env.example" "$CLAUDE_DIR/.env.example"
  echo "no .claude/.env found — wrote $CLAUDE_DIR/.env.example; copy it to .claude/.env and fill in per-project values"
fi
