#!/usr/bin/env bash
# Wire a project's .claude/ to this shared skills/agents/tools/hooks/workflows source of truth.
#
# Usage: bin/link-project.sh <path-to-project-repo>
#
# - Symlinks .claude/{skills,agents,tools,hooks,workflows} to this repo's copies.
# - Generates <project>/.mcp.json (a real file, not a symlink, in case an MCP
#   client requires that) from mcp.json.template plus the mcp.d/ fragments that
#   match the project: GitHub MCP when the git host is GitHub, Notion MCP when
#   NOTION_TOKEN is set in .claude/.env. Re-run after changing either; a file
#   this script generated is regenerated, a hand-edited one is never touched.
# - Generates <project>/.claude/settings.json from settings.json.template the
#   same way, only if one doesn't already exist — once generated, a project is
#   free to diverge from the template (different permissions, extra hooks) and
#   this script will never overwrite it silently.
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

# .mcp.json = mcp.json.template + the servers this project's git host / env call
# for (see bin/render-mcp.py). The hash of the last file we wrote is stamped so a
# later re-run (after GIT_HOST or NOTION_TOKEN changes) can regenerate it, while
# a hand-edited .mcp.json is still never overwritten.
MCP_STAMP="$CLAUDE_DIR/.mcp.generated.sha256"
RENDERED="$(mktemp)"
trap 'rm -f "$RENDERED"' EXIT
python3 "$SHARED_DIR/bin/render-mcp.py" "$PROJECT_DIR" > "$RENDERED"
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }

if [ -e "$PROJECT_DIR/.mcp.json" ]; then
  if cmp -s "$RENDERED" "$PROJECT_DIR/.mcp.json"; then
    sha "$RENDERED" > "$MCP_STAMP"
    echo "existing .mcp.json matches what this project needs; left unchanged"
  elif cmp -s "$SHARED_DIR/mcp.json.template" "$PROJECT_DIR/.mcp.json" \
      || { [ -f "$MCP_STAMP" ] && [ "$(cat "$MCP_STAMP")" = "$(sha "$PROJECT_DIR/.mcp.json")" ]; }; then
    cp "$RENDERED" "$PROJECT_DIR/.mcp.json"
    sha "$RENDERED" > "$MCP_STAMP"
    echo "regenerated $PROJECT_DIR/.mcp.json (it was an untouched generated file; MCP servers updated for this project)"
  else
    echo "refusing to overwrite hand-edited .mcp.json: $PROJECT_DIR/.mcp.json" >&2
    echo "  merge in the servers from: python3 $SHARED_DIR/bin/render-mcp.py $PROJECT_DIR" >&2
    exit 1
  fi
else
  cp "$RENDERED" "$PROJECT_DIR/.mcp.json"
  sha "$RENDERED" > "$MCP_STAMP"
  echo "generated $PROJECT_DIR/.mcp.json"
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

if [ ! -f "$CLAUDE_DIR/.env" ]; then
  cp "$SHARED_DIR/env.example" "$CLAUDE_DIR/.env.example"
  echo "no .claude/.env found — wrote $CLAUDE_DIR/.env.example; copy it to .claude/.env and fill in per-project values"
fi
