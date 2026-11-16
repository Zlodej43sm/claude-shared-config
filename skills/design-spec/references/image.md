# Image source

Extract a design from a screenshot or a mockup export. You read the image to understand
it. `tools/design_png.py` measures it, so positions, sizes and colours are pixel values
rather than guesses. Fonts, hidden states and behaviour can't be read from pixels; they
are `estimated` or go under Open questions.

`T` below is `python3 -I .claude/tools/design_png.py`.

## Prepare the image

1. **Convert to PNG.** For any other format, on macOS:
   `sips -s format png <in> --out source/original.png`. Elsewhere use any converter the
   user has (`magick <in> source/original.png`). Otherwise copy the PNG to
   `source/original.png`.
2. **Colour profile.** `T info source/original.png`. If it has a `hint` (not sRGB, e.g. a
   Display P3 Mac screenshot), convert with the command in the hint. Reading colours from
   a P3 image gives values that don't match CSS.
3. **Scale.** `info` lists `scale_candidates` (2880 px wide → 1440 at 2x). With one
   candidate, take it. With several or none, ask the user for the viewport width. If the
   scale isn't 1, make the 1x copy every measurement uses:
   `sips --resampleWidth <css width> source/original.png --out source/page-<width>.png`.
   Keep the original for reading small text. At scale 1, `source/page-<width>.png` is a
   copy of the original.

## Steps

1. **Read the page.** Look at `source/page-<width>.png` (Read the file) and name the
   blocks top to bottom: header, hero, sections, footer.
2. **Find exact boundaries.** `T bands source/page-<width>.png` returns horizontal
   segments where the background at the left and right edges stays the same colour, and
   the blank gaps inside them. A block edge is a segment edge, or the middle of a blank
   gap between two groups of content. Pick the `y` ranges, and check each against what
   you see.
   `--block`: take only the block the user named.
3. **Crop each block** to its reference:
   `T crop source/page-<width>.png blocks/NN-name/reference.png 0,<y>,<width>,<h>`
   (a block narrower than the page, like a card, gets its own `x` and `w`).
4. **Measure each block:**
   - `T palette blocks/NN-name/reference.png` gives the background and the main colours.
   - `T boxes blocks/NN-name/reference.png` gives the box of every group of content on
     the background (a text line, an icon, a button), with its main colour. Save the
     output as `blocks/NN-name/source/boxes-<width>.json`. Read the crop to match boxes to elements.
     Lower `--gap` to split words or icons that merged; raise it to merge a paragraph's
     lines into one box.
   - For a box that is a filled shape (button, badge, card), run `boxes --region` on it
     with `--bg` set to its fill colour. That separates the label from the fill and gives
     the padding: label box minus fill box.
   - `T pixel` for exact colours at chosen points: a button fill, a border line, a divider.
5. **Typography** (`estimated`):
   - Size: a text box covers the ink of its letters, not the font size. Measure the cap
     height: the box height of a capital with no descender (a word in capitals, or
     `boxes --region` around one capital letter). Common sans serifs have a cap height of
     about 0.7 em (Inter 0.73, Helvetica 0.72, Roboto 0.71), so the font size is about
     1.4 × the cap height. Round to a whole px and compare with the sizes used elsewhere
     on the page.
   - Line height: the distance between the tops of two lines of the same paragraph.
   - Weight and family: from the letter shapes. Name the closest common family (Inter,
     Roboto, Helvetica, Georgia) and put "font family" under Open questions.
6. **Write the spec** in the spec-format keys. Boxes and colours are `measured`. Font
   values, `fill`/`hug` sizing (one width can't show it) and layout modes inferred from
   alignment carry `estimated`. Set the block's `confidence: estimated` if any node has
   estimates.
7. **Assets.** Photos, illustrations and logos can't be cut out cleanly from a
   screenshot. Crop each one to `assets/<role>.png` as a placeholder at its box. Mark it
   `placeholder` in design.md's Assets table, and ask for the originals under Open questions.
8. **Other images.** Each extra image is the same design at another width: prepare it
   the same way, crop `reference-<width>.png` for each block, and fill the Responsive
   table. If an extra image shows a state instead (a hover, an open menu), the user says
   so; put it in the States table.

## Confidence

`measured` for positions, sizes and colours from pixels; `estimated` for fonts, sizing
rules and anything the image doesn't show.
