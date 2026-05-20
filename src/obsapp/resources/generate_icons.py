"""Generate obsapp-icon.png and obsapp-icon.ico from a source PNG.

Usage:
    python generate_icons.py <source.png>

The source image should be at least 256x256 pixels and square (or it will be
cropped to a square from the centre before resizing).  Output files are written
next to this script:

    obsapp-icon.png  — 256x256 RGBA PNG (used by wm_iconphoto at runtime)
    obsapp-icon.ico  — multi-size ICO with entries at 16, 32, 48, 64, 128, 256 px
                       (used by iconbitmap at runtime)

Requires Pillow:
    pip install Pillow
"""

import sys
from pathlib import Path

from PIL import Image

ICO_SIZES = [16, 32, 48, 64, 128, 256]
OUT_DIR = Path(__file__).parent


def _centre_crop_to_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    if w == h:
        return img
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def generate(source: Path) -> None:
    img = Image.open(source).convert("RGBA")
    img = _centre_crop_to_square(img)

    if img.width < 256:
        print(f"Warning: source is only {img.width}px wide; result may be blurry.")

    # 256x256 PNG for wm_iconphoto
    png_out = OUT_DIR / "obsapp-icon.png"
    img.resize((256, 256), Image.LANCZOS).save(png_out)
    print(f"Written {png_out}")

    # Multi-size ICO for iconbitmap — Pillow resizes from this image to each
    # requested size using the 'sizes' parameter.
    src = img.resize((256, 256), Image.LANCZOS)
    ico_out = OUT_DIR / "obsapp-icon.ico"
    src.save(
        ico_out,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
    )
    print(f"Written {ico_out}  ({len(ICO_SIZES)} sizes: {ICO_SIZES})")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"Usage: python {Path(__file__).name} <source.png>")
    source = Path(sys.argv[1])
    if not source.exists():
        sys.exit(f"Error: file not found: {source}")
    generate(source)


if __name__ == "__main__":
    main()
