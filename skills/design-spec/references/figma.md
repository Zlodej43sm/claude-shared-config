# Figma source

Extract a Figma frame through the Figma MCP server. The remote server (`https://mcp.figma.com/mcp`,
the project's `figma` entry) has every tool used here. The desktop server lacks
`download_assets` and `whoami`; the fallbacks are noted below.

Tool names carry the server prefix (`mcp__figma__get_metadata`, or the claude.ai connector's
prefix). Load the schemas with ToolSearch `figma` before the first call; parameter names
can change between server versions.

## Parse the URL

```
https://www.figma.com/design/<fileKey>/<title>?node-id=<a>-<b>
https://www.figma.com/design/<fileKey>/branch/<branchKey>/<title>?node-id=<a>-<b>
https://www.figma.com/file/<fileKey>/…      https://www.figma.com/proto/<fileKey>/…
```

- `fileKey`: the path segment after `/design/`, `/file/` or `/proto/`. On a branch URL, use `branchKey` instead.
- `nodeId`: the `node-id` query value with `-` replaced by `:` (`12-34` → `12:34`).
- No `node-id`: call `get_metadata` with the file key only. It lists the pages and their
  top-level frames. Show the frames with their sizes and ask which one to extract.
- `figma.com/board/…` (FigJam) or `figma.com/make/…` is not a UI design: say so and stop.

## Budget

Figma's read-tool limits for the remote server: 20 calls a month on a View or Collab seat.
With a Dev or Full seat, Professional allows 200 a day and 10 a minute, Organization 200 a
day and 15 a minute, and Enterprise 600 a day and 20 a minute. Call `whoami` first: it
doesn't count against the limit, and it gives the plan and seat.

Count the calls before starting: 1 `get_metadata` + 1 `get_variable_defs` +
1 `get_code_connect_map` + 1 `get_design_context` per block + 1 `download_assets` per 20
nodes, for each frame. On a View/Collab seat, or when the plan would pass a third of the
remaining daily budget, show the count and ask before going on. On a rate-limit error,
wait a minute (per-minute limit) or stop and report what was extracted (daily limit).

## Steps

1. **Outline.** `get_metadata(fileKey, nodeId)`. It returns an XML outline of the frame:
   every layer with id, name, type, position and size. The frame's width is the viewport.
   - Blocks are the frame's direct children. If the frame has one child as big as the
     frame (a wrapper), use that child's children instead.
   - Skip hidden layers. A child less than 24 px high merges into its neighbour (dividers).
   - Name each block from its layer name in kebab-case (`Header` → `header`,
     `Section / Popular` → `popular`). A generic name (`Frame 123`, `Group 4`) takes the
     name of its first text layer or its role (`hero`, `footer`).
   - `--block`: match the layer name (case-insensitive) or node id. No match: list the
     block names and ask.

2. **Tokens.** `get_variable_defs` on the frame: the variables and styles it uses, with
   names and values. Write them to `tokens.json`; keep names (`color/primary/500` →
   `color.primary-500`). Save the raw output as `source/figma-variables.md`.

3. **Components.** `get_code_connect_map` on the frame. Each mapped instance points to a
   component in the code. Fill design.md's Components table, so `design-build` reuses the
   component instead of rebuilding it. An empty result is normal; then list the Figma
   components that repeat across blocks (same component name in the outline).

4. **Each block.** For every block, in page order:
   - `get_design_context(fileKey, nodeId=<block id>)`, with `clientFrameworks` /
     `clientLanguages` set from the project's `package.json` (`react`, `vue`, `angular`,
     `html`; `typescript`, `javascript`) when the schema has them. Save the full response
     to `blocks/NN-name/source/figma-context.md`.
   - The response holds generated code (React + Tailwind unless told otherwise) and asset
     URLs. **Download the asset URLs right away**, because they expire:
     `curl -fsSL --max-time 30 -o assets/<name>.<ext> '<url>'`. Name files by role (`logo.svg`, `hero-photo.png`).
   - Translate to the spec's Structure tree. The generated code is a reading aid, not the
     answer: take values from it and from the outline, and write the tree in the
     spec-format keys.
     - Auto layout direction → `layout.mode`; item spacing → `gap`; padding → `padding`;
       primary/counter alignment → `justify` / `align`; wrap → `wrap`.
     - Resizing: fixed → px, fill container → `fill`, hug contents → `hug`; min/max widths.
     - No auto layout, children placed freely → `mode: stack`, with each child's `position`.
     - Fills → `bg` (image fills → `asset` + `fit`); strokes → `border` (inside/center/outside noted when it isn't inside); corner radius → `radius`; effects → `shadow` / `blur`.
     - Text style → `font` token; text content, alignment, case, decoration, truncation (`maxLines`).
     - Component instance → `el` from the Code Connect map, or the component name in Notes.
   - A response that is truncated or too large: call `get_metadata` on the block, then
     `get_design_context` on each child that holds content, and merge.
   - Interactive components with variants (`State=Hover`, `State=Disabled`) → the
     States table, values from the variant's design context when the frame shows it.

5. **References.** `download_assets` with the block node ids (up to 20 per call),
   `defaultFormat: png`, `defaultScale: 1`. Save each export as the block's
   `reference.png`. Then run `python3 -I .claude/tools/design_png.py info` on it: the width
   must equal the block's width in the outline. If it is 2x or 3x, export again at scale 1.
   - No `download_assets` (desktop server): ask the user to export each block at 1x
     (select the layer → Export → PNG 1x) and give the paths. Until then, use
     `get_screenshot` to look at the block. Write `reference: missing` in its frontmatter;
     `design-build` then compares by eye instead of by pixels.

6. **Other viewports.** Each extra Figma URL is a frame at another width. Run steps 1, 4
   and 5 on it, match its blocks to the primary ones by name (then by order), save
   `reference-<width>.png`, and fill the Responsive table with what changed. A block that
   exists at only one width is noted in the Responsive table.

7. **Fonts.** List every font family and weight from the text styles in design.md's Fonts
   table, and note where it comes from (Google Fonts, a licence the project has, unknown).

## Confidence

Values read from Figma are `exact`. A value taken only from the generated code, with no
property behind it in the design context, is `estimated`.
