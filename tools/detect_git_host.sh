#!/usr/bin/env bash
# detect_git_host — resolve which git-hosting backend (bitbucket|github|azure)
# the PR/comment tooling should use for this project.
#
# SCHEMA_IN
#   env GIT_HOST             optional explicit override: "bitbucket" | "github" | "azure"
#   env BITBUCKET_WORKSPACE  optional fallback signal (see resolution order)
#   env GITHUB_OWNER         optional fallback signal (see resolution order)
#   env AZURE_DEVOPS_ORG / AZURE_DEVOPS_URL  optional fallback signal (see resolution order)
#   (reads `git remote get-url origin` as the primary auto-detection signal
#    when GIT_HOST is unset)
#
# SCHEMA_OUT  stdout  "bitbucket", "github" or "azure" — bare word, no JSON, no trailing noise
#
# Resolution order:
#   1. $GIT_HOST if it is exactly "bitbucket", "github" or "azure" (explicit
#      override — always wins, e.g. for a self-hosted GitHub Enterprise remote
#      that doesn't contain "github.com").
#   2. `git remote get-url origin` — a URL containing "bitbucket.org" resolves
#      to bitbucket, "github.com" to github, "dev.azure.com" or
#      ".visualstudio.com" to azure (Azure DevOps).
#   3. Fallback: whichever of $BITBUCKET_WORKSPACE / $GITHUB_OWNER is the only
#      one populated; else azure when $AZURE_DEVOPS_ORG or $AZURE_DEVOPS_URL is.
#      Only reached when step 2 doesn't match (no origin remote, e.g. a workspace
#      root that is not a repo, or a self-hosted host with none of the strings in
#      the URL). A root with GitHub and Azure DevOps repos stays github here; the
#      PR skills take the host from a PR URL.
#
# EXIT  0=ok  1=could not determine host — caller should tell the user to set
#             GIT_HOST=bitbucket|github|azure explicitly in .claude/.env

set -uo pipefail

case "${GIT_HOST:-}" in
  bitbucket|github|azure) echo "$GIT_HOST"; exit 0 ;;
esac

REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
case "$REMOTE_URL" in
  *bitbucket.org*)                     echo "bitbucket"; exit 0 ;;
  *github.com*)                        echo "github";    exit 0 ;;
  *dev.azure.com*|*.visualstudio.com*) echo "azure";     exit 0 ;;
esac

count=0
only=""
if [ -n "${BITBUCKET_WORKSPACE:-}" ]; then count=$((count + 1)); only="bitbucket"; fi
if [ -n "${GITHUB_OWNER:-}" ];        then count=$((count + 1)); only="github";    fi
if [ "$count" -eq 1 ]; then
  echo "$only"; exit 0
fi
if [ "$count" -eq 0 ] && [ -n "${AZURE_DEVOPS_ORG:-}${AZURE_DEVOPS_URL:-}" ]; then
  echo "azure"; exit 0
fi

echo "ERROR: could not determine git host — set GIT_HOST=bitbucket, GIT_HOST=github or GIT_HOST=azure in .claude/.env" >&2
exit 1
