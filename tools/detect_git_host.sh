#!/usr/bin/env bash
# detect_git_host — resolve which git-hosting backend (bitbucket|github) the
# PR/comment tooling should use for this project.
#
# SCHEMA_IN
#   env GIT_HOST             optional explicit override: "bitbucket" | "github"
#   env BITBUCKET_WORKSPACE  optional fallback signal (see resolution order)
#   env GITHUB_OWNER         optional fallback signal (see resolution order)
#   (reads `git remote get-url origin` as the primary auto-detection signal
#    when GIT_HOST is unset)
#
# SCHEMA_OUT  stdout  "bitbucket" or "github" — bare word, no JSON, no trailing noise
#
# Resolution order:
#   1. $GIT_HOST if it is exactly "bitbucket" or "github" (explicit override —
#      always wins, e.g. for a self-hosted GitHub Enterprise remote that
#      doesn't contain "github.com").
#   2. `git remote get-url origin` — a URL containing "bitbucket.org" resolves
#      to bitbucket, one containing "github.com" resolves to github.
#   3. Fallback: whichever of $BITBUCKET_WORKSPACE / $GITHUB_OWNER is the only
#      one populated. Only reached when step 2 doesn't match (no origin
#      remote, or a self-hosted/enterprise host with neither string in the URL).
#
# EXIT  0=ok  1=could not determine host — caller should tell the user to set
#             GIT_HOST=bitbucket|github explicitly in .claude/.env

set -uo pipefail

case "${GIT_HOST:-}" in
  bitbucket|github) echo "$GIT_HOST"; exit 0 ;;
esac

REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
case "$REMOTE_URL" in
  *bitbucket.org*) echo "bitbucket"; exit 0 ;;
  *github.com*)    echo "github";    exit 0 ;;
esac

if [ -n "${BITBUCKET_WORKSPACE:-}" ] && [ -z "${GITHUB_OWNER:-}" ]; then
  echo "bitbucket"; exit 0
fi
if [ -n "${GITHUB_OWNER:-}" ] && [ -z "${BITBUCKET_WORKSPACE:-}" ]; then
  echo "github"; exit 0
fi

echo "ERROR: could not determine git host — set GIT_HOST=bitbucket or GIT_HOST=github in .claude/.env" >&2
exit 1
