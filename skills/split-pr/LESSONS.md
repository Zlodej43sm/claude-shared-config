# split-pr — shared lessons

This is a curated, read-only reference for all projects that link this shared
configuration. It must contain only portable guidance: no project names,
ticket or PR identifiers, repository paths, customer data, incident narratives,
or environment-specific commands. Record project-specific lessons only in
`.claude/reviews/split-pr-lessons.local.md`.

- Classify at the diff-hunk level when a file contains unrelated changes.
- Establish ordering from verified imports and build results, not commit titles
  or directory names.
- Treat deleted public exports as potential reverse-dependency breaks; build
  the isolated change before declaring it independently landable.
- Keep dependency-manifest changes and their generated lockfile updates in the
  same change set. Generate lockfiles with the target project's documented
  package-manager command.
- Verify each proposed branch using the target project's current CI definition
  and documented local commands. Clearly report any gate that cannot run
  locally.
- Do not infer cross-file dependencies from similar terminology. Cite a real
  import, symbol, generated artifact, or verified test/build result.
