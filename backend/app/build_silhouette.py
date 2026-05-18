"""Bake 'KARRIÄR' into the silhouette PNG as transparent alpha cutouts."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

_IMG_DIR = Path(__file__).resolve().parent.parent.parent / "img"
SOURCE_CANDIDATES = (
    _IMG_DIR / "karriar-yrken-silhuet_crop2.png",
    _IMG_DIR / "karriar-yrken-silhuet_crop.png",
    _IMG_DIR / "karriar-yrken-silhuett.png",
)
OUTPUT = _IMG_DIR / "karriar-yrken-silhuet_karriar.png"

TEXT = "KARRIÄR"
TEXT_WIDTH_RATIO = 0.97
OUTLINE_PX = 1
FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("C:/Windows/Fonts/ARIALBD.TTF"),
    Path("C:/Windows/Fonts/impact.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)


def _find_source() -> Path:
    for path in SOURCE_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(f"No silhouette source in {_IMG_DIR}")


def _text_width(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), TEXT, font=font)
    return bbox[2] - bbox[0]


def _load_font(max_width: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    target = int(max_width * TEXT_WIDTH_RATIO)
    best: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None

    for font_path in FONT_CANDIDATES:
        if not font_path.is_file():
            continue
        candidate: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
        for size in range(40, 360, 2):
            font = ImageFont.truetype(str(font_path), size)
            if _text_width(font) <= target:
                candidate = font
            else:
                break
        if candidate is not None:
            best = candidate

    if best is not None:
        return best
    return ImageFont.load_default()


def _outline_mask(mask: Image.Image, px: int = 1) -> Image.Image:
    """1px ring along the text mask boundary."""
    dilated = mask
    eroded = mask
    for _ in range(px):
        dilated = dilated.filter(ImageFilter.MaxFilter(3))
        eroded = eroded.filter(ImageFilter.MinFilter(3))
    return ImageChops.subtract(dilated, eroded)


def build_silhouette_with_text(
    source: Path | None = None,
    output: Path | None = None,
    text_y_ratio: float = 0.36,
) -> Path:
    """Return path to PNG with KARRIÄR punched out as transparent alpha."""
    src = source or _find_source()
    out = output or OUTPUT

    im = Image.open(src).convert("RGBA")
    w, h = im.size
    font = _load_font(w)

    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = probe.textbbox((0, 0), TEXT, font=font)
    tw = bbox[2] - bbox[0]
    tx = (w - tw) // 2 - bbox[0]
    ty = int(h * text_y_ratio) - bbox[1]

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((tx, ty), TEXT, fill=255, font=font)
    outline = _outline_mask(mask, OUTLINE_PX)

    alpha = im.split()[3]
    alpha = Image.composite(Image.new("L", (w, h), 0), alpha, mask)
    alpha = Image.composite(Image.new("L", (w, h), 255), alpha, outline)

    r, g, b, _ = im.split()
    black = Image.new("L", (w, h), 0)
    r = Image.composite(black, r, outline)
    g = Image.composite(black, g, outline)
    b = Image.composite(black, b, outline)
    im = Image.merge("RGBA", (r, g, b, alpha))
    im.save(out)
    return out


if __name__ == "__main__":
    path = build_silhouette_with_text()
    print(f"Wrote {path} (text ~{TEXT_WIDTH_RATIO:.0%} width, {OUTLINE_PX}px outline)")
