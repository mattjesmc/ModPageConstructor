"""Find a 16x16 texture for an item id, from the mod's own assets or vanilla.

Mod textures come out of the repo. Vanilla textures are pulled once from
misode/mcmeta (a version-controlled mirror of Mojang's generated assets) and
cached under ``.modpage/cache``, so later builds are offline and instant.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

MCMETA_ASSETS = "https://raw.githubusercontent.com/misode/mcmeta/assets/assets"
MCMETA_DATA = "https://raw.githubusercontent.com/misode/mcmeta/data/data"

# Where a texture reference can live inside a block model, best guess first.
MODEL_TEXTURE_KEYS = ("layer0", "all", "texture", "up", "side", "front", "top", "particle")

DEFAULT_ASSET_ROOTS = (
    "src/main/resources/assets",
    "assets",
    "common/src/main/resources/assets",
    "fabric/src/main/resources/assets",
    "neoforge/src/main/resources/assets",
    "forge/src/main/resources/assets",
    "quilt/src/main/resources/assets",
)


def split_id(item_id: str) -> tuple[str, str]:
    namespace, _, path = str(item_id).lstrip("#").partition(":")
    return (namespace, path) if path else ("minecraft", namespace)


class TextureResolver:
    """Resolves ``namespace:item`` to a PNG on disk, or ``None``."""

    def __init__(self, root: Path, *, asset_roots: list[str] | None = None,
                 cache_dir: Path | None = None, vanilla: str = "auto",
                 offline: bool = False, overrides: dict[str, str] | None = None,
                 assets_dir: str = "assets") -> None:
        self.root = root
        # Escape hatch for items with no flat texture (shields, banners, blocks
        # whose icon is a 3D render): point the id at a PNG in the assets dir.
        self.overrides = {
            str(k): (root / v if Path(v).is_absolute() else root / assets_dir / v)
            for k, v in (overrides or {}).items()
        }
        self.asset_roots = [root / p for p in (asset_roots or DEFAULT_ASSET_ROOTS)]
        self.asset_roots = [p for p in self.asset_roots if p.is_dir()]
        self.cache_dir = cache_dir or (root / ".modpage" / "cache")
        self.vanilla = vanilla
        self.offline = offline
        self.local_vanilla: Path | None = None
        if vanilla not in ("auto", "off"):
            candidate = Path(vanilla)
            self.local_vanilla = candidate if candidate.is_absolute() else root / candidate
        self._cache: dict[str, Path | None] = {}
        self.misses: set[str] = set()

    # -- assets in the mod repo -------------------------------------------

    def _asset_file(self, namespace: str, relative: str) -> Path | None:
        for asset_root in self.asset_roots:
            candidate = asset_root / namespace / relative
            if candidate.is_file():
                return candidate
        return None

    def _texture_from_model(self, namespace: str, path: str) -> Path | None:
        """Follow item/block model JSON to the texture it actually points at."""
        for kind in ("item", "block"):
            model = self._asset_file(namespace, f"models/{kind}/{path}.json")
            if not model:
                continue
            try:
                data = json.loads(model.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            textures = data.get("textures") or {}
            for key in MODEL_TEXTURE_KEYS:
                reference = textures.get(key)
                if isinstance(reference, str) and not reference.startswith("#"):
                    ref_ns, ref_path = split_id(reference)
                    found = self._asset_file(ref_ns, f"textures/{ref_path}.png")
                    if found:
                        return found
        return None

    # -- vanilla, cached --------------------------------------------------

    def _vanilla_texture(self, path: str) -> Path | None:
        if self.local_vanilla:
            for kind in ("item", "block"):
                candidate = self.local_vanilla / "minecraft" / "textures" / kind / f"{path}.png"
                if candidate.is_file():
                    return candidate
            return None
        if self.vanilla == "off":
            return None

        for kind in ("item", "block"):
            cached = self.cache_dir / "minecraft" / kind / f"{path}.png"
            if cached.is_file():
                return cached
        if self.offline:
            return None

        for kind in ("item", "block"):
            cached = self.cache_dir / "minecraft" / kind / f"{path}.png"
            try:
                with urllib.request.urlopen(
                    f"{MCMETA_ASSETS}/minecraft/textures/{kind}/{path}.png", timeout=20
                ) as response:
                    payload = response.read()
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(payload)
            return cached
        return None

    # -- public -----------------------------------------------------------

    def resolve(self, item_id: str) -> Path | None:
        if item_id in self._cache:
            return self._cache[item_id]

        override = self.overrides.get(item_id)
        if override and override.is_file():
            self._cache[item_id] = override
            return override

        namespace, path = split_id(item_id)
        found = (
            self._texture_from_model(namespace, path)
            or self._asset_file(namespace, f"textures/item/{path}.png")
            or self._asset_file(namespace, f"textures/block/{path}.png")
        )
        if not found and namespace == "minecraft":
            found = self._vanilla_texture(path)
        if not found:
            self.misses.add(item_id)
        self._cache[item_id] = found
        return found


class TagResolver:
    """Expands ``#namespace:tag`` into the item ids it contains."""

    def __init__(self, root: Path, data_roots: list[Path], *,
                 cache_dir: Path | None = None, offline: bool = False) -> None:
        self.root = root
        self.data_roots = data_roots
        self.cache_dir = cache_dir or (root / ".modpage" / "cache")
        self.offline = offline
        self._cache: dict[str, list[str]] = {}
        self.unresolved: set[str] = set()

    def _local_tag(self, namespace: str, path: str) -> dict | None:
        # 1.21+ uses tags/item, older packs use tags/items.
        for folder in ("item", "items"):
            for data_root in self.data_roots:
                candidate = data_root / namespace / "tags" / folder / f"{path}.json"
                if candidate.is_file():
                    try:
                        return json.loads(candidate.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        return None
        return None

    def _vanilla_tag(self, namespace: str, path: str) -> dict | None:
        cached = self.cache_dir / "tags" / namespace / f"{path}.json"
        if cached.is_file():
            try:
                return json.loads(cached.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        if self.offline:
            return None
        try:
            with urllib.request.urlopen(
                f"{MCMETA_DATA}/{namespace}/tags/item/{path}.json", timeout=20
            ) as response:
                payload = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(payload)
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def resolve(self, tag_id: str, _seen: set[str] | None = None) -> list[str]:
        tag_id = tag_id.lstrip("#")
        if tag_id in self._cache:
            return self._cache[tag_id]
        seen = _seen or set()
        if tag_id in seen:
            return []
        seen.add(tag_id)

        namespace, path = split_id(tag_id)
        data = self._local_tag(namespace, path)
        if data is None and namespace == "minecraft":
            data = self._vanilla_tag(namespace, path)
        if data is None:
            self.unresolved.add(tag_id)
            self._cache[tag_id] = []
            return []

        items: list[str] = []
        for entry in data.get("values", []):
            value = entry.get("id") if isinstance(entry, dict) else entry
            if not isinstance(value, str):
                continue
            if value.startswith("#"):
                items.extend(self.resolve(value, seen))
            else:
                items.append(value)
        # Preserve order, drop duplicates.
        deduped = list(dict.fromkeys(items))
        self._cache[tag_id] = deduped
        return deduped
