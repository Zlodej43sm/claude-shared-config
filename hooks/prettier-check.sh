#!/usr/bin/env bash
# Prettier hook used by both PostToolUse (auto-format a single file) and Stop
# (sweep all changed files). Surfaces errors via exit code 2 + stderr so Claude
# can react instead of silently swallowing failures.

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$PROJECT_DIR" ]; then
  echo "prettier-check: CLAUDE_PROJECT_DIR unset and not inside a git repo" >&2
  exit 1
fi

PRETTIER="$PROJECT_DIR/node_modules/.bin/prettier"
if [ ! -x "$PRETTIER" ]; then
  # Pre-install state — nothing to do, don't block the user.
  exit 0
fi

mode="${1:-}"
shift || true

case "$mode" in
  --changed)
    cd "$PROJECT_DIR" || exit 1
    # Private temp files: a fixed /tmp path would be shared by concurrent sessions
    # and could be pre-created as a symlink by another local user.
    out=$(mktemp "${TMPDIR:-/tmp}/prettier-check.XXXXXX") || exit 1
    files=$(mktemp "${TMPDIR:-/tmp}/prettier-files.XXXXXX") || { rm -f "$out"; exit 1; }
    trap 'rm -f "$out" "$files"' EXIT
    # NUL-delimited end to end so any file name (spaces, newlines, leading -)
    # reaches prettier as exactly one argument. --diff-filter=d excludes Deleted
    # entries so prettier doesn't error on files in the index but not on disk.
    {
      git diff -z --name-only --diff-filter=d HEAD 2>/dev/null
      git ls-files -z --others --exclude-standard 2>/dev/null
    } | sort -zu | while IFS= read -r -d '' f; do
      # Filter out symbolic links — prettier rejects them with an error.
      if [ -n "$f" ] && [ ! -L "$f" ]; then printf '%s\0' "$f"; fi
    done >"$files"
    if [ ! -s "$files" ]; then
      exit 0
    fi
    # --ignore-unknown skips files prettier has no parser for; .prettierignore
    # entries are honored automatically.
    if ! xargs -0 "$PRETTIER" --check --ignore-unknown -- <"$files" >"$out" 2>&1; then
      echo "Prettier found unformatted files. Run prettier --write on:" >&2
      grep -E '^\[warn\] ' "$out" | grep -vE 'Code style issues' >&2 || cat "$out" >&2
      exit 2
    fi
    ;;
  "")
    echo "prettier-check: missing file path argument" >&2
    exit 1
    ;;
  *)
    file="$mode"
    if [ ! -f "$file" ]; then
      # File may have been deleted or renamed by the same tool call.
      exit 0
    fi
    cd "$PROJECT_DIR" || exit 1
    if ! out="$("$PRETTIER" --write --ignore-unknown "$file" 2>&1)"; then
      echo "prettier-check: failed to format $file" >&2
      echo "$out" >&2
      exit 2
    fi
    ;;
esac

exit 0
