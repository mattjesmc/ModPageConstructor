"""Load and normalise a ``modpage.yml`` into the context the templates render."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import generators as generators_mod

# Every page shares the same skeleton. Sections listed here render in this order;
# the ones in ALWAYS_RENDER appear on every page even when empty, so that
# "Dependencies" and "Incompatibilities" are a guaranteed banner + answer rather
# than something a reader has to hunt for.
CANONICAL_SECTIONS: list[tuple[str, str]] = [
    ("about", "About"),
    ("features", "Features"),
    ("gallery", "Gallery"),
    ("recipes", "Recipes"),
    ("dependencies", "Dependencies"),
    ("incompatibilities", "Incompatibilities"),
    ("installation", "Installation"),
    ("configuration", "Configuration"),
    ("changelog", "Changelog"),
    ("faq", "FAQ"),
    ("credits", "Credits"),
    ("license", "License"),
]
ALWAYS_RENDER = {"dependencies", "incompatibilities"}
# Rendered whenever the key appears in `sections:`, even with no content of its
# own -- the content is discovered from the repo at build time.
OPT_IN_SECTIONS = {"recipes"}

# The contents list is not a section -- it has no body and is not reorderable --
# but it borrows the section conventions: an id, a title, and an auto-discovered
# banner at assets/banners/contents.png.
TOC_ID = "contents"
TOC_TITLE = "Contents"
TOC_STYLES = ("list", "inline")

BANNER_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg")

# How a section renders a list of generated elements. Every target understands
# all of them; `slider` is a gallery everywhere Markdown is all there is.
LAYOUTS = ("list", "cards", "table", "gallery", "slider", "changelog", "definition")
DEFAULT_LAYOUTS = {"changelog": "changelog", "gallery": "gallery"}
# Keys a section understands itself; everything else it carries is passed to the
# layout as `section.options` (table columns, image widths, fold thresholds).
SECTION_KEYS = frozenset({
    "id", "title", "banner", "body", "targets", "empty_text", "always", "after",
    "layout", "elements", "entries", "items", "images", "required", "optional",
    "bundled", "known",
})

# Display names for the link row; anything unlisted is title-cased.
LINK_LABELS = {
    "github": "GitHub",
    "modrinth": "Modrinth",
    "curseforge": "CurseForge",
    "issues": "Issues",
    "discord": "Discord",
    "wiki": "Wiki",
    "docs": "Docs",
    "changelog": "Changelog",
    "website": "Website",
    "youtube": "YouTube",
    "kofi": "Ko-fi",
    "ko_fi": "Ko-fi",
    "patreon": "Patreon",
}

DEFAULT_EMPTY_TEXT = {
    "dependencies": "**None.** This mod is standalone — no other mods are required.",
    "incompatibilities": "**None known.** No conflicts have been reported.",
    "recipes": "_No recipes found in this repo's data files._",
}


class ConfigError(Exception):
    """Raised for a config a human needs to fix; the CLI prints it verbatim."""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _normalise_named(entries: Any, *, name_key: str = "name") -> list[dict[str, Any]]:
    """Accept ``- Fabric API`` or ``- {name: Fabric API, url: ...}`` alike."""
    out: list[dict[str, Any]] = []
    for entry in _as_list(entries):
        if isinstance(entry, str):
            out.append({name_key: entry})
        elif isinstance(entry, dict):
            item = dict(entry)
            if name_key not in item:
                raise ConfigError(f"list entry {entry!r} is missing a '{name_key}' key")
            out.append(item)
        else:
            raise ConfigError(f"unsupported list entry: {entry!r}")
    return out


def _normalise_features(entries: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in _as_list(entries):
        if isinstance(entry, str):
            out.append({"title": entry, "description": None})
        elif isinstance(entry, dict):
            item = dict(entry)
            item.setdefault("title", item.pop("name", None))
            item.setdefault("description", item.pop("body", None))
            if not item.get("title") and not item.get("description"):
                raise ConfigError(f"feature {entry!r} needs a title or description")
            out.append(item)
        else:
            raise ConfigError(f"unsupported feature entry: {entry!r}")
    return out


def _normalise_images(entries: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in _as_list(entries):
        if isinstance(entry, str):
            out.append({"src": entry, "caption": None, "alt": None})
        elif isinstance(entry, dict):
            item = dict(entry)
            if "src" not in item:
                raise ConfigError(f"gallery image {entry!r} is missing 'src'")
            item.setdefault("caption", None)
            item.setdefault("alt", item.get("caption"))
            out.append(item)
        else:
            raise ConfigError(f"unsupported gallery entry: {entry!r}")
    return out


def _normalise_faq(entries: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in _as_list(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"faq entry must be a mapping, got {entry!r}")
        question = entry.get("q") or entry.get("question")
        answer = entry.get("a") or entry.get("answer")
        if not question or not answer:
            raise ConfigError(f"faq entry {entry!r} needs both a question and an answer")
        out.append({"question": str(question), "answer": str(answer)})
    return out


def _normalise_columns(spec: Any) -> list[dict[str, str]]:
    """``columns: [version, date]`` or ``[{field: date, title: Shipped}]``."""
    columns: list[dict[str, str]] = []
    for entry in _as_list(spec):
        if isinstance(entry, str):
            columns.append({"field": entry, "title": entry.replace("_", " ").title()})
        elif isinstance(entry, dict):
            name = entry.get("field") or entry.get("key") or entry.get("name")
            if not name:
                raise ConfigError(f"table column {entry!r} needs a 'field'")
            columns.append({
                "field": str(name),
                "title": str(entry.get("title") or str(name).replace("_", " ").title()),
            })
        else:
            raise ConfigError(f"unsupported table column: {entry!r}")
    return columns or [{"field": "title", "title": "Name"},
                       {"field": "description", "title": "Details"}]


def _normalise_elements(entries: Any) -> list[dict[str, Any]]:
    """Elements are whatever a generator produced; give them the keys templates read.

    A generator is free to name its fields after its own subject -- a tag has a
    ``version``, a commit has a ``subject`` -- so the conventional ``title`` and
    ``description`` are filled in from whichever of those is present rather than
    demanded of every generator.
    """
    out: list[dict[str, Any]] = []
    for entry in _as_list(entries):
        if isinstance(entry, str):
            out.append({"title": entry, "description": None})
            continue
        if not isinstance(entry, dict):
            raise ConfigError(f"element {entry!r} must be a mapping or a string")
        item = dict(entry)
        for key, sources in (("title", ("name", "version", "question", "heading")),
                             ("description", ("body", "summary", "subject", "answer",
                                              "caption", "note"))):
            if not item.get(key):
                for source in sources:
                    if item.get(source):
                        item[key] = item[source]
                        break
        item.setdefault("title", None)
        item.setdefault("description", None)
        if not any((item.get("title"), item.get("description"), item.get("image"),
                    item.get("src"), item.get("items"))):
            raise ConfigError(
                f"element {entry!r} has nothing to show -- give it a title, a "
                "description, an image, or nested items"
            )
        out.append(item)
    return out


@dataclass
class Section:
    id: str
    title: str
    banner: str | None = None
    body: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    empty_text: str | None = None
    targets: list[str] | None = None  # None = every target
    #: How ``data['elements']`` is drawn; see :data:`LAYOUTS`.
    layout: str = "list"
    #: Extra per-section settings a layout reads (table columns, image widths).
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.body and not any(self.data.values())


@dataclass
class Config:
    root: Path
    raw: dict[str, Any]
    name: str
    slug: str
    tagline: str | None
    authors: list[str]
    assets_dir: str
    assets_base_url: str | None
    header: dict[str, Any]
    links: dict[str, str]
    minecraft: dict[str, Any]
    badges: list[dict[str, str]]
    sections: list[Section]
    outputs: dict[str, str]
    template: str
    footer: str | None
    #: ``None`` when the config asks for no contents list.
    toc: dict[str, Any] | None
    #: Every declared generator's elements, keyed by name, for templates that
    #: want a list the shared skeleton has no section for.
    generated: dict[str, list[Any]] = field(default_factory=dict)
    #: Warnings raised while loading (a generator that found nothing, say);
    #: the CLI prints these alongside the per-target render warnings.
    warnings: list[str] = field(default_factory=list)

    @property
    def link_items(self) -> list[dict[str, str]]:
        """The header link row: every link except the licence URL, nicely named."""
        return [
            {"label": LINK_LABELS.get(key, key.replace("_", " ").title()), "url": url}
            for key, url in self.links.items()
            if key != "license"
        ]

    def section(self, section_id: str) -> Section | None:
        for section in self.sections:
            if section.id == section_id:
                return section
        return None


def _find_banner(root: Path, assets_dir: str, banner_dir: str, section_id: str) -> str | None:
    """Auto-discover ``assets/banners/<section>.png`` so configs stay short."""
    base = root / assets_dir / banner_dir
    for ext in BANNER_EXTS:
        if (base / f"{section_id}{ext}").is_file():
            return f"{banner_dir}/{section_id}{ext}"
    return None


def _shield(label: str, message: str, colour: str, style: str) -> str:
    def esc(text: str) -> str:
        return str(text).replace("_", "__").replace("-", "--").replace(" ", "_")

    return f"https://img.shields.io/badge/{esc(label)}-{esc(message)}-{colour}?style={style}"


def _build_badges(raw: dict[str, Any], links: dict[str, str], minecraft: dict[str, Any],
                  slug: str, license_name: str | None) -> list[dict[str, str]]:
    """Turn the badge shorthand into concrete shields.io (or custom) badges."""
    cfg = raw.get("badges")
    if cfg is False:
        return []
    cfg = cfg or {}
    style = cfg.get("style", "for-the-badge")
    colour = str(cfg.get("color", "5b21b6")).lstrip("#")
    requested = cfg.get("show")
    if requested is None:
        requested = ["modrinth", "curseforge", "github", "loaders", "versions", "license"]

    badges: list[dict[str, str]] = []
    for key in requested:
        if key == "modrinth" and links.get("modrinth"):
            badges.append({
                "alt": "Modrinth",
                "image": (f"https://img.shields.io/modrinth/dt/{slug}?style={style}"
                          "&logo=modrinth&logoColor=white&label=Modrinth&color=00AF5C"),
                "url": links["modrinth"],
            })
        elif key == "curseforge" and links.get("curseforge"):
            badges.append({
                "alt": "CurseForge",
                "image": (f"https://img.shields.io/badge/CurseForge-Download-F16436?style={style}"
                          "&logo=curseforge&logoColor=white"),
                "url": links["curseforge"],
            })
        elif key == "github" and links.get("github"):
            repo = links["github"].rstrip("/").removeprefix("https://github.com/")
            badges.append({
                "alt": "GitHub release",
                "image": (f"https://img.shields.io/github/v/release/{repo}?style={style}"
                          f"&logo=github&logoColor=white&label=Release&color={colour}"),
                "url": links["github"].rstrip("/") + "/releases/latest",
            })
        elif key == "loaders" and minecraft.get("loaders"):
            badges.append({
                "alt": "Loaders",
                "image": _shield("Loader", " | ".join(minecraft["loaders"]), colour, style),
                "url": links.get("modrinth", ""),
            })
        elif key == "versions" and minecraft.get("versions"):
            badges.append({
                "alt": "Minecraft versions",
                "image": _shield("Minecraft", " | ".join(minecraft["versions"]), colour, style),
                "url": links.get("modrinth", ""),
            })
        elif key == "license" and license_name:
            badges.append({
                "alt": "License",
                "image": _shield("License", str(license_name), colour, style),
                "url": links.get("license", ""),
            })
        elif key == "discord" and links.get("discord"):
            badges.append({
                "alt": "Discord",
                "image": (f"https://img.shields.io/badge/Discord-Join-5865F2?style={style}"
                          "&logo=discord&logoColor=white"),
                "url": links["discord"],
            })

    for extra in _as_list(cfg.get("extra")):
        if not isinstance(extra, dict) or "image" not in extra:
            raise ConfigError(f"badges.extra entry {extra!r} needs at least an 'image'")
        badges.append({
            "alt": extra.get("alt") or extra.get("label") or "Badge",
            "image": extra["image"],
            "url": extra.get("url", ""),
        })
    return badges


def _build_toc(raw: dict[str, Any], root: Path, assets_dir: str,
               banner_dir: str) -> dict[str, Any] | None:
    """Normalise the optional ``toc:`` block; ``None`` means "no contents list"."""
    cfg = raw.get("toc")
    if cfg is None or cfg is False:
        return None
    if cfg is True:
        cfg = {}
    elif isinstance(cfg, str):  # `toc: Jump to` shorthand
        cfg = {"title": cfg}
    if not isinstance(cfg, dict):
        raise ConfigError("'toc' must be true, false, a title string, or a mapping")

    style = str(cfg.get("style", "list")).lower()
    if style not in TOC_STYLES:
        raise ConfigError(f"toc.style must be one of {', '.join(TOC_STYLES)}, got '{style}'")

    sid = str(cfg.get("id") or TOC_ID)
    title = cfg.get("title", TOC_TITLE)
    try:
        min_sections = int(cfg.get("min_sections", 2))
    except (TypeError, ValueError):
        raise ConfigError(f"toc.min_sections must be a number, got {cfg['min_sections']!r}") from None

    return {
        "id": sid,
        "title": None if title is None or title is False else str(title),
        "style": style,
        "numbered": bool(cfg.get("numbered", False)),
        "banner": cfg.get("banner") or _find_banner(root, assets_dir, banner_dir, sid),
        "skip": [str(entry) for entry in _as_list(cfg.get("skip"))],
        "min_sections": min_sections,
        "targets": [str(t) for t in _as_list(cfg["targets"])] if cfg.get("targets") else None,
    }


def _build_sections(raw: dict[str, Any], root: Path, assets_dir: str, banner_dir: str,
                    license_name: str | None) -> list[Section]:
    declared = raw.get("sections") or {}
    if not isinstance(declared, dict):
        raise ConfigError("'sections' must be a mapping of section id -> settings")

    titles = dict(CANONICAL_SECTIONS)
    order = [sid for sid, _ in CANONICAL_SECTIONS]

    # Custom sections are spliced into the canonical order via `after:`.
    custom_by_id: dict[str, dict[str, Any]] = {}
    for entry in _as_list(raw.get("custom_sections")):
        if not isinstance(entry, dict) or "title" not in entry:
            raise ConfigError(f"custom_sections entry {entry!r} needs a 'title'")
        sid = str(entry.get("id") or entry["title"]).lower().replace(" ", "-")
        custom_by_id[sid] = {**entry, "id": sid}
        titles[sid] = entry["title"]
        anchor = entry.get("after")
        if anchor and anchor in order:
            order.insert(order.index(anchor) + 1, sid)
        else:
            order.append(sid)

    if raw.get("order"):
        explicit = [str(sid) for sid in raw["order"]]
        unknown = [sid for sid in explicit if sid not in titles]
        if unknown:
            raise ConfigError(f"'order' references unknown sections: {', '.join(unknown)}")
        missing = [sid for sid in sorted(ALWAYS_RENDER) if sid not in explicit]
        if missing:
            raise ConfigError(
                f"'order' must include the shared section(s): {', '.join(missing)}"
            )
        order = explicit

    sections: list[Section] = []
    for sid in order:
        cfg = declared.get(sid)
        if cfg is False:
            if sid in ALWAYS_RENDER:
                raise ConfigError(
                    f"'{sid}' is a shared section and cannot be disabled; leave it empty instead"
                )
            continue
        if cfg is None:
            cfg = custom_by_id.get(sid, {})
        if isinstance(cfg, str):  # `about: "text"` shorthand
            cfg = {"body": cfg}
        if not isinstance(cfg, dict):
            raise ConfigError(f"section '{sid}' must be a mapping, a string, or false")

        data: dict[str, Any] = {}
        if sid == "dependencies":
            data = {
                "required": _normalise_named(cfg.get("required")),
                "optional": _normalise_named(cfg.get("optional")),
                "bundled": _normalise_named(cfg.get("bundled")),
            }
        elif sid == "incompatibilities":
            data = {"known": _normalise_named(cfg.get("known") or cfg.get("items"))}
        elif sid == "features":
            data = {"items": _normalise_features(cfg.get("items"))}
        elif sid == "gallery":
            data = {"images": _normalise_images(cfg.get("images") or cfg.get("items"))}
        elif sid == "faq":
            data = {"items": _normalise_faq(cfg.get("items"))}
        elif sid == "recipes":
            # `images` is filled in by the recipe build step before rendering.
            data = {"images": [], "options": {k: v for k, v in cfg.items()
                                              if k not in ("title", "banner", "body")}}

        # Any section may carry a list of elements -- usually a generator's
        # output, spliced in by `elements: {from: <generator>}` -- drawn by the
        # layout rather than by a macro written for that one section.
        elements = cfg.get("elements", cfg.get("entries"))
        if elements is not None:
            data["elements"] = _normalise_elements(elements)
        layout = str(cfg.get("layout") or DEFAULT_LAYOUTS.get(sid, "list")).lower()
        if layout not in LAYOUTS:
            raise ConfigError(
                f"section '{sid}': layout must be one of {', '.join(LAYOUTS)}, got '{layout}'"
            )
        if layout == "table":
            columns = _normalise_columns(cfg.get("columns"))
            # Headings alone are not content; without rows the section is empty
            # and is skipped like any other, rather than drawing a bare header.
            if data.get("elements"):
                data["columns"] = columns

        body = cfg.get("body")
        if sid == "license" and not body and license_name:
            body = f"Released under the **{license_name}** license."

        section = Section(
            id=sid,
            title=str(cfg.get("title") or titles.get(sid, sid.replace("-", " ").title())),
            banner=cfg.get("banner") or _find_banner(root, assets_dir, banner_dir, sid),
            body=body.rstrip() if isinstance(body, str) else None,
            data=data,
            empty_text=cfg.get("empty_text") or DEFAULT_EMPTY_TEXT.get(sid),
            targets=[str(t) for t in _as_list(cfg["targets"])] if cfg.get("targets") else None,
            layout=layout,
            options={k: v for k, v in cfg.items() if k not in SECTION_KEYS},
        )
        opted_in = sid in OPT_IN_SECTIONS and sid in declared
        if section.is_empty and sid not in ALWAYS_RENDER and not opted_in                 and not cfg.get("always"):
            continue
        sections.append(section)
    return sections


def load(path: Path, *, run_generators: bool = True) -> Config:
    """Read one ``modpage.yml``; ``run_generators=False`` leaves references empty."""
    if not path.is_file():
        raise ConfigError(f"no config at {path}. Run 'modpage init' to create one.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")

    root = path.parent.resolve()
    name = raw.get("name")
    if not name:
        raise ConfigError(f"{path} is missing the required 'name' field")
    slug = raw.get("slug") or str(name).lower().replace(" ", "-")

    assets = raw.get("assets") or {}
    if isinstance(assets, str):
        assets = {"dir": assets}
    assets_dir = str(assets.get("dir", "assets"))
    base_url = assets.get("base_url")
    if base_url:
        base_url = str(base_url).rstrip("/") + "/"
    banner_dir = str(assets.get("banner_dir", "banners"))

    # Generators run before anything is normalised, so a generated feature list
    # is checked and shaped exactly like a hand-written one. `resolve` replaces
    # every `{from: ...}` / `{use: ...}` reference in the tree with its elements.
    try:
        runtime = generators_mod.Runtime(root, raw, assets_dir=assets_dir,
                                         enabled=run_generators)
        generated = runtime.run_all() if run_generators else {}
        raw = runtime.resolve(raw)
    except generators_mod.GeneratorError as error:
        raise ConfigError(str(error)) from None
    warnings = list(runtime.warnings)

    links = {str(k): str(v) for k, v in (raw.get("links") or {}).items() if v}
    minecraft = dict(raw.get("minecraft") or {})
    minecraft["versions"] = [str(v) for v in _as_list(minecraft.get("versions"))]
    minecraft["loaders"] = [str(v) for v in _as_list(minecraft.get("loaders"))]

    license_name = raw.get("license")
    header = dict(raw.get("header") or {})
    if not header.get("banner"):
        header["banner"] = _find_banner(root, assets_dir, banner_dir, "header")
    header.setdefault("align", "center")
    header.setdefault("show_title", not header.get("banner"))
    header.setdefault("width", None)
    header.setdefault("section_banner_width", None)
    header.setdefault("heading_with_banner", False)

    outputs = {
        "readme": "README.md",
        "modrinth": "dist/modrinth.md",
        "curseforge": "dist/curseforge.md",
        "curseforge-html": "dist/curseforge.html",
    }
    outputs.update({str(k): str(v) for k, v in (raw.get("outputs") or {}).items()})

    return Config(
        root=root,
        raw=raw,
        name=str(name),
        slug=str(slug),
        tagline=raw.get("tagline"),
        authors=[str(a) for a in _as_list(raw.get("authors"))],
        assets_dir=assets_dir,
        assets_base_url=base_url,
        header=header,
        links=links,
        minecraft=minecraft,
        badges=_build_badges(raw, links, minecraft, slug, license_name),
        sections=_build_sections(raw, root, assets_dir, banner_dir, license_name),
        outputs=outputs,
        template=str(raw.get("template", "default")),
        footer=raw.get("footer"),
        toc=_build_toc(raw, root, assets_dir, banner_dir),
        generated=generated,
        warnings=warnings,
    )


def default_config_path(start: Path | None = None) -> Path:
    return (start or Path(os.getcwd())) / "modpage.yml"
