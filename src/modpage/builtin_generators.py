"""The generators that ship with modpage.

Each one answers the same question in a different place: *what does this repo
already know that the page keeps repeating by hand?* Tags know the version
history, commits know what changed, ``assets/gallery/`` knows which
screenshots exist, and ``modpage.yml`` itself knows the things a page needs to
say twice. Everything here returns plain dicts; shaping is the pipeline's job.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .generators import Context, generator
from .gitinfo import strip_version_prefix

# Conventional-commit types folded into changelog headings. A repo that uses
# other words says so with `groups:`; a repo that uses none at all still gets
# every commit, under `other_title`.
DEFAULT_GROUPS: dict[str, list[str]] = {
    "Added": ["feat", "feature", "add", "added", "new"],
    "Changed": ["change", "changed", "refactor", "perf", "style", "update"],
    "Fixed": ["fix", "fixed", "bugfix", "hotfix", "bug"],
    "Removed": ["remove", "removed", "deprecate", "drop"],
}
DEFAULT_SKIP_TYPES = ["chore", "ci", "build", "test", "tests", "docs", "doc",
                      "release", "bump", "merge", "wip"]

CHANGELOG_CANDIDATES = ["CHANGELOG.md", "CHANGES.md", "CHANGELOG.markdown",
                        "docs/CHANGELOG.md", "CHANGELOG.txt"]
# The file's own title, which is a heading but not a release.
CHANGELOG_TITLES = {"changelog", "change log", "changes", "release notes", "history"}

# `## [1.2.0] - 2024-05-01`, `## 1.2.0 (2024-05-01)`, `## Unreleased`
_RELEASE_HEADING = re.compile(
    r"^(?P<hashes>#{1,4})\s*\[?(?P<version>[^\]\n(]+?)\]?"
    r"(?:\s*[-–(—]\s*(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\)?)?\s*$"
)
_BULLET = re.compile(r"^\s*[-*+]\s+(?P<text>.+)$")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _repo_url(ctx: Context) -> str | None:
    """Where releases and commits live: ``links.github``, else git's origin."""
    configured = (ctx.raw.get("links") or {}).get("github")
    if configured:
        return str(configured).rstrip("/")
    return ctx.git.remote_url()


def _release_url(ctx: Context, tag: str) -> str:
    template = ctx.opt("url_template")
    if template:
        return str(template).replace("{tag}", tag).replace(
            "{version}", strip_version_prefix(tag))
    base = _repo_url(ctx)
    return f"{base}/releases/tag/{tag}" if base else ""


def _commit_url(base: str | None, sha: str) -> str:
    return f"{base}/commit/{sha}" if base else ""


def _require_git(ctx: Context) -> bool:
    """A repo without usable git warns once and yields nothing, rather than failing."""
    if ctx.git.available:
        return True
    ctx.warn(f"no git history available -- {ctx.git.unavailable_reason()}")
    return False


def _group_map(ctx: Context) -> tuple[dict[str, str], list[str], list[str]]:
    """``(type -> heading, heading order, skipped types)`` from the options."""
    configured = ctx.opt("groups")
    groups = DEFAULT_GROUPS if configured is None else configured
    if not isinstance(groups, dict):
        ctx.fail("'groups' must be a mapping of heading -> list of commit types")

    by_type: dict[str, str] = {}
    order: list[str] = []
    for heading, types in groups.items():
        order.append(str(heading))
        if isinstance(types, str):
            types = [types]
        for type_name in types or []:
            by_type[str(type_name).lower()] = str(heading)

    skip = [str(t).lower() for t in ctx.opt_list("skip_types", DEFAULT_SKIP_TYPES)]
    return by_type, order, skip


def _changes(ctx: Context, commits, base_url: str | None) -> tuple[list[dict], list[dict]]:
    """Turn commits into change elements plus the grouped view templates render."""
    by_type, order, skip = _group_map(ctx)
    other_title = str(ctx.opt("other_title", "Other"))
    include_other = bool(ctx.opt("include_other", True))

    changes: list[dict[str, Any]] = []
    for commit in commits:
        type_name = (commit.type or "").lower()
        if type_name and type_name in skip and not commit.breaking:
            continue
        heading = by_type.get(type_name)
        if heading is None:
            if not include_other:
                continue
            heading = other_title
        element = commit.as_element()
        element["group"] = heading
        element["url"] = _commit_url(base_url, commit.hash)
        changes.append(element)

    ordering = [*order, other_title]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        grouped.setdefault(change["group"], []).append(change)
    groups = [{"title": title, "key": title, "items": grouped[title]}
              for title in ordering if grouped.get(title)]
    return changes, groups


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


@generator("git.tags")
def git_tags(ctx: Context) -> list[dict[str, Any]]:
    """Every git tag as a version element (tag, version, date, message, url).

    Options: ``match`` (glob, e.g. ``v*``), ``sort`` (``date`` or ``version``),
    ``prereleases`` (default true).
    """
    if not _require_git(ctx):
        return []
    tags = ctx.git.tags(ctx.opt("match"), sort=str(ctx.opt("sort_tags", "date")))
    if not ctx.opt("prereleases", True):
        tags = [tag for tag in tags if not tag.prerelease]

    elements = []
    for tag in tags:
        element = tag.as_element()
        element["url"] = _release_url(ctx, tag.name)
        element["title"] = element["version"]
        element["description"] = tag.subject
        elements.append(element)
    if not elements:
        ctx.warn(f"no tags matched {ctx.opt('match') or '*'}")
    return elements


@generator("git.commits")
def git_commits(ctx: Context) -> list[dict[str, Any]]:
    """Commits from the log, with Conventional Commit type/scope split out.

    Options: ``since`` / ``until`` (any ref), ``paths`` (limit to files),
    ``limit``, ``types`` (keep only these), ``skip_types``, ``merges``.
    """
    if not _require_git(ctx):
        return []
    commits = ctx.git.commits(
        since=ctx.opt("since"),
        until=ctx.opt("until"),
        paths=[str(p) for p in ctx.opt_list("paths")] or None,
        limit=ctx.opt_int("limit"),
        no_merges=not ctx.opt("merges", False),
    )
    keep = [str(t).lower() for t in ctx.opt_list("types")]
    skip = [str(t).lower() for t in ctx.opt_list("skip_types")]
    base_url = _repo_url(ctx)

    elements = []
    for commit in commits:
        type_name = (commit.type or "").lower()
        if keep and type_name not in keep:
            continue
        if type_name and type_name in skip:
            continue
        element = commit.as_element()
        element["url"] = _commit_url(base_url, commit.hash)
        elements.append(element)
    return elements


@generator("git.changelog")
def git_changelog(ctx: Context) -> list[dict[str, Any]]:
    """One element per release: version, date, and its commits grouped by type.

    Walks the tags newest-first and collects the commits between each pair, so
    a page's changelog is whatever the repo has actually shipped. Options:
    ``match``, ``limit`` (releases), ``unreleased`` (default true), ``paths``,
    ``groups``, ``skip_types``, ``include_other``, ``url_template``.
    """
    if not _require_git(ctx):
        return []

    tags = ctx.git.tags(ctx.opt("match"), sort=str(ctx.opt("sort_tags", "date")))
    if not ctx.opt("prereleases", True):
        tags = [tag for tag in tags if not tag.prerelease]
    paths = [str(p) for p in ctx.opt_list("paths")] or None
    base_url = _repo_url(ctx)
    # `limit` trims releases here rather than in the pipeline, so the log is
    # only walked for the releases that will actually be shown.
    limit = ctx.opt_int("limit")

    releases: list[dict[str, Any]] = []

    if ctx.opt("unreleased", True):
        newest = tags[0].name if tags else None
        pending = ctx.git.commits(since=newest, paths=paths)
        if pending:
            changes, groups = _changes(ctx, pending, base_url)
            if changes:
                releases.append({
                    "version": str(ctx.opt("unreleased_title", "Unreleased")),
                    "tag": None, "url": "", "prerelease": False, "unreleased": True,
                    "date": pending[0].date, "datetime": pending[0].datetime,
                    "subject": "", "body": "",
                    "changes": changes, "groups": groups, "count": len(changes),
                    "title": str(ctx.opt("unreleased_title", "Unreleased")),
                })

    for index, tag in enumerate(tags):
        if limit is not None and len(releases) >= limit:
            break
        previous = tags[index + 1].name if index + 1 < len(tags) else None
        commits = ctx.git.commits(since=previous, until=tag.name, paths=paths)
        changes, groups = _changes(ctx, commits, base_url)
        if not changes and not tag.body and ctx.opt("skip_empty", True):
            continue
        element = tag.as_element()
        element.update({
            "url": _release_url(ctx, tag.name),
            "unreleased": False,
            "changes": changes,
            "groups": groups,
            "count": len(changes),
            "title": element["version"],
        })
        releases.append(element)

    if not releases:
        ctx.warn("no releases found -- tag a commit, or set unreleased: true")
    return releases


@generator("git.contributors")
def git_contributors(ctx: Context) -> list[dict[str, Any]]:
    """Everyone who has committed, most commits first -- a credits section that keeps itself.

    Options: ``since``, ``paths``, ``limit``, ``exclude`` (names or emails).
    """
    if not _require_git(ctx):
        return []
    commits = ctx.git.commits(
        since=ctx.opt("since"),
        paths=[str(p) for p in ctx.opt_list("paths")] or None,
    )
    exclude = {str(name).lower() for name in ctx.opt_list("exclude")}

    tally: dict[str, dict[str, Any]] = {}
    for commit in commits:
        if commit.author.lower() in exclude or commit.email.lower() in exclude:
            continue
        entry = tally.setdefault(commit.email.lower(), {
            "name": commit.author, "title": commit.author, "email": commit.email,
            "commits": 0, "first": commit.date, "last": commit.date, "url": "",
        })
        entry["commits"] += 1
        entry["first"] = min(entry["first"], commit.date)
        entry["last"] = max(entry["last"], commit.date)
        # GitHub's noreply addresses carry the username; it is the only handle
        # the log reliably holds, so use it when it is there.
        if entry["email"].endswith("@users.noreply.github.com"):
            handle = entry["email"].split("@")[0].split("+")[-1]
            entry["url"] = f"https://github.com/{handle}"
            entry["handle"] = handle

    ordered = sorted(tally.values(), key=lambda item: -item["commits"])
    return ordered


# ---------------------------------------------------------------------------
# files and data in the tree
# ---------------------------------------------------------------------------


def _pretty(stem: str) -> str:
    text = re.sub(r"[_-]+", " ", stem).strip()
    # A leading `01_` / `2-` is an ordering hint, not part of the caption.
    text = re.sub(r"^\d+[\s.)]*", "", text)
    return text[:1].upper() + text[1:] if text else stem


@generator("files.glob")
def files_glob(ctx: Context) -> list[dict[str, Any]]:
    """Files in the tree as elements -- gallery images, slider slides, showcases.

    ``pattern`` is a glob (or a list of them) resolved inside ``assets.dir``, so
    ``gallery/*.png`` gives entries whose ``src`` the templates can pass
    straight to ``asset()``. Options: ``dir`` (a different base, repo-relative),
    ``captions`` (mapping of stem -> caption), ``dates`` (ask git when each file
    was added).
    """
    patterns = [str(p) for p in (ctx.opt_list("pattern") or ctx.opt_list("patterns"))]
    if not patterns:
        ctx.fail("needs a 'pattern:', e.g. pattern: \"gallery/*.png\"")

    base_option = ctx.opt("dir")
    if base_option is None:
        base = ctx.root / ctx.assets_dir
        assets_relative = True
    else:
        base = ctx.root / str(base_option).lstrip("/")
        assets_relative = base.resolve() == (ctx.root / ctx.assets_dir).resolve() or (
            (ctx.root / ctx.assets_dir).resolve() in base.resolve().parents)
        if not assets_relative:
            ctx.warn(f"dir '{base_option}' is outside assets.dir, so 'src' will not "
                     "resolve through asset() -- move the files or set assets.dir")

    captions = ctx.opt("captions") or {}
    want_dates = bool(ctx.opt("dates", False))

    seen: set[Path] = set()
    elements: list[dict[str, Any]] = []
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            repo_relative = path.relative_to(ctx.root).as_posix()
            try:
                src = path.relative_to(ctx.root / ctx.assets_dir).as_posix()
            except ValueError:
                src = repo_relative
            caption = captions.get(path.stem, _pretty(path.stem))
            element: dict[str, Any] = {
                "src": src, "image": src, "path": repo_relative,
                "name": path.name, "stem": path.stem, "ext": path.suffix.lstrip("."),
                "title": caption, "caption": caption, "alt": caption,
                "size": path.stat().st_size, "index": len(elements) + 1,
            }
            if want_dates:
                added, updated = ctx.git.file_dates(repo_relative)
                element["date"] = added or ""
                element["updated"] = updated or ""
            elements.append(element)

    if not elements:
        ctx.warn(f"no files matched {', '.join(patterns)} under {base}")
    return elements


# ---------------------------------------------------------------------------
# Minecraft: the language file
# ---------------------------------------------------------------------------

#: Where a mod keeps its translations. Both layouts a Minecraft mod uses, in the order the game
#: looks: a resource pack rooted at the repository, and a Gradle source set.
LANG_ROOTS = ("assets", "src/main/resources/assets")


def _lang_files(ctx: Context, namespace: str | None, code: str) -> list[Path]:
    """Every ``assets/<ns>/lang/<code>.json`` in the repository, or one namespace's."""
    out: list[Path] = []
    for root in LANG_ROOTS:
        base = ctx.root / root
        if not base.is_dir():
            continue
        for path in sorted(base.glob(f"{namespace or '*'}/lang/{code}.json")):
            if path.is_file():
                out.append(path)
    return out


def _lang_map(ctx: Context, namespace: str | None = None, code: str = "en_us") -> dict[str, str]:
    """The translations, merged, first file winning - which is the game's own rule."""
    merged: dict[str, str] = {}
    for path in _lang_files(ctx, namespace, code):
        loaded = ctx.load_data(path.relative_to(ctx.root).as_posix())
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                merged.setdefault(str(key), str(value))
    return merged


def _parse_lang_key(key: str) -> dict[str, str]:
    """What a translation key says about the thing it names.

    Minecraft keys read ``<kind>.<namespace>.<path>`` - ``item.minecraft.diamond``,
    ``decoration.armorpieces.circlet``, ``block.mymod.lamp.tooltip``. The first two segments are
    the kind and the namespace; everything after is the path, and the id is the namespace and the
    path joined with a colon, which is what every other file in a mod calls the same thing."""
    parts = key.split(".")
    if len(parts) < 3:
        return {"kind": parts[0] if parts else "", "namespace": "", "path": "", "id": ""}
    kind, namespace = parts[0], parts[1]
    path = ".".join(parts[2:])
    return {"kind": kind, "namespace": namespace, "path": path,
            "id": f"{namespace}:{path.replace('.', '/')}" if path else ""}


@generator("mc.lang")
def mc_lang(ctx: Context) -> list[dict[str, Any]]:
    """Every line of a mod's language file, with the id each key names.

    Options: ``namespace`` (one namespace rather than every one in the repo), ``code`` (the
    language, default ``en_us``), ``kind`` (only keys of this kind - ``item``, ``block``,
    whatever a mod invented), ``prefix`` (only keys starting with this).

    Display names are the one thing a mod repository knows and a page cannot guess: prettifying
    an id gets ``Great Helm`` right and ``TNT`` wrong, and it never gets a name that is not the
    id at all. This reads what the game reads.
    """
    namespace = ctx.opt("namespace")
    code = str(ctx.opt("code", "en_us"))
    kind = ctx.opt("kind")
    prefix = ctx.opt("prefix")

    lines = _lang_map(ctx, str(namespace) if namespace else None, code)
    if not lines:
        ctx.warn(f"no {code}.json under " + " or ".join(f"{root}/<ns>/lang" for root in LANG_ROOTS))
        return []

    elements: list[dict[str, Any]] = []
    for key, value in sorted(lines.items()):
        if prefix and not key.startswith(str(prefix)):
            continue
        parsed = _parse_lang_key(key)
        if kind and parsed["kind"] != str(kind):
            continue
        elements.append({"key": key, "value": value, "title": value, "name": value,
                         "description": "", **parsed})
    if not elements:
        ctx.warn(f"{len(lines)} lines in {code}.json, none matching")
    return elements


@generator("data.file")
def data_file(ctx: Context) -> list[dict[str, Any]]:
    """Elements read out of JSON or YAML in the repo (``fabric.mod.json``, a data pack…).

    Options: ``path`` (one file) or ``pattern`` (a glob, one element per file),
    ``pluck`` (dotted path to the list or mapping inside each file), ``key``
    (field name to store a mapping's key under, default ``id``), ``each``
    (force one element per key -- a mapping of id to a version string is a list
    of dependencies, while a mod manifest is one object, and only you know
    which you have), ``lang`` (resolve display names through the mod's language
    file: see below).

    ``lang:`` takes a dotted path to the translation key inside each element --
    ``description.translate`` for a data-driven registry entry, or ``true`` for
    the common shape where the element's own ``translate`` field holds it. The
    line it names becomes the element's ``title`` and ``name``, so a generated
    list says what the game says rather than a prettified id. A key with no
    translation leaves the element as it was, which is what the game does too.
    """
    key_field = str(ctx.opt("key", "id"))
    pluck = ctx.opt("pluck")
    each = ctx.opt("each")
    lang_at = ctx.opt("lang")
    lines = _lang_map(ctx, str(ctx.opt("namespace")) if ctx.opt("namespace") else None,
                      str(ctx.opt("code", "en_us"))) if lang_at else {}

    documents: list[tuple[Path | None, Any]] = []
    if ctx.opt("path"):
        loaded = ctx.load_data(str(ctx.opt("path")))
        if loaded is None:
            ctx.warn(f"no file at {ctx.opt('path')}")
        else:
            documents.append((ctx.root / str(ctx.opt("path")), loaded))
    for pattern in [str(p) for p in ctx.opt_list("pattern")]:
        for path in sorted(ctx.root.glob(pattern)):
            if path.is_file():
                documents.append((path, ctx.load_data(path.relative_to(ctx.root).as_posix())))
    if not documents:
        ctx.warn("needs a 'path:' or 'pattern:' naming a JSON or YAML file")
        return []

    elements: list[dict[str, Any]] = []
    for path, document in documents:
        node = document
        if pluck:
            for part in str(pluck).split("."):
                node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    break
        if node is None:
            continue
        stem = path.stem if path else ""
        if isinstance(node, list):
            for item in node:
                element = dict(item) if isinstance(item, dict) else {"value": item,
                                                                     "title": str(item)}
                element.setdefault("file", stem)
                elements.append(element)
        elif isinstance(node, dict):
            # A mapping of id -> object is a list of things; a plain object (a
            # mod manifest, say) is one. `each:` settles the case a mapping of
            # id -> "1.2.0" leaves genuinely ambiguous.
            values = list(node.values())
            per_key = each if each is not None else bool(
                values and all(isinstance(value, dict) for value in values))
            if per_key:
                for key, value in node.items():
                    fields = value if isinstance(value, dict) else {"value": value,
                                                                    "description": str(value)}
                    elements.append({key_field: key, "title": str(key), "name": str(key),
                                     **fields, "file": stem})
            else:
                elements.append({**node, "file": stem, key_field: node.get(key_field, stem)})
        else:
            elements.append({"value": node, "title": str(node), "file": stem})

    if lang_at:
        path_parts = None if lang_at is True else str(lang_at).split(".")
        for element in elements:
            key = element.get("translate") if path_parts is None else _dig(element, path_parts)
            line = lines.get(str(key)) if isinstance(key, str) else None
            if line:
                element["title"] = line
                element["name"] = line
                element["translate"] = key
    return elements


def _dig(node: Any, parts: list[str]) -> Any:
    """One dotted path into a nested mapping, or None."""
    for part in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


@generator("changelog.file")
def changelog_file(ctx: Context) -> list[dict[str, Any]]:
    """A hand-written ``CHANGELOG.md`` parsed into the same shape as ``git.changelog``.

    Reads the Keep a Changelog layout -- ``## [1.2.0] - 2024-05-01`` with
    ``### Added`` groups and bullets under them -- and falls back to a flat
    bullet list for files that use no groups. Options: ``path``, ``limit``,
    ``url_template``.
    """
    path = ctx.opt("path")
    candidates = [str(path)] if path else CHANGELOG_CANDIDATES
    text = None
    for candidate in candidates:
        text = ctx.read_text(candidate)
        if text is not None:
            path = candidate
            break
    if text is None:
        ctx.warn(f"no changelog file found (looked for {', '.join(candidates)})")
        return []

    # A file's releases are whatever heading depth first carries a version;
    # anything deeper is a group inside the release above it.
    known_tags = {strip_version_prefix(tag.name): tag.name for tag in ctx.git.tags()}

    releases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    group: dict[str, Any] | None = None
    level: int | None = None

    for line in text.splitlines():
        heading = _RELEASE_HEADING.match(line)
        if heading:
            depth = len(heading.group("hashes"))
            version = heading.group("version").strip()
            if level is None and version.lower() not in CHANGELOG_TITLES:
                level = depth
            if depth == level:
                number = strip_version_prefix(version)
                unreleased = version.lower().startswith("unreleased")
                # Only link a release the repo can actually point at: an
                # explicit url_template, or a tag that really exists.
                tag = known_tags.get(number, version)
                linkable = not unreleased and (ctx.opt("url_template") or number in known_tags)
                current = {
                    "version": number, "tag": tag, "title": number,
                    "date": heading.group("date") or "", "datetime": heading.group("date") or "",
                    "url": _release_url(ctx, tag) if linkable else "",
                    "unreleased": unreleased,
                    "prerelease": False, "subject": "", "body": "",
                    "changes": [], "groups": [], "count": 0,
                }
                releases.append(current)
                group = None
                continue
            if current is not None and depth > (level or 2):
                group = {"title": version, "key": version.lower(), "items": []}
                current["groups"].append(group)
                continue

        bullet = _BULLET.match(line)
        if bullet and current is not None:
            change = {"title": bullet.group("text").strip(),
                      "subject": bullet.group("text").strip(),
                      "group": group["title"] if group else "",
                      "type": (group["key"] if group else None), "url": ""}
            current["changes"].append(change)
            current["count"] = len(current["changes"])
            if group is not None:
                group["items"].append(change)
            continue

        if current is not None and line.strip() and not line.startswith("#"):
            current["body"] = (current["body"] + "\n" + line).strip()

    # A file with no `### Added` headings still deserves a group to render.
    for release in releases:
        if not release["groups"] and release["changes"]:
            release["groups"] = [{"title": "", "key": "", "items": release["changes"]}]

    limit = ctx.opt_int("limit")
    return releases[:limit] if limit else releases


# ---------------------------------------------------------------------------
# the page config itself
# ---------------------------------------------------------------------------


@generator("config.pluck")
def config_pluck(ctx: Context) -> list[Any]:
    """Objects from elsewhere in ``modpage.yml``, so one list feeds several sections.

    ``path`` is dotted: ``sections.features.items``, ``minecraft.versions``,
    ``extra.showcase``. A list comes through as-is; a mapping becomes one
    element per key (stored under ``key``); a scalar becomes a single element.
    """
    dotted = ctx.opt("path")
    if not dotted:
        ctx.fail("needs a 'path:', e.g. path: sections.features.items")
    node = ctx.expand(ctx.pluck(str(dotted)))
    if node is None:
        ctx.warn(f"nothing at '{dotted}' in modpage.yml")
        return []
    if isinstance(node, list):
        return list(node)
    if isinstance(node, dict):
        key_field = str(ctx.opt("key", "key"))
        return [
            {key_field: key, "title": str(key), **(value if isinstance(value, dict)
                                                   else {"value": value})}
            for key, value in node.items()
        ]
    return [{"title": str(node), "value": node}]


@generator("config.versions")
def config_versions(ctx: Context) -> list[dict[str, Any]]:
    """The ``minecraft:`` block crossed into one element per version/loader pair.

    A support table that stays right when a version is added in one place.
    Options: ``by`` (``version`` or ``loader``, default ``version``).
    """
    minecraft = ctx.raw.get("minecraft") or {}
    versions = [str(v) for v in (minecraft.get("versions") or [])]
    loaders = [str(v) for v in (minecraft.get("loaders") or [])]
    if not versions and not loaders:
        ctx.warn("the 'minecraft:' block lists no versions or loaders")
        return []

    if str(ctx.opt("by", "version")) == "loader":
        return [{"title": loader, "loader": loader, "versions": versions,
                 "description": ", ".join(versions)} for loader in loaders or ["Any"]]
    return [{"title": version, "version": version, "loaders": loaders,
             "description": ", ".join(loaders)} for version in versions]
