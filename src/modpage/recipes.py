"""Discover and parse a mod's recipe JSON into something renderable.

Handles the vanilla crafting/cooking/stonecutting/smithing types across the
JSON shapes Mojang has shipped: ``result`` as a bare id string, as
``{"item": ...}`` and as ``{"id": ...}``; ingredients as an object, a bare
string, or a list of alternatives.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .textures import TagResolver, split_id

DEFAULT_DATA_ROOTS = (
    "src/main/resources/data",
    "data",
    "common/src/main/resources/data",
    "fabric/src/main/resources/data",
    "neoforge/src/main/resources/data",
    "forge/src/main/resources/data",
    "quilt/src/main/resources/data",
)

CRAFTING = ("minecraft:crafting_shaped", "minecraft:crafting_shapeless")
COOKING = (
    "minecraft:smelting",
    "minecraft:blasting",
    "minecraft:smoking",
    "minecraft:campfire_cooking",
)
SINGLE_INPUT = ("minecraft:stonecutting",)
SMITHING = ("minecraft:smithing_transform", "minecraft:smithing_trim")

TYPE_LABELS = {
    "minecraft:crafting_shaped": "Crafting",
    "minecraft:crafting_shapeless": "Shapeless",
    "minecraft:smelting": "Smelting",
    "minecraft:blasting": "Blasting",
    "minecraft:smoking": "Smoking",
    "minecraft:campfire_cooking": "Campfire",
    "minecraft:stonecutting": "Stonecutting",
    "minecraft:smithing_transform": "Smithing",
    "minecraft:smithing_trim": "Smithing (trim)",
}


def pretty_name(item_id: str) -> str:
    _, path = split_id(item_id)
    return path.rsplit("/", 1)[-1].replace("_", " ").title()


@dataclass
class Ingredient:
    """One slot: a single item, or several that a viewer would cycle through."""

    candidates: list[str]
    label: str
    is_tag: bool = False
    count: int = 1

    @property
    def animated(self) -> bool:
        return len(self.candidates) > 1


@dataclass
class Recipe:
    id: str
    type: str
    source: Path
    result: Ingredient
    result_count: int
    grid: list[list[Ingredient | None]] = field(default_factory=list)
    inputs: list[Ingredient] = field(default_factory=list)
    shapeless: bool = False
    label: str = ""  # caption; set by _assign_labels once the whole set is known

    @property
    def kind(self) -> str:
        if self.type in CRAFTING:
            return "crafting"
        if self.type in COOKING:
            return "cooking"
        if self.type in SMITHING:
            return "smithing"
        return "single"

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.type, self.type.split(":")[-1].replace("_", " ").title())

    @property
    def name(self) -> str:
        return pretty_name(self.result.candidates[0]) if self.result.candidates else self.id

    @property
    def display(self) -> str:
        return self.label or self.name

    @property
    def animated(self) -> bool:
        return any(slot.animated for slot in self.all_slots)

    @property
    def all_slots(self) -> list[Ingredient]:
        flat = [slot for row in self.grid for slot in row if slot]
        return flat + self.inputs + [self.result]


class RecipeParser:
    def __init__(self, tags: TagResolver, *, max_candidates: int = 8,
                 custom_types: dict[str, Any] | None = None) -> None:
        self.tags = tags
        self.max_candidates = max_candidates
        self.custom_types = {str(k): (v or {}) for k, v in (custom_types or {}).items()}
        self.skipped: dict[str, int] = {}  # recipe type -> count we could not draw

    def ingredient(self, value: Any) -> Ingredient | None:
        """Normalise every ingredient shape Mojang has used into one slot."""
        if value is None:
            return None

        if isinstance(value, str):
            if value.startswith("#"):
                items = self.tags.resolve(value)[: self.max_candidates]
                return Ingredient(items, pretty_name(value), is_tag=True)
            return Ingredient([value], pretty_name(value))

        if isinstance(value, dict):
            count = int(value.get("count", 1) or 1)
            if "tag" in value:
                tag = str(value["tag"])
                items = self.tags.resolve(tag)[: self.max_candidates]
                return Ingredient(items, pretty_name(tag), is_tag=True, count=count)
            single = value.get("item") or value.get("id")
            if isinstance(single, str):
                return Ingredient([single], pretty_name(single), count=count)
            # 1.21.2+: {"items": ["a", "b"]}
            listed = value.get("items")
            if isinstance(listed, list):
                merged = self.ingredient(listed)
                if merged:
                    merged.count = count
                return merged
            return None

        if isinstance(value, list):
            candidates: list[str] = []
            labels: list[str] = []
            for entry in value:
                part = self.ingredient(entry)
                if not part:
                    continue
                candidates.extend(part.candidates)
                labels.append(part.label)
            candidates = list(dict.fromkeys(candidates))[: self.max_candidates]
            if not candidates:
                return None
            label = labels[0] if len(labels) == 1 else " / ".join(labels[:3])
            return Ingredient(candidates, label, is_tag=len(candidates) > 1)

        return None

    def result(self, data: dict[str, Any]) -> tuple[Ingredient, int] | None:
        raw = data.get("result")
        if isinstance(raw, str):
            return Ingredient([raw], pretty_name(raw)), int(data.get("count", 1) or 1)
        if isinstance(raw, dict):
            item = raw.get("id") or raw.get("item")
            if isinstance(item, str):
                return Ingredient([item], pretty_name(item)), int(raw.get("count", 1) or 1)
        return None

    def _layout_for(self, recipe_type: str) -> str | None:
        if recipe_type == "minecraft:crafting_shaped":
            return "shaped"
        if recipe_type == "minecraft:crafting_shapeless":
            return "shapeless"
        if recipe_type in COOKING or recipe_type in SINGLE_INPUT:
            return "single"
        if recipe_type in SMITHING:
            return "smithing"
        custom = self.custom_types.get(recipe_type)
        if custom:
            return str(custom.get("layout", "smithing"))
        return None

    def parse(self, path: Path, namespace: str) -> Recipe | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None

        recipe_type = str(data.get("type", ""))
        if ":" not in recipe_type:
            recipe_type = f"minecraft:{recipe_type}"
        layout = self._layout_for(recipe_type)
        if layout is None:
            self.skipped[recipe_type] = self.skipped.get(recipe_type, 0) + 1
            return None

        grid: list[list[Ingredient | None]] = []
        inputs: list[Ingredient] = []
        shapeless = False

        if layout == "shaped":
            grid = self._shaped_grid(data)
        elif layout == "shapeless":
            slots = [self.ingredient(entry) for entry in data.get("ingredients", [])]
            grid = self._pack([slot for slot in slots if slot])
            shapeless = True
        elif layout == "single":
            slot = self.ingredient(data.get("ingredient"))
            inputs = [slot] if slot else []
        elif layout == "smithing":
            for key in ("template", "base", "addition"):
                slot = self.ingredient(data.get(key))
                if slot:
                    inputs.append(slot)
        if not grid and not inputs:
            return None

        result = self.result(data)
        if result is None:
            # A modded recipe may compute its result in code. `custom_types` can
            # say which input to show instead (e.g. "the base item, decorated").
            result = self._custom_result(recipe_type, inputs, data)
        if result is None:
            self.skipped[recipe_type] = self.skipped.get(recipe_type, 0) + 1
            return None

        return Recipe(
            id=f"{namespace}:{path.stem}",
            type=recipe_type,
            source=path,
            result=result[0],
            result_count=result[1],
            grid=grid,
            inputs=inputs,
            shapeless=shapeless,
        )

    def _custom_result(self, recipe_type: str, inputs: list[Ingredient],
                       data: dict[str, Any]) -> tuple[Ingredient, int] | None:
        custom = self.custom_types.get(recipe_type) or {}
        spec = custom.get("result")
        if not spec:
            return None
        # Name one of the smithing keys, and the result mirrors that slot --
        # cycling in step with it when it is a tag.
        if spec in ("template", "base", "addition"):
            slot = self.ingredient(data.get(spec))
            return (slot, 1) if slot else None
        return Ingredient([str(spec)], pretty_name(str(spec))), 1

    def _shaped_grid(self, data: dict[str, Any]) -> list[list[Ingredient | None]]:
        pattern = [str(row) for row in data.get("pattern", [])]
        keys = data.get("key") or {}
        if not pattern:
            return []
        width = max(len(row) for row in pattern)
        grid: list[list[Ingredient | None]] = []
        for row in pattern:
            padded = row.ljust(width)
            grid.append([
                None if char == " " else self.ingredient(keys.get(char))
                for char in padded
            ])
        return self._trim(grid)

    @staticmethod
    def _trim(grid: list[list[Ingredient | None]]) -> list[list[Ingredient | None]]:
        """Shrink to the filled bounding box -- a 1x2 recipe draws 1x2, not 3x3."""
        rows = [i for i, row in enumerate(grid) if any(row)]
        cols = [j for j in range(len(grid[0])) if any(row[j] for row in grid)]
        if not rows or not cols:
            return []
        return [
            [grid[i][j] for j in range(cols[0], cols[-1] + 1)]
            for i in range(rows[0], rows[-1] + 1)
        ]

    @staticmethod
    def _pack(slots: list[Ingredient]) -> list[list[Ingredient | None]]:
        """Lay shapeless ingredients out in the smallest sensible box."""
        count = len(slots)
        width = 1 if count == 1 else (2 if count <= 4 else 3)
        rows: list[list[Ingredient | None]] = []
        for start in range(0, count, width):
            row: list[Ingredient | None] = list(slots[start:start + width])
            row += [None] * (width - len(row))
            rows.append(row)
        return rows


def data_roots(root: Path, configured: list[str] | None) -> list[Path]:
    candidates = configured or list(DEFAULT_DATA_ROOTS)
    return [root / p for p in candidates if (root / p).is_dir()]


def _common_token_prefix(stems: list[str]) -> str:
    """The leading ``foo_`` that every one of these file names shares."""
    if len(stems) < 2:
        return ""
    split = [stem.split("_") for stem in stems]
    shared: list[str] = []
    for index in range(min(len(tokens) for tokens in split) - 1):
        token = split[0][index]
        if all(tokens[index] == token for tokens in split):
            shared.append(token)
        else:
            break
    return "_".join(shared) + "_" if shared else ""


def _assign_labels(recipes: list[Recipe], overrides: dict[str, Any] | None = None) -> None:
    """Caption each card from its file name, minus the prefix they all share.

    Result item names read nicely but collide constantly -- one mod makes the
    same template from five recipes, another decorates the same armor twelve
    ways. File names are unique by construction, so they caption unambiguously.
    Set ``recipes.labels: {<recipe id>: "Name"}`` to override any of them.
    """
    named = {str(k): str(v) for k, v in (overrides or {}).items()}
    prefix = _common_token_prefix([recipe.source.stem for recipe in recipes])
    for recipe in recipes:
        if recipe.id in named:
            recipe.label = named[recipe.id]
            continue
        trimmed = recipe.source.stem[len(prefix):] if prefix else recipe.source.stem
        recipe.label = trimmed.replace("_", " ").title() or recipe.name


def discover(root: Path, options: dict[str, Any], *,
             offline: bool = False) -> tuple[list[Recipe], dict[str, int]]:
    """Find and parse every recipe file under the configured data roots.

    Returns the recipes plus a count of the types that could not be drawn.
    """
    roots = data_roots(root, options.get("paths"))
    if not roots:
        return [], {}

    tags = TagResolver(root, roots, offline=offline)
    parser = RecipeParser(
        tags,
        max_candidates=int(options.get("max_frames", 8) or 8),
        custom_types=options.get("custom_types"),
    )
    includes = options.get("include") or []
    excludes = options.get("exclude") or []

    recipes: list[Recipe] = []
    seen: set[str] = set()
    for data_root in roots:
        for namespace_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
            namespace = namespace_dir.name
            for folder in ("recipe", "recipes"):  # 1.21+ singular, older plural
                for path in sorted((namespace_dir / folder).rglob("*.json")):
                    recipe = parser.parse(path, namespace)
                    if not recipe or recipe.id in seen:
                        continue
                    if includes and not any(fnmatch.fnmatch(recipe.id, p) for p in includes):
                        continue
                    if any(fnmatch.fnmatch(recipe.id, p) for p in excludes):
                        continue
                    seen.add(recipe.id)
                    recipes.append(recipe)

    _assign_labels(recipes, options.get("labels"))
    recipes.sort(key=lambda r: (r.display, r.id))
    explicit = options.get("order")
    if explicit:
        rank = {str(name): i for i, name in enumerate(explicit)}
        recipes.sort(key=lambda r: rank.get(r.id, rank.get(r.display, len(rank))))
    return recipes, parser.skipped
