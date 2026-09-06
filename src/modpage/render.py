"""Render a :class:`~modpage.config.Config` into each publishing target."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from posixpath import join as urljoin
from typing import Any

import markdown as markdown_lib
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, Undefined

from . import generators
from .config import Config, ConfigError, Section

TEMPLATE_DIR = Path(__file__).parent / "templates"

@dataclass(frozen=True)
class Target:
    template: str
    #: The site this page is for; a section's ``targets:`` may name it instead
    #: of the exact target id, so ``curseforge`` also covers ``curseforge-html``.
    platform: str
    html: bool = False
    absolute_urls: bool = False
    #: Whether in-page links work here. Anchors need an ``id`` attribute, so a
    #: target that renders no HTML at all gets an unlinked contents list.
    anchors: bool = True
    #: Rendered by a bare ``modpage build``; opt-in targets need ``-t``.
    default: bool = True


TARGETS: dict[str, Target] = {
    "readme": Target("readme.md.j2", "readme"),
    "modrinth": Target("modrinth.md.j2", "modrinth", absolute_urls=True),
    # CurseForge's editor offers WYSIWYG or Markdown, nothing else, and its
    # Markdown mode escapes raw HTML -- so the page it gets is HTML-free Markdown.
    "curseforge": Target("curseforge.md.j2", "curseforge", absolute_urls=True, anchors=False),
    # Opt in: the same page as HTML, for opening in a browser and copying the
    # rendered result into the WYSIWYG editor. Pasting the source does not work.
    "curseforge-html": Target("curseforge.html.j2", "curseforge",
                              html=True, absolute_urls=True, default=False),
}
DEFAULT_TARGETS: list[str] = [name for name, spec in TARGETS.items() if spec.default]

_REMOTE = ("http://", "https://", "//", "data:", "mailto:")
_MD = markdown_lib.Markdown(extensions=["extra", "sane_lists", "smarty"])


@dataclass
class Rendered:
    target: str
    path: Path
    content: str
    warnings: list[str]


def _tidy(text: str) -> str:
    """Jinja leaves ragged blank lines; normalise them so diffs stay small."""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def _md_to_html(text: str | None) -> str:
    if not text:
        return ""
    _MD.reset()
    return _MD.convert(str(text))


def _make_environment(config: Config) -> Environment:
    """Project templates in ``.modpage/templates`` win over the packaged ones."""
    env = Environment(
        loader=ChoiceLoader([
            FileSystemLoader(config.root / ".modpage" / "templates"),
            FileSystemLoader(TEMPLATE_DIR),
        ]),
        # Configs are deliberately sparse: an unset key renders as nothing
        # rather than exploding halfway through a page.
        undefined=Undefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["md"] = _md_to_html
    env.filters["inline_md"] = lambda text: re.sub(r"</?p>", "", _md_to_html(text)).strip()
    # Generated elements carry ISO dates and raw ids; give templates the same
    # two filters the generator pipeline uses to tidy them.
    env.filters["date"] = generators.fmt_date
    env.filters["slug"] = generators.slugify
    return env


def _asset_resolver(config: Config, target: str, out_path: Path, warnings: list[str]):
    """Build the ``asset()`` helper the templates call for every image path."""
    absolute_required = TARGETS[target].absolute_urls

    # A README that does not sit at the repo root still needs working relative
    # links, so walk back up to the config root.
    try:
        depth = len(out_path.resolve().parent.relative_to(config.root).parts)
    except ValueError:
        depth = 0
    prefix = "../" * depth

    seen_missing: set[str] = set()

    def asset(path: str | None) -> str:
        if not path:
            return ""
        path = str(path)
        if path.startswith(_REMOTE):
            return path

        relative = urljoin(config.assets_dir, path.lstrip("/"))
        on_disk = config.root / relative
        if not on_disk.is_file() and relative not in seen_missing:
            seen_missing.add(relative)
            warnings.append(f"asset not found on disk: {relative}")

        if absolute_required:
            if not config.assets_base_url:
                message = (
                    f"'{target}' needs absolute image URLs; set assets.base_url in modpage.yml "
                    "(e.g. https://raw.githubusercontent.com/<user>/<repo>/main/)"
                )
                if message not in warnings:
                    warnings.append(message)
                return prefix + relative
            return config.assets_base_url + relative
        return prefix + relative

    return asset


def _toc_context(config: Config, target: str,
                 sections: list[Section]) -> dict[str, Any] | None:
    """The contents list for one target, or ``None`` when it should be left out."""
    toc = config.toc
    if not toc:
        return None
    spec = TARGETS[target]
    if toc["targets"] is not None and not {target, spec.platform} & set(toc["targets"]):
        return None

    entries = [
        {"id": section.id, "title": section.title,
         "anchor": section.id if spec.anchors else None}
        for section in sections if section.id not in toc["skip"]
    ]
    # A contents list over one or two sections is noise, not navigation.
    if len(entries) < toc["min_sections"]:
        return None
    return {**toc, "entries": entries}


def render_target(config: Config, target: str) -> Rendered:
    if target not in TARGETS:
        raise ConfigError(f"unknown target '{target}'. Known: {', '.join(TARGETS)}")

    spec = TARGETS[target]
    out_path = config.root / config.outputs[target]
    warnings: list[str] = []
    if not spec.html and out_path.suffix.lower() in (".html", ".htm"):
        warnings.append(
            f"'{target}' now renders Markdown but outputs.{target} is {config.outputs[target]}; "
            "change it to a .md path (the HTML page is the opt-in 'curseforge-html' target)"
        )

    env = _make_environment(config)
    env.globals["asset"] = _asset_resolver(config, target, out_path, warnings)
    template = env.get_template(f"{config.template}/{spec.template}")

    visible = [s for s in config.sections
               if s.targets is None or target in s.targets or spec.platform in s.targets]
    context: dict[str, Any] = {
        "cfg": config,
        "partials": f"{config.template}/partials",
        "mod": config,
        "target": target,
        "platform": spec.platform,
        "is_html": spec.html,
        "sections": visible,
        "toc": _toc_context(config, target, visible),
        "header": config.header,
        "badges": config.badges,
        "links": config.links,
        "minecraft": config.minecraft,
        "extra": config.raw.get("extra", {}),
        # Every declared generator's elements, whether or not a section uses
        # them -- a custom template can lay them out however it likes.
        "gen": config.generated,
    }
    return Rendered(target, out_path, _tidy(template.render(**context)), warnings)


def render_all(config: Config, targets: list[str] | None = None) -> list[Rendered]:
    return [render_target(config, target) for target in (targets or DEFAULT_TARGETS)]
