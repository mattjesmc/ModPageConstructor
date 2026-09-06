"""Draw a parsed recipe as a small PNG, or a GIF when a slot has alternatives.

The card is composed at native texture scale (16px items) and only then scaled
up with nearest-neighbour, so the pixels stay sharp. Slot counts are drawn after
the upscale from a built-in pixel font, so they look the same on every machine.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence

from .recipes import Ingredient, Recipe
from .textures import TextureResolver

# Logical geometry, in texture pixels.
ITEM = 16
SLOT = 18
GAP = 1
PAD = 4
ARROW_W = 12
ARROW_GAP = 5
RESULT_SLOT = 26

PANEL = (198, 198, 198)
SLOT_FILL = (139, 139, 139)
SLOT_DARK = (55, 55, 55)
SLOT_LIGHT = (255, 255, 255)
ARROW = (85, 85, 85)
FLAME = (226, 137, 46)
MISSING_A = (0, 0, 0)
MISSING_B = (248, 0, 248)


@dataclass
class RecipeImage:
    recipe: Recipe
    path: Path            # absolute path written
    relative: str         # path relative to the assets dir, for the templates
    animated: bool
    frames: int


# Stack counts are drawn from these 5x7 glyphs, in the shape of Minecraft's own
# font, rather than from a system font. A system font would make the pixels
# depend on the machine (Segoe on Windows, DejaVu on a Linux runner), and a
# page rebuilt in CI would then rewrite every badge once per platform.
GLYPH_W, GLYPH_H = 5, 7
_DIGITS = {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": (".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "..#..", ".##.."),
}
COUNT_TEXT = (255, 255, 255)
COUNT_SHADOW = (63, 63, 63)


def _draw_count(draw: ImageDraw.ImageDraw, anchor_x: int, anchor_y: int,
                count: int, scale: int) -> None:
    """Draw ``count`` with its bottom-right corner at the logical pixel (anchor_x, anchor_y).

    Digits are 5x7 texture pixels with a one-pixel gap, drawn as ``scale``-sized
    blocks with a one-pixel drop shadow, the way the game draws stack sizes.
    """
    text = str(count)
    width = len(text) * (GLYPH_W + 1) - 1
    left = anchor_x - width           # the shadow lands on anchor_x itself
    top = anchor_y - GLYPH_H
    for dx, dy, colour in ((1, 1, COUNT_SHADOW), (0, 0, COUNT_TEXT)):
        for index, char in enumerate(text):
            glyph = _DIGITS.get(char)
            if glyph is None:
                continue
            origin_x = left + index * (GLYPH_W + 1) + dx
            for row, bits in enumerate(glyph):
                for col, bit in enumerate(bits):
                    if bit != "#":
                        continue
                    px = (origin_x + col) * scale
                    py = (top + row + dy) * scale
                    draw.rectangle([px, py, px + scale - 1, py + scale - 1], fill=colour)


def _missing_texture() -> Image.Image:
    image = Image.new("RGBA", (ITEM, ITEM), MISSING_A)
    draw = ImageDraw.Draw(image)
    half = ITEM // 2
    draw.rectangle([0, 0, half - 1, half - 1], fill=MISSING_B)
    draw.rectangle([half, half, ITEM - 1, ITEM - 1], fill=MISSING_B)
    return image


def _load_item(resolver: TextureResolver, item_id: str, cache: dict[str, Image.Image]):
    if item_id in cache:
        return cache[item_id]
    path = resolver.resolve(item_id)
    if path is None:
        image = _missing_texture()
    else:
        image = Image.open(path).convert("RGBA")
        # Animated textures ship as a vertical strip; take the first frame.
        if image.height > image.width and image.height % image.width == 0:
            image = image.crop((0, 0, image.width, image.width))
        if image.size != (ITEM, ITEM):
            image = image.resize((ITEM, ITEM), Image.NEAREST)
    cache[item_id] = image
    return image


def _draw_slot(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    draw.rectangle([x, y, x + size - 1, y + size - 1], fill=SLOT_FILL)
    draw.line([(x, y), (x + size - 1, y)], fill=SLOT_DARK)
    draw.line([(x, y), (x, y + size - 1)], fill=SLOT_DARK)
    draw.line([(x, y + size - 1), (x + size - 1, y + size - 1)], fill=SLOT_LIGHT)
    draw.line([(x + size - 1, y), (x + size - 1, y + size - 1)], fill=SLOT_LIGHT)


def _draw_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, cooking: bool) -> None:
    mid = y
    draw.rectangle([x, mid - 1, x + ARROW_W - 5, mid + 1], fill=ARROW)
    draw.polygon(
        [(x + ARROW_W - 6, mid - 4), (x + ARROW_W, mid), (x + ARROW_W - 6, mid + 4)],
        fill=ARROW,
    )
    if cooking:
        base = mid + 6
        draw.polygon(
            [(x + ARROW_W // 2, base), (x + ARROW_W // 2 - 3, base + 5),
             (x + ARROW_W // 2 + 3, base + 5)],
            fill=FLAME,
        )


class RecipeRenderer:
    def __init__(self, resolver: TextureResolver, *, scale: int = 3,
                 cycle_ms: int = 1000, max_frames: int = 8) -> None:
        self.resolver = resolver
        self.scale = max(1, int(scale))
        self.cycle_ms = int(cycle_ms)
        self.max_frames = max(1, int(max_frames))
        self._textures: dict[str, Image.Image] = {}

    # -- geometry ---------------------------------------------------------

    def _layout(self, recipe: Recipe) -> tuple[int, int, list[list[Ingredient | None]]]:
        grid = recipe.grid or [list(recipe.inputs)]
        rows = len(grid)
        cols = max(len(row) for row in grid)
        grid_w = cols * SLOT + (cols - 1) * GAP
        grid_h = rows * SLOT + (rows - 1) * GAP
        width = PAD + grid_w + ARROW_GAP + ARROW_W + ARROW_GAP + RESULT_SLOT + PAD
        height = PAD + max(grid_h, RESULT_SLOT) + PAD
        if recipe.kind == "cooking":
            height += 4  # room for the flame under the arrow
        return width, height, grid

    # -- one frame --------------------------------------------------------

    def _frame(self, recipe: Recipe, index: int) -> tuple[Image.Image, list[tuple[int, int, int]]]:
        width, height, grid = self._layout(recipe)
        card = Image.new("RGBA", (width, height), PANEL)
        draw = ImageDraw.Draw(card)
        counts: list[tuple[int, int, int]] = []  # (x, y, count) in logical px

        rows = len(grid)
        grid_h = rows * SLOT + (rows - 1) * GAP
        top = PAD + max(0, (RESULT_SLOT - grid_h) // 2)

        for r, row in enumerate(grid):
            for c, slot in enumerate(row):
                x = PAD + c * (SLOT + GAP)
                y = top + r * (SLOT + GAP)
                _draw_slot(draw, x, y, SLOT)
                if not slot or not slot.candidates:
                    continue
                item_id = slot.candidates[index % len(slot.candidates)]
                texture = _load_item(self.resolver, item_id, self._textures)
                card.alpha_composite(texture, (x + 1, y + 1))
                if slot.count > 1:
                    counts.append((x + SLOT - 1, y + SLOT - 1, slot.count))

        cols = max(len(row) for row in grid)
        grid_w = cols * SLOT + (cols - 1) * GAP
        arrow_x = PAD + grid_w + ARROW_GAP
        _draw_arrow(draw, arrow_x, PAD + max(grid_h, RESULT_SLOT) // 2,
                    recipe.kind == "cooking")

        result_x = arrow_x + ARROW_W + ARROW_GAP
        result_y = PAD + max(0, (max(grid_h, RESULT_SLOT) - RESULT_SLOT) // 2)
        _draw_slot(draw, result_x, result_y, RESULT_SLOT)
        result_id = (recipe.result.candidates[index % len(recipe.result.candidates)]
                     if recipe.result.candidates else "")
        result_texture = _load_item(self.resolver, result_id, self._textures)
        inset = (RESULT_SLOT - ITEM) // 2
        card.alpha_composite(result_texture, (result_x + inset, result_y + inset))
        if recipe.result_count > 1:
            counts.append((result_x + RESULT_SLOT - 2, result_y + RESULT_SLOT - 2,
                           recipe.result_count))

        return card, counts

    def _upscale(self, card: Image.Image, counts: list[tuple[int, int, int]]) -> Image.Image:
        big = card.resize(
            (card.width * self.scale, card.height * self.scale), Image.NEAREST
        ).convert("RGB")
        if not counts:
            return big
        draw = ImageDraw.Draw(big)
        for x, y, count in counts:
            _draw_count(draw, x, y, count, self.scale)
        return big

    # -- public -----------------------------------------------------------

    def render(self, recipe: Recipe, out_dir: Path, assets_dir: Path) -> RecipeImage:
        frame_count = 1
        if recipe.animated:
            frame_count = min(
                self.max_frames,
                max(len(slot.candidates) for slot in recipe.all_slots if slot.candidates),
            )

        images = [self._upscale(*self._frame(recipe, i)) for i in range(frame_count)]
        animated = len(images) > 1
        name = recipe.id.replace(":", "__").replace("/", "_")
        out_path = out_dir / f"{name}.{'gif' if animated else 'png'}"

        buffer = io.BytesIO()
        if animated:
            images[0].save(
                buffer, format="GIF", save_all=True, append_images=images[1:],
                duration=self.cycle_ms, loop=0, disposal=2, optimize=True,
            )
        else:
            images[0].save(buffer, format="PNG", optimize=True)

        payload = buffer.getvalue()
        out_dir.mkdir(parents=True, exist_ok=True)
        # Only touch the file when the picture changes, so git and --check stay
        # quiet. Comparing pixels rather than bytes matters: the same frames
        # encode a few bytes differently across Pillow builds (Windows vs the
        # manylinux wheels), and a byte comparison would have every CI run on a
        # new platform rewrite every image once.
        if not out_path.is_file() or not _same_picture(out_path.read_bytes(), payload):
            out_path.write_bytes(payload)

        # Drop a stale counterpart if a recipe switched between static and animated.
        other = out_dir / f"{name}.{'png' if animated else 'gif'}"
        if other.is_file():
            other.unlink()

        return RecipeImage(
            recipe=recipe,
            path=out_path,
            relative=out_path.relative_to(assets_dir).as_posix(),
            animated=animated,
            frames=len(images),
        )


def _frames(payload: bytes) -> list[tuple[bytes, int]]:
    """Every frame of an encoded image as raw RGBA bytes, with its duration."""
    with Image.open(io.BytesIO(payload)) as image:
        return [
            (frame.convert("RGBA").tobytes(), int(frame.info.get("duration", 0)))
            for frame in ImageSequence.Iterator(image)
        ]


def _same_picture(existing: bytes, fresh: bytes) -> bool:
    """True when two encoded images show the same frames for the same durations."""
    if existing == fresh:
        return True
    try:
        return _frames(existing) == _frames(fresh)
    except Exception:  # noqa: BLE001 - an unreadable file is simply not the same
        return False


def build_for(config, *, offline: bool = False) -> tuple[list[RecipeImage], list[str]]:
    """Discover this repo's recipes and render an image for each.

    Returns the images plus any warnings worth showing the user. Images land in
    ``<assets.dir>/<out>/`` so they are committed alongside the other art and
    resolve through ``assets.base_url`` on Modrinth and CurseForge.
    """
    from . import recipes as recipes_mod

    section = config.section("recipes")
    if section is None:
        return [], []

    options = section.data.get("options") or {}
    warnings: list[str] = []

    found, skipped = recipes_mod.discover(config.root, options, offline=offline)
    for recipe_type, count in sorted(skipped.items()):
        warnings.append(
            f"recipes: skipped {count} recipe(s) of unsupported type '{recipe_type}' "
            "-- add it under recipes.custom_types to draw them"
        )
    if not found:
        warnings.append("recipes: no drawable recipe JSON under the configured data paths")
        return [], warnings

    assets_dir = config.root / config.assets_dir
    out_dir = assets_dir / str(options.get("out", "recipes"))

    resolver = TextureResolver(
        config.root,
        asset_roots=options.get("asset_paths"),
        vanilla=str(options.get("vanilla", "auto")),
        offline=offline,
        overrides=options.get("icons"),
        assets_dir=config.assets_dir,
    )
    renderer = RecipeRenderer(
        resolver,
        scale=int(options.get("scale", 3) or 3),
        cycle_ms=int(options.get("cycle_ms", 1000) or 1000),
        max_frames=int(options.get("max_frames", 8) or 8),
    )

    images = [renderer.render(recipe, out_dir, assets_dir) for recipe in found]

    if resolver.misses:
        sample = ", ".join(sorted(resolver.misses)[:5])
        warnings.append(
            f"recipes: no texture for {len(resolver.misses)} item(s), drawn as "
            f"missing-texture ({sample})"
        )
    return images, warnings
