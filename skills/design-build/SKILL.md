---
name: design-build
description: Builds UI from a design-spec directory, one block at a time, and proves each block matches its reference by pixel diff. Detects the project's UI stack, reuses its tokens and components, and aligns blocks that already exist in the code instead of rebuilding them. Plans first and waits for approval, then for each block - writes the code, renders it in a headless browser (Playwright MCP) at every spec viewport, diffs it against reference.png, and fixes the mismatches until the diff passes. Use after /design-spec, or when asked to "build / implement / match this design" for a spec that exists. Usage - /design-build <spec-dir> [--block=<name>]... [--preview=<url>] [--threshold=<percent>] [--max-rounds=<n>]
---

# design-build — per-block specs → pixel-matched code

Turns a spec directory written by `design-spec` into code in the current project, one
block at a time. A block is done when its render matches `reference.png` at every
viewport in the spec. The spec format is defined in
[../design-spec/references/spec-format.md](../design-spec/references/spec-format.md):
read it first.

**No code before the plan is approved** (Step 3).

## Input

```
/design-build <spec-dir> [--block=<name>]... [--preview=<url>] [--threshold=<percent>] [--max-rounds=<n>]
```

- `<spec-dir>`: a directory with `design.md`, e.g. `.claude/design/home-page`.
- `--block`: build only these blocks (name as in design.md). Default: every block whose
  status isn't `verified` or `accepted`, in page order.
- `--preview`: the URL where the built blocks render (a page of the running app, a
  Storybook story). Default: found in Step 2.
- `--threshold`: accepted mismatch percentage; default the spec's `diff_threshold`.
- `--max-rounds`: fix-and-diff rounds per block and viewport before stopping; default 5.

`T` below is `python3 -I .claude/tools/design_png.py`.

## Step 0 — Load

- Read `design.md`, `tokens.json` and the `spec.md` of each selected block. Look at each
  `reference.png`.
- Check the Playwright MCP tools (ToolSearch `browser_navigate`). Without them the
  blocks can be built but not verified. Say so, offer the setup from `design-spec`
  Step 2a, and continue only if the user accepts building without verification. Blocks
  built that way end as `built`, never `verified`.
- A block with `reference: missing` is compared by eye (Read both images) instead of by
  `T diff`. Say so in the report.

## Step 1 — Understand the project

- **Stack.** Detect it as `frontend-review` Step 0 does
  ([../frontend-review/SKILL.md](../frontend-review/SKILL.md)): framework, styling
  (CSS modules, Tailwind, styled-components, SCSS), design-system package, Storybook,
  test tools. Read the matching framework reference there for conventions.
- **Project rules.** Follow the root `CLAUDE.md` / `AGENTS.md` to the front-end
  conventions, lint config and design-system docs. Note the type-check, lint, test and
  build commands from `CLAUDE.md`, the `Makefile` or `package.json` scripts.
- **Existing tokens.** Find where the project keeps its design values: theme files, CSS
  custom properties, the Tailwind config, the design-system package. Map each entry of
  `tokens.json`:

  | Spec token | Project token | Match |
  |---|---|---|
  | color.primary `#e03a2a` | `--tf-color-brand` | same value |
  | font.heading-xl | `typography.h1` | line height differs: 56 vs 52 |
  | radius.button `8` | — | new |

  Use the project's token wherever the value is the same, whatever its name. A value
  with no project token is listed as **new**.
- **Existing components.** The Components table in `design.md`, the design-system
  package and the project's component folders. A button, link, icon or card the project
  already has is reused, not rebuilt.
- **Existing blocks.** For each block, search the code for an implementation: component
  names (`Header`, `SiteFooter`), landmarks, and distinctive text from the spec (grep a
  heading or a link label). A block that exists is **aligned**: verified first, then only
  its deviations are fixed. A block that doesn't exist is **built** new.

## Step 2 — Choose the preview

The block must render in a browser at the spec's viewport width, the way it renders in
the product. In order:

1. `--preview` given → use it.
2. The block already renders on a page of the app (align mode, or the user names the
   page) → that page, with the app's dev server.
3. The project uses Storybook → one story per block, following the project's story
   conventions, with full-width layout (`layout: 'fullscreen'`) and no decorator padding.
4. A plain HTML/CSS project → the page the block belongs to, opened as `file://`.

Start a dev server or Storybook with the project's own script, in the background. If more
than one script fits, ask which. Never add a route, page or flag to the product only for
previews.

## Step 3 — Plan and ask

Show the plan and stop:

```
Design build: .claude/design/home-page  (react + css modules, preview: storybook)

| # | Block | Mode | Files | Reuses | New tokens |
|---|---|---|---|---|---|
| 1 | header | align | src/components/Header/Header.tsx | Logo, NavLink | — |
| 2 | hero | build | src/components/Hero/Hero.tsx, Hero.module.css, Hero.stories.tsx | Button | radius.button 8 |

Token differences to decide: font.heading-xl line height 56 (spec) vs 52 (typography.h1).
Fonts: Inter 400/600/700 — already loaded by the app.
Assets to add: assets/hero-photo.png → public/images/hero-photo.png

Reply **build** to start, **modify: <change>** to change the plan, or **cancel**.
```

- New tokens, a token value that differs from the project's, a new font or a new
  dependency each need an explicit yes. They change the design system for every page.
- Third-party assets (design.md Assets with an origin the user doesn't own) are listed
  and need an explicit yes before they're copied into the project.

## Step 4 — Build and verify, block by block

For each block, in page order, when the plan is approved:

1. **Write the code.** Follow the code rules of `implement` Step 4, item 1
   ([../implement/SKILL.md](../implement/SKILL.md)) and the project's conventions:
   - Semantic elements from the spec's `el`. Text and attributes from `text` / `attrs`.
     Accessible names for icon-only links and buttons.
   - Layout as the spec says: `row`/`column` → flexbox, `grid` → CSS grid, `stack` →
     positioned children. Sizes come from `sizing`: `fill` and `hug` stay fluid. Use a
     fixed px value only where the spec has a number; never pin a box's measured width.
   - Token names, not raw values, wherever a project token matches.
   - Responsive changes at the breakpoints in `tokens.json`; states (hover, focus,
     active, disabled) from the States table. Focus stays visible.
   - Assets copied from the spec's `assets/` to where the project keeps them.
   After each file, run the project's type-check and lint commands, and fix errors before
   going on.

2. **Render.** For each viewport `w` in the spec, primary first:
   - `browser_resize` to `w` × 900, then `browser_navigate` to the preview.
   - Install the helpers by passing the full text of
     [../design-spec/references/dom-extract.js](../design-spec/references/dom-extract.js)
     as `browser_evaluate`'s `function`. Then call `() => window.__designSpec.settle()`.
   - Find the block: `() => window.__designSpec.extract("<selector of the built block>")`
     gives its page box (`block.box`) and its node tree. Save the result as
     `build/dom-<w>.json`.
   - `browser_take_screenshot` with `fullPage: true`, `type: png`, `scale: css` and a
     `filename`. Crop the block from it the way `design-spec` does (site Step 8), to
     `build/actual-<w>.png`.

3. **Diff.**
   `T diff <reference> build/actual-<w>.png --out build/diff-<w>.png --threshold <t>`
   (`<reference>` is `reference.png` at the primary viewport, `reference-<w>.png` at the
   others). `pass: true` → next viewport.

4. **Fix**, while `pass` is false and rounds are left:
   - **Size first.** If `size_match` is false, fix the block's height and width before
     anything else. Every other difference moves with it.
   - Take the largest boxes first (`boxes` is sorted by `pixels`). For each, crop the
     same region from the reference and the actual render (`T crop`, with 8 px of margin)
     and Read both. Find the spec nodes whose `box` overlaps it.
   - Compare those nodes with the built ones in `build/dom-<w>.json`: box, font, colour,
     spacing. For a `site` source, compare against the spec's `source/dom-<w>.json` node
     by node, since both come from the same `extract()`.
   - Change the code, re-render, re-diff. Each round must lower `mismatch_percent` or
     shrink the largest box. A change that makes either worse is reverted.

5. **When rounds run out**, read `build/diff-<w>.png`:
   - Only thin outlines around glyphs remain, and font family, size, weight, line height
     and colour equal the spec: the text is rendered by another engine (usual for a Figma
     source). Status `accepted: text rasterisation, <diff>% @<w>`.
   - Anything else: status `blocked: <what still differs>`. Show the diff image area and
     ask the user. Don't move on silently.

6. **Record** the status in design.md's Blocks table: `built`, `verified (<diff>% @<w>, …)`,
   `accepted: …` or `blocked: …`.

## Step 5 — Finish

- Run the project's test command; then its build command if it has one. Fix failures the
  change caused.
- If the preview shows the whole page and the spec came from a page (not single blocks),
  diff the full page once: a block can pass alone and still sit at the wrong offset.
- Report:

```
| Block | Mode | Files | Result |
|---|---|---|---|
| header | align | Header.tsx | verified (0.2% @1440, 0.4% @375) |
| hero | build | Hero.tsx, Hero.module.css | accepted: text rasterisation, 1.6% @1440 |

Design-system additions: radius.button. Diff images: .claude/design/home-page/blocks/*/build/
Checks: lint ✓, types ✓, tests ✓.
```

- Suggest `frontend-review` on the change.

## Constraints

- No code before the plan in Step 3 is approved. Only the files in the plan, plus stories and assets the plan names.
- No new tokens, token value changes, fonts or dependencies without an explicit yes.
- No git commits, pushes or branch changes unless the user asks.
- Never raise the threshold or loosen `--max-box-pixels` to make a block pass. `accepted` needs the reason Step 4.5 gives.
- Stop the dev server or Storybook you started when done.
