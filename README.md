# claude-shared-config

Single source of truth for Claude Code `skills/`, `agents/`, `tools/`, and `hooks/`,
shared across all local levelAccess projects instead of hand-copying them per repo.

## What's here

- `skills/`, `agents/`, `tools/`, `hooks/` — the actual shared content. None of it
  hardcodes a repo path; everything resolves the working project via
  `$CLAUDE_PROJECT_DIR` (set by Claude Code) or `git rev-parse --show-toplevel`.
- `mcp.json.template` — generated (copied, not symlinked) into each project's root
  `.mcp.json`. All values are `${VAR}` references resolved from that project's own
  `.claude/.env` — the template itself never changes per project.
- `env.example` — template for a project's `.claude/.env`. Secret fields use
  `op://` (1Password) references; see the file header for setup.
- `bin/link-project.sh <path>` — wires a project to this repo (symlinks +
  generates `.mcp.json`). Safe to re-run; refuses to clobber a non-symlink.

## What's NOT here (stays per-project, never write project values back into this repo)

`.claude/.env`, `.claude/settings.json`, `.claude/settings.local.json`,
`.claude/plans/`, `.claude/reviews/`, `.claude/worktrees/`, and any other
session/runtime state. Project `.gitignore` must exclude `.claude/.env`,
`.claude/settings.local.json`, and `.mcp.json`.

## Adding a project

```bash
~/dev/levelAccess/claude-shared-config/bin/link-project.sh ~/dev/levelAccess/<project>
```

Then fill in `.claude/.env` from the generated `.claude/.env.example`.
