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
    # Opt in: not a page at all. Everything the page templates are given, as JSON, for a consumer
    # that has its own renderer -- a website, an app -- and would rather lay the facts out itself
    # than parse a rendered page back apart. Absolute URLs, because whoever reads this is not
    # serving from the repository.
    "site": Target("site.json.j2", "site", absolute_urls=True, anchors=False, default=False),
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


def _jsonable(value: Any) -> Any:
    """Anything the context holds, as something json can write.

    Sections are dataclasses and generated elements are whatever a generator returned; both are
    plain data underneath. A Path becomes its string, a date its ISO form, and anything else its
    repr rather than an exception -- a target that refuses to render because one generator handed
    back an odd object would be a worse answer than a string saying what it was."""
    from datetime import date, datetime
    from dataclasses import asdict, is_dataclass

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    return repr(value)


def _site_json(context: dict[str, Any]) -> str:
    """The render context, as JSON: what the `site` target emits.

    The whole context minus the pieces that are functions or that only mean something inside a
    Jinja render -- `cfg` (the Config object itself, whose fields are already spread across the
    rest), and `partials` (a template path)."""
    import json

    body = {key: _jsonable(value) for key, value in context.items()
            if key not in ("cfg", "partials", "mod", "site_json")}
    # The raw config too, so nothing a repo put in modpage.yml is lost on the way through.
    body["raw"] = _jsonable(context["cfg"].raw)
    return json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True)


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
    # The `site` target's whole body is the context as JSON; the template asks for it by name so
    # that a repo can override the file and emit a different shape without touching Python.
    context["site_json"] = lambda indent=2: _site_json(context)
    rendered = template.render(**context)
    # JSON is whitespace-sensitive in a way prose is not: _tidy would collapse the blank lines
    # inside a string and strip the trailing newline a file wants.
    return Rendered(target, out_path, rendered if target == "site" else _tidy(rendered), warnings)


def render_all(config: Config, targets: list[str] | None = None) -> list[Rendered]:
    return [render_target(config, target) for target in (targets or DEFAULT_TARGETS)]


def render_documents(config: Config, targets: list[str] | None = None,
                     load: Any = None) -> list[Rendered]:
    """Every extra config the ``documents:`` block names, rendered to its own output.

    A build has more than one page to write the moment a mod has a wiki. Each document is an
    ordinary config with its own sections and its own generators - so a page can be prose, or
    generated, or both, and nothing about it is a special case - and the only thing the parent
    config says about it is which file it is and where its output goes.

    `load` is the config loader, passed in rather than imported, so this module keeps not knowing
    how a config is read.
    """
    if not config.documents:
        return []
    if load is None:
        from .config import load  # type: ignore[assignment]

    out: list[Rendered] = []
    for entry in config.documents:
        path = config.root / entry["config"]
        if not path.is_file():
            raise ConfigError(f"documents: no config at {entry['config']}")
        document = load(path)
        wanted = entry.get("targets") or []
        for target in (targets or DEFAULT_TARGETS):
            if target not in TARGETS or (wanted and target not in wanted):
                continue
            # A document that says where its own targets land is left alone; otherwise the
            # parent's `out:` decides, which is the ordinary case - a document should not have to
            # repeat five paths to be a second page.
            if not (document.raw.get("outputs") or {}).get(target):
                where = entry["out"].replace("{target}", target).replace("{ext}", _extension(target))
                rendering = [t for t in (targets or DEFAULT_TARGETS)
                             if t in TARGETS and (not wanted or t in wanted)]
                if where == entry["out"] and len(rendering) > 1:
                    raise ConfigError(
                        f"documents: '{entry['id']}' has out: {entry['out']!r}, which names no "
                        "{target} or {ext}, so every target would write the same file. Put one in, "
                        "or render one target at a time."
                    )
                # `out:` is written from the parent config's root, which is where the person
                # writing it is standing; the document's own root may be a subfolder, so the path
                # is resolved here rather than left relative to the wrong thing.
                document.outputs[target] = str((config.root / where).resolve())
            out.append(render_target(document, target))
    return out


def _extension(target: str) -> str:
    """The file extension a target's output wants, for a `documents:` entry that says `{ext}`."""
    if target == "site":
        return "json"
    return "html" if TARGETS[target].html else "md"
