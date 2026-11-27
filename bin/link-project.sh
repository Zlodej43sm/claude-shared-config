#!/usr/bin/env bash
# Wire a project's .claude/ to this shared skills/agents/tools/hooks/workflows source of truth.
#
# Usage: bin/link-project.sh [--refresh-mcp] [--dry-run]
#                            [--existing extend|rewrite|skip|ask] <path-to-project-repo>
#
# - Symlinks .claude/{skills,agents,tools,hooks,workflows} to this repo's copies.
# - If the project already has its own real .claude/<dir> with entries of its
#   own (often committed to its repo), asks what to do with it:
#     extend  (default) link each shared entry into it individually; same-named
#             project entries win. Those per-entry links go into
#             .git/info/exclude (local only, never committed).
#     rewrite back the directory up under this repo's .backups/ and replace it
#             with a symlink to the shared one.
#     skip    leave it as it is; link nothing into it.
#     custom  extend, but pick which shared entries to leave out and which
#             same-named project entries the shared version replaces (backed up).
#   The answer is kept in this repo's .link-choices (gitignored) so re-runs and
#   bin/sync-projects.sh don't ask again. --existing answers for every such
#   directory without asking (ask: ask again even if answered before). With no
#   terminal to ask (piped/CI), the default — extend — is used.
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
CHOICES="$SHARED_DIR/.link-choices"

usage() { echo "Usage: link-project.sh [--refresh-mcp] [--dry-run] [--existing extend|rewrite|skip|ask] <path-to-project-repo>" >&2; exit 2; }

REFRESH_MCP=0
DRY_RUN=0
EXISTING=""
PROJECT_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --refresh-mcp) REFRESH_MCP=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --existing) [ $# -ge 2 ] || usage; EXISTING="$2"; shift ;;
    --existing=*) EXISTING="${1#--existing=}" ;;
    -h|--help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [ -z "$PROJECT_DIR" ] || usage; PROJECT_DIR="$1" ;;
  esac
  shift
done
[ -n "$PROJECT_DIR" ] || usage
case "$EXISTING" in
  "" | extend | rewrite | skip | ask) ;;
  *) echo "--existing must be extend, rewrite, skip or ask (got: $EXISTING)" >&2; usage ;;
esac
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
CLAUDE_DIR="$PROJECT_DIR/.claude"
BACKUP_DIR="$SHARED_DIR/.backups/$(basename "$PROJECT_DIR")"
RUN_TS="$(date +%Y%m%d-%H%M%S)"

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

# Git-ignore a path locally (.git/info/exclude, never committed) unless the
# project already ignores it. $1 is relative to $PROJECT_DIR.
exclude_locally() {
  git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  git -C "$PROJECT_DIR" check-ignore -q --no-index "$1" && return 0
  local prefix common_dir exclude_file
  prefix="$(git -C "$PROJECT_DIR" rev-parse --show-prefix)"
  common_dir="$(cd "$PROJECT_DIR" && cd "$(git rev-parse --git-common-dir)" && pwd)"
  exclude_file="$common_dir/info/exclude"
  mkdir -p "$common_dir/info"
  if [ -s "$exclude_file" ] && [ -n "$(tail -c1 "$exclude_file")" ]; then
    echo >>"$exclude_file"
  fi
  echo "/$prefix$1" >>"$exclude_file"
}

# Lists below are space-separated strings, not arrays: bash 3.2 (macOS) treats
# an empty array as unbound under `set -u`. Entry names never contain spaces.

# in_list <word> <list>
in_list() { case " $2 " in *" $1 "*) return 0 ;; esac; return 1; }

# shared_entries <name>: entries of this repo's <name>/ that get linked.
shared_entries() {
  local src base out=""
  for src in "$SHARED_DIR/$1"/*; do
    [ -e "$src" ] || continue
    base="$(basename "$src")"
    case "$base" in __pycache__ | *.pyc) continue ;; esac
    out="$out $base"
  done
  echo "${out# }"
}

# own_entries <name>: entries of the project's .claude/<name> that aren't links
# into this repo. shared_links <name>: the ones that are.
own_entries() {
  local entry out=""
  for entry in "$CLAUDE_DIR/$1"/*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    if [ -L "$entry" ]; then
      case "$(readlink "$entry")" in "$SHARED_DIR/$1/"*) continue ;; esac
    fi
    out="$out $(basename "$entry")"
  done
  echo "${out# }"
}
has_shared_links() {
  local entry
  for entry in "$CLAUDE_DIR/$1"/*; do
    [ -L "$entry" ] || continue
    case "$(readlink "$entry")" in "$SHARED_DIR/$1/"*) return 0 ;; esac
  done
  return 1
}

# is_tracked <path relative to the project>: git tracks something under it.
is_tracked() {
  [ -n "$(git -C "$PROJECT_DIR" ls-files -- "$1" 2>/dev/null | head -n1)" ]
}

# Answers given at the prompt, kept in $CHOICES (gitignored) so a re-run or
# bin/sync-projects.sh doesn't ask again. Lines: <project>TAB<key>TAB<value>,
# key being a LINK_DIRS name (value extend|skip) or <name>/<entry> (value skip:
# a shared entry the project chose not to link).
choice_get() {
  [ -f "$CHOICES" ] || return 0
  awk -F'\t' -v p="$PROJECT_DIR" -v k="$1" '$1 == p && $2 == k { v = $3 } END { if (v != "") print v }' "$CHOICES"
}
# choice_put <key> [value]: record a choice, or forget it when no value is given.
# Replacing a directory's choice also forgets its per-entry ones.
choice_put() {
  [ "$DRY_RUN" -eq 1 ] && return 0
  local tmp
  tmp="$(mktemp)"
  if [ -f "$CHOICES" ]; then
    awk -F'\t' -v p="$PROJECT_DIR" -v k="$1" '!($1 == p && ($2 == k || index($2, k "/") == 1))' "$CHOICES" >"$tmp"
  fi
  [ -z "${2:-}" ] || printf '%s\t%s\t%s\n' "$PROJECT_DIR" "$1" "$2" >>"$tmp"
  mv "$tmp" "$CHOICES"
}

# pick <answer> <list>: the list entries the answer names, by name or 1-based number.
pick() {
  local tok e i found out=""
  set -f
  for tok in ${1//,/ }; do
    i=0 found=""
    for e in $2; do
      i=$((i + 1))
      if [ "$tok" = "$e" ] || [ "$tok" = "$i" ]; then found="$e"; break; fi
    done
    if [ -z "$found" ]; then
      echo "  ignored: $tok (not in the list)" >&2
    elif ! in_list "$found" "$out"; then
      out="$out $found"
    fi
  done
  set +f
  echo "${out# }"
}

# ask_mode <name> <own entries>: the interactive prompt. Sets MODE (and, for
# custom, REPLACE plus the recorded per-entry skips).
ask_mode() {
  local name="$1" own="$2" shared same="" e i ans tracked=0
  shared="$(shared_entries "$name")"
  for e in $own; do in_list "$e" "$shared" && same="$same $e"; done
  same="${same# }"
  is_tracked ".claude/$name" && tracked=1
  echo
  echo "The project already has its own .claude/$name: $(echo "$own" | wc -w | tr -d ' ') entr(ies) — $own"
  [ -z "$same" ] || echo "  same name as a shared one: $same"
  [ "$tracked" -eq 0 ] || echo "  committed to the project's git repo"
  echo "What should happen with the shared $name?"
  echo "  1) extend   keep the project's entries and link the shared ones next to them;"
  echo "              the project's same-named entries win  (default)"
  echo "  2) rewrite  replace .claude/$name with a link to the shared folder"
  echo "              (the project's copy is backed up to $BACKUP_DIR/ first)"
  [ "$tracked" -eq 0 ] || echo "              committed, so git will then show its files as deleted"
  echo "  3) skip     leave .claude/$name as it is and link nothing into it"
  echo "  4) custom   extend, but choose which shared entries to leave out and"
  echo "              which same-named project entries the shared version replaces"
  while :; do
    printf 'Choice [1-4, Enter = extend]: '
    read -r ans || ans=""
    case "$ans" in
      "" | 1 | e | extend) MODE=extend ;;
      2 | r | rewrite) MODE=rewrite ;;
      3 | s | skip) MODE=skip ;;
      4 | c | custom) MODE=custom ;;
      *) echo "please answer 1, 2, 3 or 4"; continue ;;
    esac
    break
  done
  if [ "$MODE" = rewrite ]; then
    printf 'Replace %s with the shared folder (backed up first)? [y/N]: ' "$CLAUDE_DIR/$name"
    read -r ans || ans=""
    case "$ans" in
      y | Y | yes) ;;
      *) echo "not rewriting; using extend"; MODE=extend ;;
    esac
  fi
  if [ "$MODE" = custom ]; then
    echo "Shared $name:"
    i=0
    for e in $shared; do i=$((i + 1)); printf '  %2d) %s\n' "$i" "$e"; done
    printf 'Leave out which? (numbers or names, space-separated; Enter = link all): '
    read -r ans || ans=""
    local skip
    skip="$(pick "$ans" "$shared")"
    choice_put "$name" extend
    for e in $skip; do choice_put "$name/$e" skip; done
    local replaceable=""
    for e in $same; do in_list "$e" "$skip" || replaceable="$replaceable $e"; done
    replaceable="${replaceable# }"
    if [ -n "$replaceable" ]; then
      echo "In both the project and here (the project's version wins unless replaced):"
      i=0
      for e in $replaceable; do i=$((i + 1)); printf '  %2d) %s\n' "$i" "$e"; done
      printf "Replace which with the shared version? (project's copy backed up first; Enter = none): "
      read -r ans || ans=""
      REPLACE="$(pick "$ans" "$replaceable")"
    fi
    MODE=extend
    return
  fi
  [ "$MODE" = rewrite ] || choice_put "$name" "$MODE"
}

# resolve_mode <name>: decide what to do with the project's own real
# .claude/<name> — sets MODE to extend, rewrite or skip (REPLACE: same-named
# project entries to swap for the shared version this run).
resolve_mode() {
  local name="$1" own recorded
  MODE="" REPLACE=""
  own="$(own_entries "$name")"
  recorded="$(choice_get "$name")"
  if [ -n "$EXISTING" ] && [ "$EXISTING" != ask ]; then
    MODE="$EXISTING"
    [ "$MODE" = rewrite ] || choice_put "$name" "$MODE"
  elif [ "$EXISTING" != ask ] && [ -n "$recorded" ]; then
    MODE="$recorded"
  elif [ "$EXISTING" != ask ] && { [ -z "$own" ] || has_shared_links "$name"; }; then
    # Nothing of the project's own to decide about, or extended by an earlier
    # run (before answers were recorded).
    MODE=extend
  elif [ "$DRY_RUN" -eq 1 ]; then
    echo "would ask what to do with the project's own $CLAUDE_DIR/$name (extend, rewrite, skip or custom); previewing the default, extend:"
    MODE=extend
  elif [ ! -t 0 ]; then
    echo "project has its own $CLAUDE_DIR/$name and there's no terminal to ask: using the default, extend (to choose: bin/link-project.sh --existing ask $PROJECT_DIR)"
    MODE=extend
  else
    ask_mode "$name" "$own"
  fi
}

# backup_entry <path inside .claude/>: copy it to $BACKUP_DIR/claude.<ts>/, print where.
backup_entry() {
  local dest="$BACKUP_DIR/claude.$RUN_TS/${1#"$CLAUDE_DIR"/}"
  mkdir -p "$(dirname "$dest")"
  cp -Rp "$1" "$dest"
  echo "$dest"
}

# rewrite_dir <name>: replace the project's own .claude/<name> with a link to
# the shared one, keeping a backup. Forgets any recorded answer, so if a
# `git pull` brings the committed folder back, the next run asks again.
rewrite_dir() {
  local name="$1" target="$CLAUDE_DIR/$1" backup tracked=0
  is_tracked ".claude/$name" && tracked=1
  if would "replace $target with a link to $SHARED_DIR/$name (project's copy backed up to $BACKUP_DIR/claude.$RUN_TS/$name)"; then
    backup="$(backup_entry "$target")"
    rm -rf "$target"
    ln -s "$SHARED_DIR/$name" "$target"
    choice_put "$name"
    echo "rewrote $target -> $SHARED_DIR/$name (project's copy: $backup)"
    if [ "$tracked" -eq 1 ]; then
      echo "  note: .claude/$name is committed to the project's repo — git now shows its files as deleted, and a pull that changes them brings the folder back (the next run then asks again)"
    fi
  fi
}

# The project keeps its own .claude/<name> as a real directory (often committed
# to its repo, so a `git pull` would put it back over a symlink anyway): link
# each shared entry into it individually instead. Entries the project already
# has — its own skill/agent/hook of the same name — win and are left alone,
# unless listed in REPLACE (backed up, then swapped for the shared link).
# Shared entries recorded as skipped are not linked (and unlinked if they were).
merge_dir() {
  local name="$1" dir="$CLAUDE_DIR/$1" entry src base dest
  local added="" own="" stale="" skipped="" replaced="" n_added=0
  # Drop links to shared entries that were since removed or renamed.
  for entry in "$dir"/*; do
    [ -L "$entry" ] || continue
    case "$(readlink "$entry")" in "$SHARED_DIR/$name/"*) ;; *) continue ;; esac
    [ -e "$entry" ] && continue
    if would "remove stale link $entry"; then rm "$entry"; fi
    stale="$stale $(basename "$entry")"
  done
  for src in "$SHARED_DIR/$name"/*; do
    [ -e "$src" ] || continue
    base="$(basename "$src")"
    case "$base" in __pycache__ | *.pyc) continue ;; esac
    dest="$dir/$base"
    if [ "$(choice_get "$name/$base")" = skip ]; then
      if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ] && would "remove link $dest (left out by choice)"; then
        rm "$dest"
      fi
      skipped="$skipped $base"
      continue
    fi
    if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
      continue
    elif [ -e "$dest" ] || [ -L "$dest" ]; then
      if ! in_list "$base" "$REPLACE"; then
        own="$own $base"
        continue
      fi
      if would "replace project's own $dest with a link to $src (backed up first)"; then
        replaced="$replaced $base -> $(backup_entry "$dest")"
        rm -rf "$dest"
      fi
    fi
    if would "link $dest -> $src"; then
      ln -s "$src" "$dest"
      exclude_locally ".claude/$name/$base"
    fi
    added="$added $base"
    n_added=$((n_added + 1))
  done
  local verb="merged"
  [ "$DRY_RUN" -eq 1 ] && verb="would merge"
  echo "$verb into project's own directory $dir: $n_added new link(s)${added:+ (${added# })}${stale:+; removed stale:$stale}"
  if [ -n "$own" ]; then
    echo "  project's own version kept (shadows the shared one):$own"
  fi
  if [ -n "$replaced" ]; then
    echo "  replaced with the shared version (project's copy backed up):$replaced"
  fi
  if [ -n "$skipped" ]; then
    echo "  left out by choice (change with --existing ask):$skipped"
  fi
}

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
  elif [ -d "$target" ]; then
    resolve_mode "$name"
    case "$MODE" in
      skip) echo "left the project's own $target as is (chosen: skip; change with --existing ask)" ;;
      rewrite) rewrite_dir "$name" ;;
      *) merge_dir "$name" ;;
    esac
    continue
  elif [ -e "$target" ]; then
    echo "refusing to overwrite existing non-directory: $target (remove it manually first)" >&2
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
