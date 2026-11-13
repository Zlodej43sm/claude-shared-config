# Doc self-check before commit and PR

Generic. Run it on every changed doc before each commit, before opening or updating a PR, and again after fixing review comments, because a fix often copies a rule to a second place or leaves a comment that contradicts it. The checks are ordered by how often reviewers raise them. Each line is a question; a "no" is something to fix now. The rule behind each check is in `../SKILL.md`.

## 1. Is it true on the default branch? (§D)
- Every behaviour, name, default and status code is on the owning repo's default branch, not only on an open PR, a feature branch, a plan doc or a ticket. That includes a sibling service you "know" is about to change.
- Every "X does Y" points to code you opened. If you can't find it, delete it or ask.
- Arrow labels and payloads in the diagrams next to the change match the code, even when the diagram is not in the diff.
- Quick check per claim: `git -C ../<repo> fetch -q && git -C ../<repo> grep -n '<name>' origin/<default-branch>`.

## 2. Is it end state only? (§A)
- No "today", "currently", "previously", "legacy", "old behaviour", "will", "after this change", "phase N", rollout or rollback order, migration notes.
- No ticket keys in headings or text. Headings name the concept.
- A live config switch is named once and links to the ADR or runbook that owns its rollout.
- Quick check: `grep -nE '\b(today|currently|previously|legacy|we will|after this change|phase [0-9]|roll ?out|roll ?back)\b|\b[A-Z][A-Z0-9]+-[0-9]+\b' <changed docs>`.

## 3. Does each rule have one home? (§H)
- Each rule this change adds or edits is stated in one section. Every other doc links to that section instead of restating it.
- Search for the rule's key words across `docs/`, the glossary and READMEs. Any second copy is reduced to a link.
- Inside one doc, a rule that applies to several modes or cases is stated once.

## 4. Is the level of detail right? (§H)
- The architecture or contract doc keeps the rule (what happens, who sees it) and drops TTL values, log event names, internal keys, storage paths and function names.
- Glossary entries are one short sentence and stay within the project's length cap.

## 5. Does the change agree with itself? (§I)
- Code comments, test names and comments, e2e assertions, config defaults and READMEs say what the docs say.
- For each actor, state or failure the change adds, `grep` the whole doc and its diagram sources: every rule, table, foreign key and list of exceptions that assumes the old set includes it or says why not.
- A config default this change turns on matches the rollout order the docs state. A dependency on an unmerged change in another repo is written as a merge order in the PR description or README.
- A test that proves a documented rule fails when the rule breaks. Check for a state that is already terminal, a wait that returns at once, or outcomes that look the same.

## 6. Shown, not narrated? (§B)
- Flows, ownership and state machines are diagrams. Data models, endpoints and config are tables.

## 7. Plain and short? (§C)
- Short sentences, glossary terms, no filler, no vague verbs ("handles", "manages"). Every paragraph you added is the shortest version that still says it.

## 8. Reader questions, failure modes, fan-out (§E–§G)
- Bootstrap, authorization, interface, handoff and lifecycle are answered for every new actor, credential or resource.
- Ambiguous failure, crash between steps, retries, duplicates and concurrency are covered for design docs.
- Every other canonical doc this change makes stale is updated or named as a follow-up.
