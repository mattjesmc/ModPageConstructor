"""Generate placeholder banner PNGs so a repo can build before its art exists.

    python tools/make_placeholder_banners.py path/to/repo/assets/banners "Mod Name"

Writes header.png, contents.png and one banner per canonical section. Replace them with real
art whenever you like -- the filenames are what modpage looks for.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modpage.config import CANONICAL_SECTIONS, TOC_ID, TOC_TITLE  # noqa: E402

INK = (237, 233, 254)
ACCENT = (167, 139, 250)
BACKDROP = (30, 27, 46)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _banner(path: Path, text: str, width: int, height: int, size: int) -> None:
    image = Image.new("RGB", (width, height), BACKDROP)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, height - 4, width, height], fill=ACCENT)
    font = _font(size)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((width - (box[2] - box[0])) / 2, (height - (box[3] - box[1])) / 2 - box[1]),
        text, font=font, fill=INK,
    )
    image.save(path)
    print(f"wrote {path}")


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/banners")
    title = sys.argv[2] if len(sys.argv) > 2 else "Mod Name"
    out.mkdir(parents=True, exist_ok=True)

    _banner(out / "header.png", title, 1200, 340, 84)
    for sid, section_title in [(TOC_ID, TOC_TITLE), *CANONICAL_SECTIONS]:
        _banner(out / f"{sid}.png", section_title.upper(), 960, 120, 44)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
