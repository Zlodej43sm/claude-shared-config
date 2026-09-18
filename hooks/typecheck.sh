#!/usr/bin/env bash
# Typecheck hook used by Stop to sweep the whole monorepo before Claude stops.
# Surfaces tsc errors via exit code 2 + stderr so Claude reacts instead of
# leaving type errors for CI to catch (mirrors prettier-check.sh). Turbo's cache
# makes this a near-instant no-op on turns that didn't touch typed sources.

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$PROJECT_DIR" ]; then
  echo "typecheck: CLAUDE_PROJECT_DIR unset and not inside a git repo" >&2
  exit 1
fi

TURBO="$PROJECT_DIR/node_modules/.bin/turbo"
if [ ! -x "$TURBO" ]; then
  # Pre-install state — nothing to typecheck, don't block the user.
  exit 0
fi

cd "$PROJECT_DIR" || exit 1

# `turbo run typecheck` == root `pnpm typecheck`. Invoke the binary directly so
# the hook doesn't depend on corepack/pnpm being on the hook shell's PATH.
if ! out="$("$TURBO" run typecheck 2>&1)"; then
  echo "Typecheck failed — fix before stopping:" >&2
  echo "$out" >&2
  exit 2
fi

exit 0
