# Design spec format

The contract between `design-spec` (writes it) and `design-build` (reads it). One spec
directory holds one design: a page, a screen or a single block. Every value is in CSS
pixels at the viewport named in the file, never device pixels.

## Directory layout

```
.claude/design/<slug>/
  design.md                      index: source, viewports, block list and status, fonts, assets, open questions
  tokens.json                    colours, type styles, spacing, radii, shadows, breakpoints
  assets/                        images, icons and SVGs used by the blocks
  source/                        raw page-level extraction (Figma variables, site tokens dump, the original image)
  blocks/<NN>-<name>/
    spec.md                      the block: structure, styles, states, responsive changes
    reference.png                the block rendered at the primary viewport, 1x
    reference-<width>.png        the block at each other viewport, 1x
    source/                      raw block extraction: figma-context.md, dom-<width>.json
    build/                       written by design-build: actual-<width>.png, diff-<width>.png, dom-<width>.json
```

`<NN>` is the block's order on the page (`01`, `02`, …) and `<name>` its kebab-case name
(`header`, `hero`, `popular-restaurants`, `footer`). The order is top to bottom; a fixed or
sticky element (cookie bar, sticky header) keeps the place it has at scroll 0.

## design.md

```markdown
---
name: home-page
source: figma | site | image
source_ref: https://www.figma.com/design/AbC123/Home?node-id=12-34
captured: 2026-11-16
viewports: [1440, 375]
diff_threshold: 2
---
# Home page

## Blocks
| # | Block | Spec | Size @1440 | Locator | Status |
|---|---|---|---|---|---|
| 1 | header | blocks/01-header/spec.md | 1440×72 | node 12:35 | extracted |
| 2 | hero | blocks/02-hero/spec.md | 1440×480 | node 12:40 | verified (0.4% @1440, 0.9% @375) |

## Page
Page background, content max-width and side gutters, how blocks stack (sticky header,
overlapping hero), scroll behaviour.

## Components
| Component | Used in | Code mapping |
|---|---|---|
| Button / primary | hero, footer | `src/components/Button.tsx` (Figma Code Connect) |

## Fonts
| Family | Weights | Origin |
|---|---|---|
| Inter | 400, 600, 700 | Figma text styles; Google Fonts |

## Assets
| File | Kind | Used in | Origin |
|---|---|---|---|
| assets/logo.svg | svg | header, footer | Figma node 12:36 |

## Open questions
- What the source can't answer: hover states missing from a screenshot, no mobile frame, text that is a placeholder.
```

Fields:

| Field | Meaning |
|---|---|
| `source` | `figma`, `site` (a URL or a local HTML file) or `image` |
| `source_ref` | the Figma URL with `node-id`, the page URL, or the image path(s) |
| `viewports` | CSS widths captured; the first is the primary one that `reference.png` and every `box` use |
| `diff_threshold` | percentage of mismatched pixels `design-build` accepts per block (table below) |
| Locator | how to find the block again: Figma node id, CSS selector, or `crop x,y,w,h` in the 1x source image |
| Status | `extracted` → `built` → `verified (<diff> @<width>, …)`; or `accepted: <reason>` when a remaining difference is explained (text rendered by another engine); or `blocked: <what is left>` |

Default `diff_threshold`, set by `design-spec` from the source:

| Source | Threshold | Why |
|---|---|---|
| site | 0.5 | Same engine renders reference and build; only real differences remain |
| figma | 2 | Figma and browsers rasterise text differently; glyph edges differ |
| image | 5 | Positions and colours are measured, fonts are estimated |

`design-build --threshold` overrides it. A block also fails when one mismatch box holds more
pixels than the `--max-box-pixels` limit of `tools/design_png.py diff`, so one wrong-coloured
button can't hide inside a large block.

## tokens.json

Named design values. Each entry carries the value and where it came from, so `design-build`
can map it to a token the project already has.

```json
{
  "color": {
    "primary": { "value": "#e03a2a", "source": "--color-primary" },
    "text": { "value": "#222222", "source": "most used text colour" }
  },
  "font": {
    "heading-xl": { "family": "Inter", "weight": 700, "size": 48, "lineHeight": 56, "letterSpacing": 0, "source": "Figma style Heading/XL" },
    "body": { "family": "Inter", "weight": 400, "size": 16, "lineHeight": 24, "letterSpacing": 0, "source": "Figma style Body/M" }
  },
  "space": { "s": { "value": 8 }, "m": { "value": 16 }, "l": { "value": 24 } },
  "radius": { "button": { "value": 8 } },
  "shadow": { "card": { "value": "0 2px 8px rgba(0, 0, 0, 0.08)" } },
  "breakpoint": { "mobile": { "value": 375 }, "desktop": { "value": 1440 } }
}
```

- Names come from the source when it has them: Figma variable or style names
  (`color/primary/500` → `primary-500`), CSS custom properties (`--color-primary` →
  `primary`). Otherwise name by role (`text`, `surface`, `border`), never by value (`red`).
- Lengths are numbers in px. Colours are `#rrggbb`, or `#rrggbbaa` with alpha.
- A value that appears once and has no name in the source stays raw in the block spec;
  it is not a token.

## blocks/NN-name/spec.md

Frontmatter, then fixed sections in this order. Leave a section out only when it has
nothing (a block without states has no States section).

````markdown
---
block: header
order: 1
viewport: 1440
size: { w: 1440, h: 72 }
reference: reference.png
locator: { figma_node: "12:35" }
position: sticky top 0
confidence: exact
---
# Header

## Role
Site header, `<header>` landmark. Logo links home; three nav links; sticky on scroll.
Reuses: Button / primary (see design.md Components).

## Structure
```yaml
- id: header
  el: header
  box: [0, 0, 1440, 72]
  layout: { mode: row, justify: space-between, align: center, padding: [0, 32, 0, 32] }
  sizing: { w: fill, h: 72 }
  style: { bg: color.surface, border-bottom: 1px solid color.border }
  children:
    - id: logo
      el: a
      box: [32, 20, 120, 32]
      asset: assets/logo.svg
      attrs: { href: /, aria-label: Home }
    - id: nav
      el: nav > ul
      box: [1159, 27, 249, 18]
      layout: { mode: row, gap: 24 }
      repeat: { count: 3, item: nav-link }
      children:
        - id: nav-link
          el: a
          text: { content: [Restaurants, Offers, Gift cards], font: font.nav, color: color.text-secondary }
```

## States
| Element | State | Change |
|---|---|---|
| nav-link | hover | color: color.primary; text-decoration: underline |

## Responsive
| Viewport | Change |
|---|---|
| 375 | nav hidden; burger button 24×24 at [335, 24]; height 56 (reference-375.png) |

## Assets
| File | Node | Size |
|---|---|---|
| assets/logo.svg | logo | 120×32 |

## Notes
Deviations and anything the build needs that the tree can't hold.
````

### Frontmatter

| Field | Meaning |
|---|---|
| `viewport` | CSS width every `box` in this file is measured at |
| `size` | the block's box at that viewport |
| `locator` | `figma_node`, `selector` or `crop: [x, y, w, h]` (1x source pixels) |
| `position` | `static`, `sticky top <n>`, `fixed top <n>`, or `overlaps <block> by <n>` |
| `confidence` | `exact` (read from Figma or computed styles), `measured` (from image pixels), `estimated` (guessed, e.g. a font from a screenshot) |

### Structure nodes

The tree lists every visible element that has its own box, paint or text. Wrappers with
no styling of their own are left out.

| Key | Meaning |
|---|---|
| `id` | unique within the block, kebab-case, by role (`logo`, `search-button`) |
| `el` | suggested element: a semantic tag (`header`, `nav`, `button`, `a`, `h2`, `ul`), or a short chain (`nav > ul`) |
| `box` | `[x, y, w, h]` relative to the block's top-left, at the spec viewport |
| `layout` | `mode`: `row`, `column`, `grid`, `stack` (children positioned absolutely) or `none`; with `gap`, `padding` `[t, r, b, l]`, `justify`, `align`, `wrap`, and for grid `columns` / `rows` (e.g. `repeat(3, 1fr)`) |
| `sizing` | per axis: a number (fixed px), `fill` (stretches to the parent), `hug` (fits content); plus `min` / `max` when set |
| `style` | paint: `bg`, `border` (or per side), `radius`, `shadow`, `opacity`, `blur`, `overflow` |
| `text` | `content` (a string, or a list when `repeat` uses one per item), `font` (token or inline `{family, weight, size, lineHeight, letterSpacing}`), `color`, `align`, `transform`, `decoration`, `maxLines` |
| `asset` | file under `assets/`; for images also `fit` (`cover`, `contain`) |
| `attrs` | `href`, `alt`, `aria-label`, `type`, `placeholder` |
| `repeat` | `{ count, item }`: the child with `id: item` repeats `count` times with the same layout |
| `position` | for `stack` children: `{ top, right, bottom, left }`, and `z` |
| `estimated` | list of keys in this node that are guesses, e.g. `[text.font]` |
| `children` | nested nodes, in visual order |

Values reference tokens as `<group>.<name>` (`color.primary`, `font.body`) when the value
equals a token; otherwise they are raw (`#f5f5f5`, `14`).

### Source files

`source/` keeps the raw extraction so `design-build` can look up a value the spec left out:

| File | Written for | Content |
|---|---|---|
| `source/figma-context.md` | figma | `get_design_context` output for the block node |
| `source/dom-<width>.json` | site | `window.__designSpec.extract()` output: `tree` of nodes with `tag`, `box`, `attrs`, `text`, non-default computed `style`, `children`; plus `assets` |
| `source/boxes-<width>.json` | image | `tools/design_png.py boxes` output for the block crop |

`design-build` runs the same `extract()` on the block it built, so `dom-<width>.json` and
the build's output compare node by node.
