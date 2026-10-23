# Templates

Placeholders are `<like-this>`. Delete lines that don't apply; keep the order.

## docs/services/<repo>.md
```markdown
---
summary: <one line: what the repo is>
keywords: [<domain words>, <identifiers>, <synonyms>]
verified: <YYYY-MM-DD>
---
# <repo>

**What it is:** <one or two sentences>. (family: <family>)
**Top review risks:** <3–5 short risks, `;`-separated>
**Related:** `docs/services/<other>.md`, …
**Code:** `<absolute root>/<repo>/` · **Index:** `docs/services/README.md` · **Workspace map:** root `CLAUDE.md` §2-§3 · **Lookups:** `docs/lookups.md`[ · **More:** `docs/services/<repo>--review.md`]

---

- **Stack:** <language, framework, DB, package manager, runtime version>
- **CI/deploy:** <branch → env, per pipeline file; what is manual>
- **Structure:** <entry point → layers; roles/processes; load-bearing order>
- **Data:** <stores; who owns the schema; migrations and when they run>
- **Auth:** <inbound auth; what never rejects; header/secret NAMES>
- **Contracts:** <what it publishes/consumes; schema home>
- **Commands:** <setup>; <test>; single `<single-test command>`; <lint>
- **Review hotspots:** <what reviewers must check; sub-bullets allowed>
- **Drift:** <where its own docs are wrong>
```
Overflow `docs/services/<repo>--review.md`: same frontmatter, H1 `# <repo> — review`, then
`**Parent:** \`docs/services/<repo>.md\` · **Index:** \`docs/services/README.md\``, `---`, the moved bullets.

## docs/services/README.md
```markdown
---
summary: Service index — top risks per repo by family, plus "find by question"
keywords: [service index, which repo, owner, find by question]
verified: <date>
---
# Service index

One file per repo at `docs/services/<repo>.md` …(one line on the bullet layout).

## <Family>
| Service | Top review risks |
|---|---|
| [`<repo>`](<repo>.md) | <short risks> |

## Find by question
| If the question is about... | Start with |
|---|---|
| <capability words> | `<repo>` |
```

## docs/lookups.md and docs/lookups/<topic>.md
```markdown
# Lookups (index)
<one paragraph: scope, `(I)`, `none found`, names-only>
| § | Topic | File |
|---|---|---|
| 1 | <topic> | `docs/lookups/<topic>.md` |
```
```markdown
# Lookups §<N>: <topic>

Index: `docs/lookups.md`.

| <Key> | Producer / Owner | Consumer / Also touched by | Notes |
|---|---|---|---|
```

## docs/connections/<flow>.md
```markdown
# Connections: <flow>

Root `CLAUDE.md` §3.<n>. Tables: `docs/lookups.md` §<n>.

~~~
<caller> ─<mechanism>─► <callee>
~~~

## Reality check            (planned vs actually wired; omit if all wired)
## Points that bite
- **<short name>:** <what goes wrong and where>
```

## docs/recipes/<name>.md
```markdown
# Recipe: <name>

Index: `docs/recipes/README.md`. Source: <Confluence/Notion page title + link>, read <date>.

1. <step, with exact command>
## Gotchas
```

## Top-level chunks (commands, conventions, checklist, change-map, security, drift)
H1, then `Root \`CLAUDE.md\` §<n>.`, then bullets/tables. `commands.md` is one table:
`| Repo | Setup | Tests (single) | Lint / gate |`.

## Root CLAUDE.md skeleton
```markdown
# CLAUDE.md

Workspace index for `<root>`. Detail lives in `docs/` as chunks of ≤4 KB with frontmatter: find the chunk here, Read only that one.

## Quick navigation
| I need to... | Open |
|---|---|
| Know which repo owns a capability | §2; `docs/services/README.md` |
| One repo's detail | `docs/services/<repo>.md` |
| Run, test, lint | `docs/commands.md` |
| Flows between repos | §3; `docs/connections/*.md` |
| Topic / store / secret name / contract / version | `docs/lookups.md` |
| Change spanning repos | `docs/checklist.md` |
| Conventions · recipes | `docs/conventions.md` · `docs/recipes/README.md` |
| Security · stale docs | `docs/security.md` · `docs/drift.md` |
| Useful links (dashboards, team pages) | `docs/links.md` |

**Convention:** read `docs/services/<repo>.md` first, then the repo's own agent docs; verified <date>.

## 1. What this directory is      (not a monorepo; cd first; git fetch; non-repo dirs; credential files)
## 2. Workspace map               (table: family → repos in backticks with 1–3 word role)
## 3. How the pieces connect      (3.n one bullet per connections file)
## 4. Finding things              (grep over docs/, summary/keywords one-liners, code grep recipes)
## 5. Working rules               (pointers to commands/conventions/checklist; never-do list; run `workspace_docs.py check`; keep the pinned-links block)
## 6. Known risks and stale docs  (top 3–5 risks; pointers)
## 7. Team docs → recipes         (where team docs live; recipe index)
## 8. Tooling note                (shell wrappers, MCP tools, ticket key prefixes)
```
