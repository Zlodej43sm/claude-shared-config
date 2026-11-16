#!/usr/bin/env python3
"""
design_png — measure, crop and compare PNG images for the design-spec and
design-build skills. Standard library only (no Pillow), so it runs anywhere
python3 does. Every subcommand prints one JSON object on stdout.

Usage:
  design_png.py info    <png>
  design_png.py pixel   <png> <x,y> [<x,y> ...]
  design_png.py palette <png> [--region x,y,w,h] [--top N]
  design_png.py bands   <png> [--tolerance T] [--min-gap PX]
  design_png.py boxes   <png> [--region x,y,w,h] [--bg auto|#rrggbb] [--tolerance T] [--gap PX]
  design_png.py crop    <png> <out.png> <x,y,w,h>
  design_png.py diff    <reference.png> <actual.png> [--out diff.png] [--tolerance T]
                        [--gap PX] [--threshold PERCENT] [--max-box-pixels N]

  info     size, colour profile, and the likely CSS viewport width / device scale
           (2880 px wide -> 1440 @2x). A non-sRGB image (a Mac screenshot is often
           Display P3) gets a hint with the command that converts it.
  pixel    exact colour at each point.
  palette  most frequent colours, with their share of the region.
  bands    splits a page screenshot into horizontal segments by edge background
           colour, and lists the blank (single-colour) gaps inside them: candidate
           block boundaries.
  boxes    bounding boxes of everything that differs from the background (text
           lines, icons, buttons), with each box's main foreground colour.
  crop     writes a region to a new PNG.
  diff     compares two renders: size match, share of mismatched pixels, boxes
           around the mismatches, and a diff PNG (reference faded, mismatches red,
           area outside the overlap magenta). --threshold adds "pass": sizes
           within 1 px, mismatch share at or under the threshold, and no single
           mismatch box holding more than --max-box-pixels pixels (default 400).
           The box limit catches a wrong colour on one element, which is a small
           share of a large block. Text rendered by another engine (Figma vs a
           browser) leaves thin outlines around glyphs; read the diff PNG to tell
           those from real errors.

Tolerance is the largest per-channel difference (0-255) still treated as equal;
it absorbs anti-aliasing (diff default 8: a colour off by 8 levels or more
counts). Only 8- and 16-bit, non-interlaced PNGs are read;
convert other formats first (macOS: sips -s format png in.jpg --out in.png).
Output files (crop, diff --out) must be .png files inside the current directory;
the tool refuses any other path.
Exit codes: 0 ok, 1 usage, unreadable input or refused output path.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS_BY_COLOR_TYPE = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
COMMON_CSS_WIDTHS = (320, 360, 375, 390, 393, 412, 414, 428, 430, 744, 768, 800, 820, 834,
                     1024, 1280, 1366, 1440, 1536, 1600, 1680, 1728, 1920, 2560)
BOX_CELL = 4
MAX_BOXES = 300
PALETTE_SAMPLE_LIMIT = 2_000_000


class PngError(Exception):
    pass


class Image:
    def __init__(self, width: int, height: int, rows: list[bytes], profile: str = "sRGB"):
        self.width = width
        self.height = height
        self.rows = rows
        self.profile = profile

    def pixel(self, x: int, y: int) -> bytes:
        return self.rows[y][4 * x:4 * x + 4]


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def unfilter_line(kind: int, line: bytearray, prev: bytearray, bpp: int) -> None:
    n = len(line)
    if kind == 0:
        return
    if kind == 1:
        for i in range(bpp, n):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif kind == 2:
        for i in range(n):
            line[i] = (line[i] + prev[i]) & 0xFF
    elif kind == 3:
        for i in range(n):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif kind == 4:
        for i in range(n):
            left = line[i - bpp] if i >= bpp else 0
            upper_left = prev[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + paeth(left, prev[i], upper_left)) & 0xFF
    else:
        raise PngError(f"unknown PNG filter type {kind}")


def palette_tables(plte: bytes, trns: bytes | None) -> tuple[bytes, bytes, bytes, bytes]:
    entries = len(plte) // 3
    red = bytearray(range(256))
    green = bytearray(range(256))
    blue = bytearray(range(256))
    alpha = bytearray(b"\xff" * 256)
    for i in range(entries):
        red[i], green[i], blue[i] = plte[3 * i], plte[3 * i + 1], plte[3 * i + 2]
    for i, value in enumerate(trns or b""):
        alpha[i] = value
    return bytes(red), bytes(green), bytes(blue), bytes(alpha)


def to_rgba(line: bytes, color_type: int, width: int, tables) -> bytes:
    if color_type == 6:
        return bytes(line)
    out = bytearray(4 * width)
    if color_type == 2:
        out[0::4], out[1::4], out[2::4] = line[0::3], line[1::3], line[2::3]
        out[3::4] = b"\xff" * width
    elif color_type == 0:
        out[0::4] = out[1::4] = out[2::4] = line
        out[3::4] = b"\xff" * width
    elif color_type == 4:
        gray = line[0::2]
        out[0::4] = out[1::4] = out[2::4] = gray
        out[3::4] = line[1::2]
    elif color_type == 3:
        indices = bytes(line)
        red, green, blue, alpha = tables
        out[0::4] = indices.translate(red)
        out[1::4] = indices.translate(green)
        out[2::4] = indices.translate(blue)
        out[3::4] = indices.translate(alpha)
    return bytes(out)


def read_png(path: str) -> Image:
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise PngError(f"cannot read {path}: {error.strerror}") from error
    if data[:8] != PNG_SIGNATURE:
        raise PngError(f"{path} is not a PNG; convert it first (macOS: sips -s format png <in> --out <out>.png)")
    pos, idat, plte, trns, header, profile = 8, [], b"", None, None, "untagged"
    while pos + 8 <= len(data):
        length, chunk_type = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif chunk_type == b"PLTE":
            plte = body
        elif chunk_type == b"tRNS":
            trns = body
        elif chunk_type == b"IDAT":
            idat.append(body)
        elif chunk_type == b"sRGB":
            profile = "sRGB"
        elif chunk_type == b"iCCP":
            profile = body.split(b"\x00", 1)[0].decode("latin-1") or "embedded ICC"
        elif chunk_type == b"IEND":
            break
    if header is None:
        raise PngError(f"{path}: missing IHDR chunk")
    width, height, depth, color_type, _, _, interlace = header
    if interlace:
        raise PngError(f"{path}: interlaced PNG; re-export it without interlacing")
    if color_type not in CHANNELS_BY_COLOR_TYPE or depth not in (8, 16) or (color_type == 3 and depth != 8):
        raise PngError(f"{path}: unsupported PNG (color type {color_type}, bit depth {depth})")
    channels = CHANNELS_BY_COLOR_TYPE[color_type]
    bytes_per_sample = depth // 8
    bpp = channels * bytes_per_sample
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    if len(raw) < height * (stride + 1):
        raise PngError(f"{path}: truncated image data")
    tables = palette_tables(plte, trns) if color_type == 3 else None
    rows, prev, offset = [], bytearray(stride), 0
    for _ in range(height):
        kind = raw[offset]
        line = bytearray(raw[offset + 1:offset + 1 + stride])
        offset += 1 + stride
        unfilter_line(kind, line, prev, bpp)
        prev = line
        samples = line[0::2] if bytes_per_sample == 2 else line
        rows.append(to_rgba(samples, color_type, width, tables))
    return Image(width, height, rows, profile)


def png_chunk(chunk_type: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + chunk_type + body + struct.pack(">I", zlib.crc32(chunk_type + body))


def safe_output_path(path: str) -> Path:
    target = Path(path).expanduser().resolve()
    root = Path.cwd().resolve()
    if target.suffix.lower() != ".png" or not target.is_relative_to(root):
        raise PngError(f"refusing to write {path}: output must be a .png file inside {root}")
    return target


def write_png(path: str, image: Image) -> None:
    target = safe_output_path(path)
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in image.rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PNG_SIGNATURE + png_chunk(b"IHDR", header)
                           + png_chunk(b"IDAT", zlib.compress(raw, 6)) + png_chunk(b"IEND", b""))


def hex_color(rgba: bytes) -> str:
    text = "#{:02x}{:02x}{:02x}".format(rgba[0], rgba[1], rgba[2])
    return text if rgba[3] == 255 else text + "{:02x}".format(rgba[3])


def parse_hex(text: str) -> bytes:
    value = text.lstrip("#")
    if len(value) not in (6, 8):
        raise PngError(f"bad colour {text!r}; use #rrggbb or #rrggbbaa")
    rgba = bytes.fromhex(value)
    return rgba if len(rgba) == 4 else rgba + b"\xff"


def parse_ints(text: str, count: int, label: str) -> list[int]:
    try:
        values = [int(part) for part in text.split(",")]
    except ValueError:
        values = []
    if len(values) != count or any(v < 0 for v in values):
        raise PngError(f"bad {label} {text!r}; expected {count} non-negative integers separated by commas")
    return values


def parse_region(text: str | None, image: Image) -> tuple[int, int, int, int]:
    if not text:
        return 0, 0, image.width, image.height
    x, y, w, h = parse_ints(text, 4, "region")
    if w == 0 or h == 0 or x + w > image.width or y + h > image.height:
        raise PngError(f"region {text} is outside the {image.width}x{image.height} image")
    return x, y, w, h


def differs(a: bytes, b: bytes, tolerance: int) -> bool:
    return (abs(a[0] - b[0]) > tolerance or abs(a[1] - b[1]) > tolerance
            or abs(a[2] - b[2]) > tolerance or abs(a[3] - b[3]) > tolerance)


def color_counts(image: Image, region: tuple[int, int, int, int]) -> Counter:
    x, y, w, h = region
    step = 1
    while (w // step) * (h // step) > PALETTE_SAMPLE_LIMIT:
        step += 1
    counts: Counter = Counter()
    for row_index in range(y, y + h, step):
        row = image.rows[row_index]
        for col in range(x, x + w, step):
            counts[row[4 * col:4 * col + 4]] += 1
    return counts


def scale_candidates(width: int) -> list[dict]:
    return [{"css_width": width // scale, "scale": scale}
            for scale in (1, 2, 3) if width % scale == 0 and width // scale in COMMON_CSS_WIDTHS]


def is_srgb_like(profile: str) -> bool:
    return profile == "untagged" or "srgb" in profile.lower() or "iec61966" in profile.lower()


def cmd_info(args) -> dict:
    image = read_png(args.png)
    result = {"width": image.width, "height": image.height, "color_profile": image.profile,
              "scale_candidates": scale_candidates(image.width)}
    if not is_srgb_like(image.profile):
        result["hint"] = ("not sRGB: colours read from it won't match CSS values. Convert first "
                          "(macOS: sips --matchTo '/System/Library/ColorSync/Profiles/sRGB Profile.icc' <in> --out <out>.png)")
    return result


def cmd_pixel(args) -> dict:
    image = read_png(args.png)
    points = []
    for point in args.points:
        x, y = parse_ints(point, 2, "point")
        if x >= image.width or y >= image.height:
            raise PngError(f"point {point} is outside the {image.width}x{image.height} image")
        points.append({"x": x, "y": y, "color": hex_color(image.pixel(x, y))})
    return {"points": points}


def cmd_palette(args) -> dict:
    image = read_png(args.png)
    region = parse_region(args.region, image)
    counts = color_counts(image, region)
    total = sum(counts.values())
    return {"region": dict(zip("xywh", region)),
            "colors": [{"color": hex_color(c), "share": round(100 * n / total, 2)}
                       for c, n in counts.most_common(args.top)]}


def row_is_uniform(row: bytes, width: int, tolerance: int) -> bool:
    first = row[:4]
    if row == first * width:
        return True
    if tolerance == 0:
        return False
    for col in range(1, width):
        if differs(row[4 * col:4 * col + 4], first, tolerance):
            return False
    return True


MIXED_EDGE = b""


def edge_color(row: bytes, width: int) -> bytes:
    left_x, right_x = min(1, width - 1), max(0, width - 2)
    left, right = row[4 * left_x:4 * left_x + 4], row[4 * right_x:4 * right_x + 4]
    return left if left == right else MIXED_EDGE


def runs_of(keys: list[bytes]) -> list[list]:
    runs: list[list] = []
    for y, key in enumerate(keys):
        if runs and runs[-1][0] == key:
            runs[-1][2] = y
        else:
            runs.append([key, y, y])
    return runs


def merge_equal_neighbours(runs: list[list]) -> list[list]:
    merged: list[list] = []
    for key, y0, y1 in runs:
        if merged and merged[-1][0] == key:
            merged[-1][2] = y1
        else:
            merged.append([key, y0, y1])
    return merged


def blank_gaps(image: Image, y0: int, y1: int, tolerance: int, min_gap: int) -> list[dict]:
    gaps, gap_start = [], None
    for y in range(y0, y1 + 2):
        uniform = y <= y1 and row_is_uniform(image.rows[y], image.width, tolerance)
        if uniform and gap_start is None:
            gap_start = y
        elif not uniform and gap_start is not None:
            if y - gap_start >= min_gap:
                gaps.append({"y": gap_start, "h": y - gap_start})
            gap_start = None
    return gaps


def cmd_bands(args) -> dict:
    image = read_png(args.png)
    runs = runs_of([edge_color(row, image.width) for row in image.rows])
    runs = merge_equal_neighbours([[key if y1 - y0 + 1 >= args.min_gap else MIXED_EDGE, y0, y1]
                                   for key, y0, y1 in runs])
    segments: list[list] = []
    for run in runs:
        if segments and run[2] - run[1] + 1 < args.min_gap:
            segments[-1][2] = run[2]
        else:
            segments.append(run)
    return {"width": image.width, "height": image.height, "segments": [
        {"y": y0, "h": y1 - y0 + 1, "edge_color": hex_color(key) if key else None,
         "blank_gaps": blank_gaps(image, y0, y1, args.tolerance, args.min_gap)}
        for key, y0, y1 in segments]}


def components(cells: set[tuple[int, int]], reach: int) -> list[set[tuple[int, int]]]:
    groups, remaining = [], set(cells)
    while remaining:
        seed = remaining.pop()
        group, stack = {seed}, [seed]
        while stack:
            cx, cy = stack.pop()
            for dx in range(-reach, reach + 1):
                for dy in range(-reach, reach + 1):
                    neighbour = (cx + dx, cy + dy)
                    if neighbour in remaining:
                        remaining.discard(neighbour)
                        group.add(neighbour)
                        stack.append(neighbour)
        groups.append(group)
    return groups


def mask_boxes(mask_rows: dict[int, list[int]], gap: int) -> list[dict]:
    cells = {(x // BOX_CELL, y // BOX_CELL) for y, xs in mask_rows.items() for x in xs}
    reach = max(1, -(-gap // BOX_CELL))
    boxes = []
    for group in components(cells, reach):
        x0 = min(c[0] for c in group) * BOX_CELL
        y0 = min(c[1] for c in group) * BOX_CELL
        x1 = (max(c[0] for c in group) + 1) * BOX_CELL
        y1 = (max(c[1] for c in group) + 1) * BOX_CELL
        xs, ys, pixels = [], [], 0
        for y in range(y0, y1):
            hits = [x for x in mask_rows.get(y, ()) if x0 <= x < x1]
            if hits:
                ys.append(y)
                xs.extend((hits[0], hits[-1]))
                pixels += len(hits)
        if pixels:
            boxes.append({"x": min(xs), "y": min(ys), "w": max(xs) - min(xs) + 1,
                          "h": max(ys) - min(ys) + 1, "pixels": pixels})
    boxes.sort(key=lambda b: (b["y"], b["x"]))
    return boxes


def cmd_boxes(args) -> dict:
    image = read_png(args.png)
    region = parse_region(args.region, image)
    rx, ry, rw, rh = region
    background = (color_counts(image, region).most_common(1)[0][0]
                  if args.bg == "auto" else parse_hex(args.bg))
    mask_rows: dict[int, list[int]] = {}
    for y in range(ry, ry + rh):
        row = image.rows[y]
        if row[4 * rx:4 * (rx + rw)] == background * rw:
            continue
        hits = [x for x in range(rx, rx + rw) if differs(row[4 * x:4 * x + 4], background, args.tolerance)]
        if hits:
            mask_rows[y] = hits
    boxes = mask_boxes(mask_rows, args.gap)
    for box in boxes[:MAX_BOXES]:
        counts: Counter = Counter()
        for y in range(box["y"], box["y"] + box["h"]):
            row = image.rows[y]
            for x in mask_rows.get(y, ()):
                if box["x"] <= x < box["x"] + box["w"]:
                    counts[row[4 * x:4 * x + 4]] += 1
        box["main_color"] = hex_color(counts.most_common(1)[0][0])
    return {"region": dict(zip("xywh", region)), "background": hex_color(background),
            "count": len(boxes), "boxes": boxes[:MAX_BOXES], "truncated": len(boxes) > MAX_BOXES}


def cmd_crop(args) -> dict:
    image = read_png(args.png)
    x, y, w, h = parse_region(args.region, image)
    write_png(args.out, Image(w, h, [row[4 * x:4 * (x + w)] for row in image.rows[y:y + h]]))
    return {"out": args.out, "width": w, "height": h}


def faded(row: bytes) -> bytearray:
    out = bytearray(row)
    for i in range(0, len(out), 4):
        gray = (out[i] * 30 + out[i + 1] * 59 + out[i + 2] * 11) // 100
        out[i] = out[i + 1] = out[i + 2] = 192 + gray // 4
        out[i + 3] = 255
    return out


def scale_hint(reference: Image, actual: Image) -> str | None:
    for factor in (2, 3):
        if actual.width == reference.width * factor:
            return f"actual is {factor}x the reference width: take the screenshot in CSS pixels (scale 'css') or export the reference at {factor}x"
        if reference.width == actual.width * factor:
            return f"reference is {factor}x the actual width: export the reference at 1x or crop it from a 1x render"
    return None


def cmd_diff(args) -> dict:
    reference, actual = read_png(args.reference), read_png(args.actual)
    width, height = max(reference.width, actual.width), max(reference.height, actual.height)
    overlap_w, overlap_h = min(reference.width, actual.width), min(reference.height, actual.height)
    mask_rows: dict[int, list[int]] = {}
    diff_rows = []
    mismatched = 0
    for y in range(height):
        out = bytearray(b"\xff\x00\xff\xff" * width)
        if y < overlap_h:
            ref_row, act_row = reference.rows[y], actual.rows[y]
            out[:4 * overlap_w] = faded(ref_row[:4 * overlap_w])
            if ref_row[:4 * overlap_w] != act_row[:4 * overlap_w]:
                hits = [x for x in range(overlap_w)
                        if differs(ref_row[4 * x:4 * x + 4], act_row[4 * x:4 * x + 4], args.tolerance)]
                for x in hits:
                    out[4 * x:4 * x + 4] = b"\xff\x00\x00\xff"
                if hits:
                    mask_rows[y] = hits
                    mismatched += len(hits)
            outside = list(range(overlap_w, width))
        else:
            outside = list(range(width))
        if outside:
            mask_rows.setdefault(y, []).extend(outside)
            mismatched += len(outside)
        diff_rows.append(bytes(out))
    ratio = mismatched / (width * height)
    boxes = mask_boxes(mask_rows, args.gap)
    size_match = abs(reference.width - actual.width) <= 1 and abs(reference.height - actual.height) <= 1
    largest_box = max((box["pixels"] for box in boxes), default=0)
    result = {
        "reference": {"width": reference.width, "height": reference.height},
        "actual": {"width": actual.width, "height": actual.height},
        "size_match": size_match,
        "mismatch_pixels": mismatched,
        "mismatch_percent": round(100 * ratio, 3),
        "largest_box_pixels": largest_box,
        "boxes": sorted(boxes, key=lambda b: -b["pixels"])[:MAX_BOXES],
        "boxes_truncated": len(boxes) > MAX_BOXES,
    }
    hint = scale_hint(reference, actual)
    if hint:
        result["hint"] = hint
    if args.out:
        write_png(args.out, Image(width, height, diff_rows))
        result["diff_png"] = args.out
    if args.threshold is not None:
        result["threshold_percent"] = args.threshold
        result["max_box_pixels"] = args.max_box_pixels
        result["pass"] = size_match and 100 * ratio <= args.threshold and largest_box <= args.max_box_pixels
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure, crop and compare PNGs (design-spec / design-build).")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info")
    info.add_argument("png")
    info.set_defaults(run=cmd_info)

    pixel = sub.add_parser("pixel")
    pixel.add_argument("png")
    pixel.add_argument("points", nargs="+")
    pixel.set_defaults(run=cmd_pixel)

    palette = sub.add_parser("palette")
    palette.add_argument("png")
    palette.add_argument("--region")
    palette.add_argument("--top", type=int, default=12)
    palette.set_defaults(run=cmd_palette)

    bands = sub.add_parser("bands")
    bands.add_argument("png")
    bands.add_argument("--tolerance", type=int, default=4)
    bands.add_argument("--min-gap", type=int, default=24)
    bands.set_defaults(run=cmd_bands)

    boxes = sub.add_parser("boxes")
    boxes.add_argument("png")
    boxes.add_argument("--region")
    boxes.add_argument("--bg", default="auto")
    boxes.add_argument("--tolerance", type=int, default=24)
    boxes.add_argument("--gap", type=int, default=6)
    boxes.set_defaults(run=cmd_boxes)

    crop = sub.add_parser("crop")
    crop.add_argument("png")
    crop.add_argument("out")
    crop.add_argument("region")
    crop.set_defaults(run=cmd_crop)

    diff = sub.add_parser("diff")
    diff.add_argument("reference")
    diff.add_argument("actual")
    diff.add_argument("--out")
    diff.add_argument("--tolerance", type=int, default=8)
    diff.add_argument("--gap", type=int, default=8)
    diff.add_argument("--threshold", type=float)
    diff.add_argument("--max-box-pixels", type=int, default=400)
    diff.set_defaults(run=cmd_diff)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.run(args)
    except (PngError, zlib.error) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
