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
    files_list=$(
      {
        # --diff-filter=d excludes Deleted entries so prettier doesn't error on
        # files that exist in the index but not on disk.
        git diff --name-only --diff-filter=d HEAD 2>/dev/null
        git ls-files --others --exclude-standard 2>/dev/null
      } | awk 'NF' | sort -u
    )
    if [ -z "$files_list" ]; then
      exit 0
    fi
    # --ignore-unknown skips files prettier has no parser for; .prettierignore
    # entries are honored automatically. xargs splits the newline-delimited list
    # so prettier sees one argument per file (paths with spaces would need -0,
    # but this repo has none).
    # Filter out symbolic links — prettier rejects them with an error.
    files_list=$(printf '%s\n' "$files_list" | while IFS= read -r f; do [ ! -L "$f" ] && echo "$f"; done)
    if [ -z "$files_list" ]; then
      exit 0
    fi
    if ! printf '%s\n' "$files_list" | xargs "$PRETTIER" --check --ignore-unknown >/tmp/prettier-check.out 2>&1; then
      echo "Prettier found unformatted files. Run \`yarn prettier --write\` on:" >&2
      grep -E '^\[warn\] ' /tmp/prettier-check.out | grep -vE 'Code style issues' >&2 || cat /tmp/prettier-check.out >&2
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
