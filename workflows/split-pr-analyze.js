export const meta = {
  name: 'split-pr-analyze',
  description:
    'Classify a large diff into logically separable, hunk-level concerns — one agent per changed top-level package/area — for the split-pr skill',
  phases: [{ title: 'Classify' }],
};

// args = {
//   baseRef: string,
//   headRef: string,
//   groups: [{ key: string, paths: string[], hint?: string }],
//   lessons: string,         // full text of .claude/skills/split-pr/LESSONS.md
//   importGraphSummary: string, // compact text summary of import_graph.sh's output relevant to this group set
// }

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    summary: {
      type: 'string',
      description: 'One paragraph: what changed in this group and why, in plain terms',
    },
    hunks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          concern: {
            type: 'string',
            description:
              'Short, reusable label for the logically separable piece of work this hunk belongs to. Reuse the EXACT SAME string for every hunk (in this group or elsewhere) that belongs to the same concern, so hunks can be grouped later. Do not force a fixed taxonomy — invent a label that actually describes the change (e.g. "kafka transport", "library-refactor: agents adapters", "unrelated: workflowId field-order tweak").',
          },
          independent: {
            type: 'boolean',
            description:
              'true if this hunk is unrelated to the rest of the file/commit it lives in and should be pulled into its own small PR rather than riding along',
          },
          note: { type: 'string', description: 'one line: why this hunk got this label' },
        },
        required: ['file', 'concern'],
      },
    },
    cross_concern_risks: {
      type: 'array',
      description:
        'Anything found that creates an ordering constraint against another concern: an import of a symbol not yet defined outside this group, a shared file with hunks from multiple concerns, a doc that describes behavior owned by another concern, etc.',
      items: { type: 'string' },
    },
  },
  required: ['summary', 'hunks'],
};

const { baseRef, headRef, groups, lessons, importGraphSummary } = args;

function buildPrompt(g) {
  return `You are analyzing one slice of a large diff in this repo, to help split an oversized PR into smaller, reviewable, dependency-ordered PRs. This is analysis only — you will not edit, commit, or branch anything.

Diff range: ${baseRef}...${headRef}
Files/paths in your slice: ${g.paths.join(', ')}
${g.hint ? `Context hint for this slice: ${g.hint}` : ''}

Steps:
1. Run: git diff ${baseRef}...${headRef} --name-status -- ${g.paths.join(' ')}
2. For every file returned (skip pure renames/copies with an empty diff), read its actual diff: git diff ${baseRef}...${headRef} -- <file>. If a file's diff is very large, read it in slices rather than skipping it.
3. For every changed file, classify each DIFF HUNK — not necessarily the whole file — using the schema below. A file that bundles two unrelated changes (e.g. a mechanical rename plus an unrelated bugfix in the same file) must get two different "concern" labels, one per hunk, not one label for the whole file.
4. Deleted files, renamed files, and pure comment/doc-link fixes still need a concern label — deletions are frequently the other half of a rewrite happening in a different file.
5. Note every cross-package import you see in this slice (an import of a symbol from another @findfix/* package). If that imported symbol is newly added in this same diff (not already on ${baseRef}), that is an ordering constraint: this concern cannot land before the concern that adds that symbol.

Known import-graph signal already computed deterministically for this diff (cross-check your findings against it, don't contradict it without a specific reason):
${importGraphSummary || '(none computed)'}

Lessons from past runs of this analysis on this repo — apply these, do not repeat a mistake already listed here:
${lessons || '(none recorded yet)'}

Report via the required schema.`;
}

const results = await parallel(
  groups.map(
    (g) => () =>
      agent(buildPrompt(g), {
        label: `classify:${g.key}`,
        phase: 'Classify',
        schema: REPORT_SCHEMA,
      }).then((r) => ({ key: g.key, report: r })),
  ),
);

return results.filter(Boolean)
