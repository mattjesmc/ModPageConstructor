"""``modpage`` command line: build the pages for one mod repo from its config."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import config as config_mod
from . import generators as generators_mod
from . import render as render_mod
from .config import CANONICAL_SECTIONS, ConfigError

SCAFFOLD = Path(__file__).parent / "scaffold" / "modpage.yml"
WORKFLOW_SCAFFOLD = Path(__file__).parent / "scaffold" / "workflow.yml"
#: The GitHub repository the composite action is published from, as `uses:` wants it.
ACTION_REPO = "mattjesmc/ModPageConstructor"

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def _supports_colour() -> bool:
    return sys.stdout.isatty()


def _paint(text: str, colour: str) -> str:
    return f"{colour}{text}{RESET}" if _supports_colour() else text


def _load(args: argparse.Namespace) -> config_mod.Config:
    path = Path(args.config).resolve() if args.config else config_mod.default_config_path()
    cfg = config_mod.load(path, run_generators=not getattr(args, "no_generators", False))
    for warning in cfg.warnings:
        print(_paint(f"  warning: {warning}", YELLOW))
    return cfg


def _resolve_targets(requested: list[str] | None) -> list[str]:
    """No ``-t`` renders the default set; ``-t all`` also includes the opt-in ones."""
    if not requested:
        return list(render_mod.DEFAULT_TARGETS)
    if "all" in requested:
        return list(render_mod.TARGETS)
    unknown = [t for t in requested if t not in render_mod.TARGETS]
    if unknown:
        raise ConfigError(
            f"unknown target(s): {', '.join(unknown)}. "
            f"Known: {', '.join(render_mod.TARGETS)}, all"
        )
    return requested


def _attach_recipes(cfg: config_mod.Config, args: argparse.Namespace) -> None:
    """Render recipe images and hand them to the recipes section, if declared."""
    section = cfg.section("recipes")
    if section is None or getattr(args, "no_recipes", False):
        return
    from . import recipe_render

    images, warnings = recipe_render.build_for(cfg, offline=getattr(args, "offline", False))
    section.data["images"] = images
    for warning in warnings:
        print(_paint(f"  warning: {warning}", YELLOW))
    if images:
        animated = sum(1 for image in images if image.animated)
        print(_paint(
            f"  recipes: {len(images)} rendered"
            f"{f' ({animated} animated)' if animated else ''}", DIM))


def cmd_build(args: argparse.Namespace) -> int:
    cfg = _load(args)
    _attach_recipes(cfg, args)
    results = render_mod.render_all(cfg, _resolve_targets(args.target))

    if args.stdout:
        for index, result in enumerate(results):
            if len(results) > 1:
                print(f"{'' if index == 0 else chr(10)}===== {result.target} =====")
            print(result.content, end="")
        return 0

    stale: list[str] = []
    for result in results:
        out_path = Path(args.out_dir).resolve() / out_name(result) if args.out_dir else result.path
        existing = out_path.read_text(encoding="utf-8") if out_path.is_file() else None

        for warning in result.warnings:
            print(_paint(f"  warning: {warning}", YELLOW))

        if args.check:
            if existing != result.content:
                stale.append(str(out_path))
                print(_paint(f"  stale: {out_path}", RED))
            else:
                print(_paint(f"  up to date: {out_path}", DIM))
            continue

        if existing == result.content:
            print(_paint(f"  unchanged: {out_path}", DIM))
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.content, encoding="utf-8", newline="\n")
        verb = "wrote" if existing is None else "updated"
        print(_paint(f"  {verb}: {out_path}", GREEN))

    if args.check and stale:
        print(_paint(f"\n{len(stale)} file(s) out of date. Run 'modpage build'.", RED))
        return 1
    return 0


def out_name(result: render_mod.Rendered) -> str:
    return result.path.name


def cmd_recipes(args: argparse.Namespace) -> int:
    """Render the recipe images without touching the pages."""
    cfg = _load(args)
    if cfg.section("recipes") is None:
        print(_paint("no 'recipes:' section in modpage.yml -- add one to enable this", RED))
        return 1
    from . import recipe_render

    images, warnings = recipe_render.build_for(cfg, offline=args.offline)
    for warning in warnings:
        print(_paint(f"  warning: {warning}", YELLOW))
    for image in images:
        kind = "gif" if image.animated else "png"
        detail = f" ({image.frames} frames)" if image.animated else ""
        print(f"  {image.recipe.id:<42} {kind}{detail}")
    print(_paint(f"{chr(10)}{len(images)} recipe image(s) in "
                 f"{cfg.assets_dir}/{args.out or 'recipes'}/", GREEN))
    return 0


def cmd_generators(args: argparse.Namespace) -> int:
    """List the generators available here, and preview what this repo's produce."""
    from . import generators as gen_mod

    registry = gen_mod.registry()
    print("Available generators:")
    print()
    for name in sorted(registry):
        print(f"  {name:<20} {_paint(gen_mod.describe(name), DIM)}")

    path = Path(args.config).resolve() if args.config else config_mod.default_config_path()
    if not path.is_file():
        print()
        print(_paint(f"(no {path.name} here, so nothing is declared yet)", DIM))
        return 0

    cfg = _load(args)
    if not cfg.generated:
        print()
        print(_paint("This repo declares none. Add a 'generators:' block to "
                     f"{path.name} and reference it with 'from:'.", DIM))
        return 0

    print()
    print(f"Declared in {path.name}:")
    print()
    declarations = cfg.raw.get("generators") or {}
    for name, elements in cfg.generated.items():
        spec = declarations.get(name) or {}
        use = spec.get("use") if isinstance(spec, dict) else spec
        count = _paint(f"{len(elements)} element(s)", GREEN if elements else YELLOW)
        print(f"  {name}  {_paint('via ' + str(use), DIM)}  -> {count}")
        for element in elements[: args.limit]:
            if isinstance(element, dict):
                label = (element.get("title") or element.get("name")
                         or element.get("version") or element.get("src") or "")
                keys = ", ".join(sorted(element)[:8])
                print(f"      - {str(label)[:52]:<52} {_paint(keys, DIM)}")
            else:
                print(f"      - {element}")
        if len(elements) > args.limit:
            print(_paint(f"      ... and {len(elements) - args.limit} more", DIM))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.dir).resolve()
    target = root / "modpage.yml"
    if target.exists() and not args.force:
        print(_paint(f"{target} already exists (use --force to overwrite)", RED))
        return 1
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCAFFOLD, target)
    print(_paint(f"wrote: {target}", GREEN))

    for sub in ("banners", "gallery"):
        directory = root / "assets" / sub
        directory.mkdir(parents=True, exist_ok=True)
        keep = directory / ".gitkeep"
        if not any(directory.iterdir()):
            keep.touch()
        print(_paint(f"ready:  {directory}", DIM))

    modpage_dir = root / ".modpage"
    modpage_dir.mkdir(exist_ok=True)
    (modpage_dir / ".gitignore").write_text("cache/\n", encoding="utf-8")

    if not args.no_workflow:
        workflow = root / ".github" / "workflows" / "modpage.yml"
        if workflow.exists():
            print(_paint(f"kept:   {workflow} (already present)", DIM))
        else:
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text(workflow_text(), encoding="utf-8", newline="\n")
            print(_paint(f"wrote:  {workflow}", GREEN))

    banner_names = ", ".join(f"{sid}.png" for sid, _ in CANONICAL_SECTIONS)
    print(
        "\nDrop a header banner at assets/banners/header.png, and section banners named:\n"
        f"  {banner_names}\n"
        "Any that are missing fall back to a plain text heading.\n"
        "Then run: modpage build"
    )
    return 0


def workflow_text() -> str:
    """The GitHub Actions workflow ``init`` drops into a mod repo, pinned to this release."""
    from . import __version__

    return (WORKFLOW_SCAFFOLD.read_text(encoding="utf-8")
            .replace("{action_repo}", ACTION_REPO)
            .replace("{version}", __version__))


def cmd_sections(args: argparse.Namespace) -> int:
    print("Shared page skeleton (in order):\n")
    for sid, title in CANONICAL_SECTIONS:
        marker = ""
        if sid in config_mod.ALWAYS_RENDER:
            marker = _paint(" [always rendered]", YELLOW)
        elif sid in config_mod.OPT_IN_SECTIONS:
            marker = _paint(" [opt in; content discovered from the repo]", DIM)
        print(f"  {sid:<18} {title}{marker}")
    print(
        "\nA section is skipped when it has no content, except the always-rendered ones,\n"
        "which fall back to their empty_text. Add your own with 'custom_sections'.\n"
        "Any section can carry 'elements:' -- usually a generator's output -- drawn\n"
        f"by its 'layout:' ({', '.join(config_mod.LAYOUTS)}). See 'modpage generators'."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modpage",
        description="Generate mod pages (README, Modrinth, CurseForge Markdown) from modpage.yml.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="render the pages for this repo")
    build.add_argument("-c", "--config", help="path to modpage.yml (default: ./modpage.yml)")
    build.add_argument(
        "-t", "--target", action="append",
        choices=[*render_mod.TARGETS, "all"],
        help=(f"target to render; repeatable (default: {', '.join(render_mod.DEFAULT_TARGETS)}; "
              "'all' adds the opt-in curseforge-html page)"),
    )
    build.add_argument("-o", "--out-dir", help="write every output into this directory instead")
    build.add_argument("--stdout", action="store_true", help="print instead of writing files")
    build.add_argument("--check", action="store_true",
                       help="exit 1 if any output is out of date (for CI)")
    build.add_argument("--no-recipes", action="store_true",
                       help="skip re-rendering recipe images")
    build.add_argument("--offline", action="store_true",
                       help="never fetch vanilla textures or tags; use the cache only")
    build.add_argument("--no-generators", action="store_true",
                       help="leave every generated list empty (skips git and file scans)")
    build.set_defaults(func=cmd_build)

    recipes = sub.add_parser("recipes", help="render just the recipe images")
    recipes.add_argument("-c", "--config", help="path to modpage.yml (default: ./modpage.yml)")
    recipes.add_argument("-o", "--out", help=argparse.SUPPRESS)
    recipes.add_argument("--offline", action="store_true",
                         help="never fetch vanilla textures or tags; use the cache only")
    recipes.set_defaults(func=cmd_recipes)

    gens = sub.add_parser("generators",
                          help="list the element generators and preview what they produce")
    gens.add_argument("-c", "--config", help="path to modpage.yml (default: ./modpage.yml)")
    gens.add_argument("-n", "--limit", type=int, default=5,
                      help="how many elements to preview per generator (default: 5)")
    gens.set_defaults(func=cmd_generators)

    init = sub.add_parser("init", help="scaffold modpage.yml and the assets folders")
    init.add_argument("dir", nargs="?", default=".", help="repo root (default: .)")
    init.add_argument("--force", action="store_true", help="overwrite an existing modpage.yml")
    init.add_argument("--no-workflow", action="store_true",
                      help="do not write the GitHub Actions workflow that rebuilds the pages")
    init.set_defaults(func=cmd_init)

    sections = sub.add_parser("sections", help="list the shared section skeleton")
    sections.set_defaults(func=cmd_sections)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as error:
        print(_paint(f"error: {error}", RED), file=sys.stderr)
        return 2
    except generators_mod.GeneratorError as error:
        print(_paint(f"error: {error}", RED), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
