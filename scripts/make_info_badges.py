"""One-off conversion: 'dark mode info icon.jpg' / 'light mode info icon
vector.jpg' (opaque square rasters of the info-badge artwork, white
background) -> transparent-cornered RGBA PNGs the app loads directly
(`components.thumbnail_carousel._info_badge_source`), same pattern as
audio-mute.png. Re-run this if either source .jpg is replaced.

Approach: find the drawn circle's bounding box (everything that isn't
near-white), crop to it, then clip to a circular alpha mask sized to that
same box. This keeps each icon's own interior fill exactly as drawn (the
dark badge's solid dark disc; the light badge's white disc + dark ring +
dark glyph) and only makes the truly-outside-the-circle corners
transparent — a plain white-background chroma-key would also hollow out
the light badge's white interior, which is wrong.
"""
import os

from PIL import Image, ImageChops, ImageDraw

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

SOURCES = {
    "dark": ("dark mode info icon.jpg", "info-icon-dark.png"),
    "light": ("light mode info icon vector.jpg", "info-icon-light.png"),
}

OUT_SIZE = 512


def content_bbox(img_rgb):
    bg = Image.new("RGB", img_rgb.size, (255, 255, 255))
    diff = ImageChops.difference(img_rgb, bg).convert("L")
    bw = diff.point(lambda p: 255 if p > 8 else 0)
    return bw.getbbox()


def make_badge(src_name, out_name):
    src_path = os.path.join(ROOT, src_name)
    img = Image.open(src_path).convert("RGB")
    bbox = content_bbox(img)
    if bbox is None:
        raise SystemExit(f"{src_name}: no non-white content found")
    x0, y0, x1, y1 = bbox
    size = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left, top = int(round(cx - size / 2)), int(round(cy - size / 2))
    crop = img.crop((left, top, left + size, top + size)).convert("RGBA")

    # Supersampled circular mask for a clean (antialiased) edge -- PIL's
    # ellipse has no AA of its own (see CLAUDE.md's Known Issues).
    ss = 4
    big = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(big).ellipse([0, 0, size * ss - 1, size * ss - 1], fill=255)
    mask = big.resize((size, size), Image.LANCZOS)
    crop.putalpha(mask)

    out = crop.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
    out_path = os.path.join(ROOT, out_name)
    out.save(out_path)
    print(f"{src_name} -> {out_name}  bbox={bbox} size={size} -> {OUT_SIZE}")


if __name__ == "__main__":
    for _key, (src, out) in SOURCES.items():
        make_badge(src, out)
