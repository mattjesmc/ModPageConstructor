"""Element generators: build page content from the repo instead of by hand.

A *generator* is a function that returns a list of **elements** -- plain dicts
-- given a :class:`Context` describing the repo and the options it was declared
with. Where a hand-written config lists ten features, a generated one names a
generator once and the list follows the repo:

.. code-block:: yaml

    generators:
      releases:
        use: git.changelog
        match: "v*"
        limit: 5

    sections:
      changelog:
        elements: {from: releases}

Everything a generator returns then goes through the same shaping pipeline --
``where``/``when``, ``sort``, ``offset``/``limit``, ``map``, ``group_by`` -- so
a generator only has to fetch, never to format. The pipeline is available at the
reference site too, which is what makes one generator serve several sections:
the same ``releases`` can be five entries in the changelog and one line in the
header.

Generators are looked up in a registry. The built-ins live in
:mod:`modpage.builtin_generators`; a repo adds its own by dropping a module in
``.modpage/generators/`` and decorating a function::

    from modpage.generators import generator

    @generator("mymod.showcase")
    def showcase(ctx):
        return [{"title": p.stem, "image": f"showcase/{p.name}"}
                for p in ctx.glob("showcase/*.png")]
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml
from jinja2 import Environment, Undefined

from .gitinfo import GitRepo, version_key

GeneratorFn = Callable[["Context"], Iterable[Any]]

#: Keys that shape an existing result rather than telling a generator what to
#: fetch. Recognised both on a declaration and at every reference site.
PIPELINE_KEYS = frozenset({
    "where", "when", "sort", "reverse", "limit", "offset", "map", "fields",
    "group_by", "group_titles", "unique",
})
#: Keys that are about the reference itself, not options for the generator.
_REF_KEYS = frozenset({"from", "use"})

_REGISTRY: dict[str, GeneratorFn] = {}
_PROJECTS_LOADED: set[Path] = set()


class GeneratorError(Exception):
    """Raised for a generator a human needs to fix; the CLI prints it verbatim."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def register(name: str, fn: GeneratorFn) -> GeneratorFn:
    _REGISTRY[str(name)] = fn
    return fn


def generator(name: str) -> Callable[[GeneratorFn], GeneratorFn]:
    """Decorator form: ``@generator("mymod.showcase")``."""
    def decorate(fn: GeneratorFn) -> GeneratorFn:
        return register(name, fn)
    return decorate


def registry() -> dict[str, GeneratorFn]:
    _load_builtins()
    return dict(_REGISTRY)


def describe(name: str) -> str:
    """The generator's one-line summary, for ``modpage generators``."""
    fn = registry().get(name)
    doc = (fn.__doc__ or "").strip() if fn else ""
    return doc.splitlines()[0] if doc else ""


def _load_builtins() -> None:
    from . import builtin_generators  # noqa: F401  (registers on import)


def load_project_generators(root: Path, warnings: list[str] | None = None) -> list[str]:
    """Import every ``.modpage/generators/*.py`` in a mod repo, once per root.

    These are the repo's own files, run at build time exactly like its
    templates are -- there is no sandbox, and none is implied.
    """
    root = Path(root).resolve()
    directory = root / ".modpage" / "generators"
    if root in _PROJECTS_LOADED or not directory.is_dir():
        return []
    _PROJECTS_LOADED.add(root)

    loaded: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"modpage._project_generators.{root.name}_{path.stem}"
        try:
            module = _import_path(module_name, path)
        except Exception as error:  # a repo's own module: report, do not crash
            if warnings is not None:
                warnings.append(f"generator module {path.name} failed to import: {error}")
            continue
        sys.modules[module_name] = module
        loaded.append(path.name)
    return loaded


def _import_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise GeneratorError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_callable(use: str, ctx_root: Path) -> GeneratorFn:
    """``git.tags`` from the registry, or ``path/to/file.py:function``."""
    _load_builtins()
    if use in _REGISTRY:
        return _REGISTRY[use]
    if ".py:" in use or use.endswith(".py"):
        file_part, _, func_name = use.partition(":")
        path = (ctx_root / file_part).resolve()
        if not path.is_file():
            raise GeneratorError(f"no generator file at {file_part}")
        module = _import_path(f"modpage._adhoc_{path.stem}", path)
        fn = getattr(module, func_name or "generate", None)
        if not callable(fn):
            raise GeneratorError(
                f"{file_part} has no callable '{func_name or 'generate'}'"
            )
        return fn
    known = ", ".join(sorted(_REGISTRY)) or "none"
    raise GeneratorError(f"unknown generator '{use}'. Registered: {known}")


# ---------------------------------------------------------------------------
# Context handed to every generator
# ---------------------------------------------------------------------------


@dataclass
class Context:
    """Everything a generator is allowed to read, and how to complain."""

    name: str
    root: Path
    #: The whole ``modpage.yml`` as loaded, before any generator ran.
    raw: dict[str, Any]
    options: dict[str, Any]
    git: GitRepo
    assets_dir: str = "assets"
    warnings: list[str] = field(default_factory=list)
    #: Set by the runtime, so a generator that reads the config can expand a
    #: reference it lands on rather than handing back ``{from: ...}``.
    runtime: Any = None

    # -- options ----------------------------------------------------------

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    def opt_int(self, key: str, default: int | None = None) -> int | None:
        value = self.options.get(key, default)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise GeneratorError(
                f"{self.name}: '{key}' must be a number, got {value!r}"
            ) from None

    def opt_list(self, key: str, default: Iterable[Any] = ()) -> list[Any]:
        value = self.options.get(key)
        if value is None:
            return list(default)
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value]

    def warn(self, message: str) -> None:
        text = f"{self.name}: {message}"
        if text not in self.warnings:
            self.warnings.append(text)

    def fail(self, message: str) -> None:
        raise GeneratorError(f"{self.name}: {message}")

    # -- the repo ---------------------------------------------------------

    def glob(self, pattern: str, *, relative_to: str | None = None) -> list[Path]:
        """Files matching a glob, relative to the assets dir unless told otherwise."""
        base = self.root / (self.assets_dir if relative_to is None else relative_to)
        return sorted(path for path in base.glob(pattern) if path.is_file())

    def read_text(self, relative: str) -> str | None:
        path = self.root / relative
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def load_data(self, relative: str) -> Any:
        """Parse a JSON or YAML file from the repo; ``None`` when it is missing."""
        text = self.read_text(relative)
        if text is None:
            return None
        if relative.lower().endswith(".json"):
            try:
                return json.loads(text)
            except json.JSONDecodeError as error:
                self.fail(f"{relative} is not valid JSON ({error})")
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as error:
            self.fail(f"{relative} is not valid YAML ({error})")

    def expand(self, node: Any) -> Any:
        """Resolve any generator reference inside a value read from the config."""
        if self.runtime is None:
            return node
        return self.runtime.resolve(node)

    def pluck(self, dotted: str, default: Any = None) -> Any:
        """Look a value up in the page config: ``sections.features.items``.

        Numeric segments index into lists, so ``minecraft.versions.0`` works.
        """
        node: Any = self.raw
        for part in str(dotted).split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, (list, tuple)) and part.lstrip("-").isdigit():
                index = int(part)
                if -len(node) <= index < len(node):
                    node = node[index]
                else:
                    return default
            else:
                return default
        return node


# ---------------------------------------------------------------------------
# The shaping pipeline
# ---------------------------------------------------------------------------

_JINJA = Environment(undefined=Undefined, autoescape=False)


def fmt_date(value: Any, pattern: str = "%d %b %Y") -> str:
    """``{{ date | date('%b %Y') }}`` over an ISO string, without importing one."""
    from datetime import datetime

    text = str(value or "")
    if not text:
        return ""
    for shape in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if "T" in shape else text[:10],
                                     shape.replace("%z", "")).strftime(pattern)
        except ValueError:
            continue
    return text


def slugify(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


_JINJA.filters["date"] = fmt_date
_JINJA.filters["slug"] = slugify


def _as_element(item: Any) -> dict[str, Any]:
    """Generators may yield dicts, strings, or paths; templates want dicts."""
    if isinstance(item, dict):
        return dict(item)
    if isinstance(item, Path):
        return {"path": str(item), "name": item.name, "title": item.stem}
    if isinstance(item, str):
        return {"title": item, "name": item}
    if hasattr(item, "as_element"):
        return dict(item.as_element())
    if hasattr(item, "__dict__"):
        return {k: v for k, v in vars(item).items() if not k.startswith("_")}
    return {"value": item}


def _render(template: str, element: dict[str, Any]) -> str:
    try:
        return _JINJA.from_string(template).render(**element).strip()
    except Exception as error:
        raise GeneratorError(f"expression {template!r} failed: {error}") from None


def _truthy(template: str, element: dict[str, Any]) -> bool:
    text = template.strip()
    if not (text.startswith("{{") or text.startswith("{%")):
        text = "{{ " + text + " }}"
    rendered = _render(text, element).strip().lower()
    return rendered not in ("", "false", "none", "0", "[]", "{}")


_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "in": lambda a, b: a in (b or []),
    "not_in": lambda a, b: a not in (b or []),
    "contains": lambda a, b: str(b) in str(a or ""),
    "matches": lambda a, b: re.search(str(b), str(a or "")) is not None,
    "gt": lambda a, b: a is not None and a > b,
    "gte": lambda a, b: a is not None and a >= b,
    "lt": lambda a, b: a is not None and a < b,
    "lte": lambda a, b: a is not None and a <= b,
    "exists": lambda a, b: (a not in (None, "", [], {})) is bool(b),
}


def _matches(element: dict[str, Any], where: dict[str, Any]) -> bool:
    for field_name, expected in where.items():
        actual = element.get(field_name)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                check = _OPS.get(op)
                if check is None:
                    raise GeneratorError(
                        f"unknown 'where' operator '{op}'. Known: {', '.join(_OPS)}"
                    )
                if not check(actual, operand):
                    return False
        elif isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _sort_spec(spec: Any) -> tuple[str, bool, bool]:
    """``-date`` / ``{by: version, reverse: true, numeric: true}`` -> a key."""
    if isinstance(spec, dict):
        by = str(spec.get("by") or spec.get("field") or "")
        return by, bool(spec.get("reverse", False)), bool(spec.get("version", False))
    text = str(spec)
    if text.startswith("-"):
        return text[1:], True, False
    return text, False, False


def apply_pipeline(items: Iterable[Any], options: dict[str, Any]) -> list[Any]:
    """Filter, order, trim, reshape and group -- in that order, all optional."""
    elements = [_as_element(item) for item in items]

    where = options.get("where")
    if where is not None:
        if not isinstance(where, dict):
            raise GeneratorError("'where' must be a mapping of field -> match")
        elements = [item for item in elements if _matches(item, where)]

    when = options.get("when")
    if when:
        elements = [item for item in elements if _truthy(str(when), item)]

    if options.get("unique"):
        key_field = str(options["unique"])
        seen: set[Any] = set()
        deduped = []
        for item in elements:
            marker = item.get(key_field)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        elements = deduped

    if options.get("sort"):
        by, reverse, numeric = _sort_spec(options["sort"])
        if by:
            def key(item: dict[str, Any]):
                value = item.get(by)
                if numeric:
                    return version_key(str(value or ""))
                # Mixed or missing values must not raise mid-build.
                return (value is None, str(value if value is not None else ""))
            elements.sort(key=key, reverse=reverse)
    if options.get("reverse"):
        elements.reverse()

    offset = int(options.get("offset") or 0)
    if offset:
        elements = elements[offset:]
    limit = options.get("limit")
    if limit is not None:
        elements = elements[: max(0, int(limit))]

    mapping = options.get("map")
    if mapping:
        if not isinstance(mapping, dict):
            raise GeneratorError("'map' must be a mapping of field -> template")
        mapped = []
        for item in elements:
            extra = {
                key: _render(value, item) if isinstance(value, str) else value
                for key, value in mapping.items()
            }
            mapped.append({**item, **extra})
        elements = mapped

    fields = options.get("fields")
    if fields:
        keep = [str(name) for name in fields]
        elements = [{key: item.get(key) for key in keep} for item in elements]

    group_by = options.get("group_by")
    if group_by:
        titles = options.get("group_titles") or {}
        groups: dict[Any, dict[str, Any]] = {}
        for item in elements:
            marker = item.get(str(group_by))
            group = groups.setdefault(marker, {
                "key": marker,
                "title": str(titles.get(marker, marker if marker is not None else "Other")),
                "items": [],
            })
            group["items"].append(item)
        return list(groups.values())

    return elements


# ---------------------------------------------------------------------------
# Runtime: declarations, references, and resolution over the raw config
# ---------------------------------------------------------------------------


class Runtime:
    """Runs the declared generators and expands every reference in the config."""

    def __init__(self, root: Path, raw: dict[str, Any], *, assets_dir: str = "assets",
                 enabled: bool = True) -> None:
        self.root = Path(root)
        self.raw = raw
        self.assets_dir = assets_dir
        self.enabled = enabled
        self.warnings: list[str] = []
        self.git = GitRepo(self.root)
        self.results: dict[str, list[Any]] = {}
        self._running: list[str] = []

        declared = raw.get("generators") or {}
        if declared and not isinstance(declared, dict):
            raise GeneratorError("'generators' must be a mapping of name -> settings")
        self.declared: dict[str, dict[str, Any]] = {}
        for name, spec in declared.items():
            if isinstance(spec, str):  # `releases: git.changelog` shorthand
                spec = {"use": spec}
            if not isinstance(spec, dict) or not spec.get("use"):
                raise GeneratorError(
                    f"generator '{name}' needs a 'use:' naming which generator to run"
                )
            self.declared[str(name)] = dict(spec)

        if enabled:
            load_project_generators(self.root, self.warnings)

    # -- running ----------------------------------------------------------

    def run_spec(self, spec: dict[str, Any], name: str) -> list[Any]:
        use = str(spec["use"])
        options = {key: value for key, value in spec.items() if key not in _REF_KEYS}
        fn = _resolve_callable(use, self.root)
        ctx = Context(
            name=name, root=self.root, raw=self.raw, options=options,
            git=self.git, assets_dir=self.assets_dir, warnings=self.warnings,
            runtime=self,
        )
        try:
            produced = fn(ctx)
        except GeneratorError:
            raise
        except Exception as error:
            raise GeneratorError(f"{name} ({use}) failed: {error}") from error
        return apply_pipeline(produced or [], options)

    def value(self, name: str) -> list[Any]:
        """The named generator's result, computed once per build."""
        if name in self.results:
            return self.results[name]
        if name not in self.declared:
            known = ", ".join(sorted(self.declared)) or "none declared"
            raise GeneratorError(
                f"no generator named '{name}' under 'generators:'. Declared: {known}"
            )
        if name in self._running:
            cycle = " -> ".join([*self._running, name])
            raise GeneratorError(f"generators reference each other in a cycle: {cycle}")
        self._running.append(name)
        try:
            result = self.run_spec(self.declared[name], name)
        finally:
            self._running.pop()
        self.results[name] = result
        return result

    def run_all(self) -> dict[str, list[Any]]:
        """Every declaration, whether or not the page references it."""
        for name in self.declared:
            self.value(name)
        return dict(self.results)

    # -- references -------------------------------------------------------

    def _reference(self, node: dict[str, Any]) -> list[Any]:
        if "from" in node:
            name = str(node["from"])
            base = self.value(name)
            overrides = {key: value for key, value in node.items() if key not in _REF_KEYS}
            if not overrides:
                return list(base)
            # Options the generator itself understands mean a different fetch;
            # pipeline-only options just reshape the result we already have.
            refetch = {key: value for key, value in overrides.items()
                       if key not in PIPELINE_KEYS}
            if refetch:
                merged = {**self.declared[name], **overrides}
                return self.run_spec(merged, f"{name} (inline)")
            return apply_pipeline(base, overrides)
        return self.run_spec(node, f"inline:{node['use']}")

    def resolve(self, node: Any, *, path: str = "") -> Any:
        """Deep-copy the config, replacing every generator reference with its elements.

        A reference in a mapping value position becomes the list; one that is
        itself a list entry is spliced into the surrounding list, so generated
        and hand-written entries can sit side by side.
        """
        if isinstance(node, dict):
            if _is_reference(node):
                if not self.enabled:
                    return []
                return self._reference(node)
            return {
                key: (value if key == "generators"
                      else self.resolve(value, path=f"{path}.{key}" if path else str(key)))
                for key, value in node.items()
            }
        if isinstance(node, list):
            out: list[Any] = []
            for index, item in enumerate(node):
                if isinstance(item, dict) and _is_reference(item):
                    if self.enabled:
                        out.extend(self._reference(item))
                    continue
                out.append(self.resolve(item, path=f"{path}[{index}]"))
            return out
        return node


def _is_reference(node: dict[str, Any]) -> bool:
    """``{from: releases}`` or ``{use: git.tags, limit: 3}`` and nothing else."""
    if "from" in node:
        return isinstance(node["from"], str)
    return "use" in node and isinstance(node["use"], str)
