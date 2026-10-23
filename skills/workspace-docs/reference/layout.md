# Canonical layout and rules

```
<root>/
  CLAUDE.md                     lean index (≤8 KB, aim ≤6 KB), sections §1–§8, auto-loaded every session
  docs/
    services/README.md          service index: per-family tables + "Find by question"
    services/<repo>.md          one per repo folder (file name = folder name)
    services/<repo>--<topic>.md overflow chunk (usually --review), linked by **More:** in the parent
    lookups.md                  numbered index (§1, §2 …) → docs/lookups/*.md
    lookups/<topic>.md          one table per concern, titled "# Lookups §N: <topic>"
    connections/<flow>.md       flow diagram + "Points that bite", titled "# Connections: <flow>"
    connections/ci-and-deploy.md  branch → env, deploy targets, routing
    recipes/README.md           operational how-to index (+ how to add one)
    recipes/<name>.md           one procedure each, titled "# Recipe: <name>"
    commands.md                 per-repo command cheat sheet (setup, single test, lint)
    conventions.md              patterns shared across repos
    checklist.md                cross-repo "if X changes, also check Y"
    change-map.md               optional: per-repo "if you change X, open these files" (split by family if big)
    security.md                 risks to verify (locations and names only)
    drift.md                    stale/incorrect docs and version files
    links.md                    useful-links registry (managed by `workspace_docs.py link`; pinned rows
                                are mirrored into root CLAUDE.md between pinned-links markers)
    tools/                      optional workspace-specific scripts (e.g. a schema audit); the
                                validator is the shared `.claude/tools/workspace_docs.py check`
```

## Chunk rules
- **≤ 4096 bytes** per `.md` under `docs/` (validator enforces). Split along a natural seam; never truncate.
- **Frontmatter first**, exactly these keys (others optional):
  ```
  ---
  summary: one line, what this chunk answers (shown by `grep -rh "^summary:" docs/`)
  keywords: [domain words, identifiers, synonyms people grep for]
  verified: YYYY-MM-DD
  ---
  ```
- One H1. Lookups/connections/top-level chunks have a back-reference line right after it
  (`Root \`CLAUDE.md\` §N.` or `Index: \`docs/lookups.md\`.`).
- Service chunks use labeled bullets (`- **Commands:** …`), not H2s, so `grep "\*\*Auth:\*\*"` works
  across repos. Standard labels, in order, only those that apply: **Stack**, **CI/deploy**, **Structure**,
  **Data**, **Auth**, **Contracts**, **Commands**, **Review hotspots**, **Drift**; extra labels allowed.
- Cross-references use workspace-relative paths in backticks (`docs/lookups.md` §3) so the validator
  can check them. Repo-internal paths are written relative to the repo (`src/app.ts`).
- `(I)` = inferred; `none found` = searched in the workspace and absent.
- Names only for secrets; never values.

## Root CLAUDE.md rules
- Index, not manual: each section 1–5 lines + pointers into `docs/`.
- Every repo appears in backticks (validator checks).
- Ground rules that must hold even if no chunk is read go in §1/§5 (not a monorepo, cd first,
  git fetch before review, credential files never read, stale in-repo docs).

## Mapping existing docs (align mode)
| Existing content | Canonical slot |
|---|---|
| per-repo detail | `services/<repo>.md` (+ `--review.md`) |
| repo index / "which repo owns" | `services/README.md` |
| big lookup file with many tables | `lookups.md` index + `lookups/<topic>.md` per table |
| caller→callee, producer→consumer tables | `lookups/contracts-*.md` |
| flow diagrams, pitfalls between repos | `connections/<flow>.md` |
| deploy topology, routing, branch→env | `connections/ci-and-deploy.md` |
| "where things live" per repo, grep recipes | `lookups/where-things-live.md`, `lookups/search-recipes.md` |
| "if you change X open Y" per repo | `change-map.md` (or `change-map-<family>.md`) |
| cross-repo change fan-out | `checklist.md` |
| how-tos from Confluence/Notion | `recipes/<name>.md` |
| layout, registries, shared libs, Jira keys | `conventions.md` |
