# ModPageConstructor

One template, one config, one asset folder — three published pages.

`modpage` builds a mod's **GitHub README**, its **Modrinth description** and its
**CurseForge description** from a single `modpage.yml` in the mod's own repo. Every mod
gets the same page skeleton, so `Dependencies` and `Incompatibilities` are always
a banner and a straight answer, even when the answer is "none".

```
your-mod-repo/
  modpage.yml            <- everything the pages say
  assets/
    banners/header.png   <- title banner
    banners/dependencies.png
    banners/incompatibilities.png
    gallery/overview.png
  README.md              <- generated
  dist/modrinth.md       <- generated
  dist/curseforge.md     <- generated
```

## Install

There is no PyPI package; the tool installs straight from this repository. Pin
a release tag so a template change here never rewrites a page you did not ask
to change:

```bash
python -m pip install "git+https://github.com/mattjesmc/ModPageConstructor@v0.4.0"
```

Or run it without installing anything, with [uv](https://docs.astral.sh/uv/)
or `pipx`:

```bash
uvx --from "git+https://github.com/mattjesmc/ModPageConstructor@v0.4.0" modpage build
pipx run --spec "git+https://github.com/mattjesmc/ModPageConstructor@v0.4.0" modpage build
```

If `modpage` is not on your PATH afterwards, `python -m modpage <args>` works
identically. Working on the generator itself? `python -m pip install -e .` from
a checkout gives an editable install.

## Use (in each mod repo)

```bash
cd path/to/your-mod-repo
modpage init            # writes a commented modpage.yml + assets/ folders
modpage build           # renders all three targets
modpage build -t readme # or just one
modpage build -t all    # also the opt-in curseforge-html page (see below)
modpage build --check   # exit 1 if a generated file is out of date (CI)
modpage sections        # print the shared section skeleton
modpage generators      # list element generators + preview what yours produce
```

`modpage build` only rewrites files whose content actually changed, so it is safe
to run on every commit.

## Keeping the pages fresh with GitHub Actions

`modpage init` also writes `.github/workflows/modpage.yml` (skip it with
`--no-workflow`), which rebuilds the
pages on every push to `main` and on every `v*` tag and commits whatever
changed. Tag a release and the changelog on all three pages follows it; drop a
screenshot in `assets/gallery/` and the gallery does too. A commit made by the
workflow does not trigger the workflow again, so there is no loop.

The whole file is a checkout plus this repository's composite action:

```yaml
permissions:
  contents: write

jobs:
  pages:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0     # generators read tags and history
          ref: ${{ github.event.repository.default_branch }}
      - uses: mattjesmc/ModPageConstructor@v0.4.0
```

`fetch-depth: 0` matters: a shallow clone has no tags and one commit, so the
`git.*` generators would quietly return nothing. `ref:` matters on tag pushes,
where the checkout would otherwise be a detached HEAD with no branch to commit
to.

The action takes a few inputs, all optional:

| Input | Default | Does |
| --- | --- | --- |
| `config` | `modpage.yml` | Path to the config, relative to the repo root |
| `targets` | default set | Space-separated targets, e.g. `readme modrinth` or `all` |
| `mode` | `commit` | `commit` pushes changes; `check` fails when a page is stale; `build` only writes the files |
| `commit-message` | `docs: regenerate mod pages` | Message for the commit |
| `offline` | `false` | Use `.modpage/cache/` only; never fetch vanilla textures |
| `python-version` | `3.12` | Interpreter to run with |

It exposes one output, `changed`, for steps that want to react. Use
`mode: check` on pull requests if you would rather contributors run
`modpage build` themselves. The vanilla texture cache is restored between runs
with `actions/cache`, so the first build after a new recipe fetches a handful of
PNGs and later builds fetch nothing.

Version pinning is the one thing to keep an eye on. The `@v0.4.0` in `uses:` is
the generator version the pages are built with, and `init` writes whichever
version wrote the scaffold. Bump it on purpose, then look at the resulting
commit.

## The shared skeleton

Sections render in this order. Ones with no content are skipped — except the two
marked *always*, which fall back to their `empty_text`.

| Section | Always | Shape |
| --- | --- | --- |
| `about` | | Markdown body |
| `features` | | List of `title` / `description` (+ optional `image`) |
| `gallery` | | Images with captions |
| `recipes` | | Rendered from the repo's recipe JSON — see below |
| `dependencies` | **yes** | `required` / `optional` / `bundled` tables |
| `incompatibilities` | **yes** | `known` table: mod, conflict, workaround |
| `installation` | | Markdown body |
| `configuration` | | Markdown body |
| `changelog` | | Release entries, usually generated -- see below |
| `faq` | | `q` / `a` pairs |
| `credits` | | Markdown body |
| `license` | | Defaults to the top-level `license:` |

Any section can also carry `elements:` -- a list drawn by its `layout:` rather
than by a macro written for that one section. See *Element generators*.

Add your own with `custom_sections:` and place them with `after: features`.
Reorder everything with a top-level `order:` list (it must still contain
`dependencies` and `incompatibilities`).

## Contents list

A page with ten banners is a long scroll. Add a top-level `toc:` block and every
target gets a contents list between the header and the first section, listing the
sections that target actually renders:

```yaml
toc:
  title: Contents      # heading above the list; `false` for none
  style: list          # list (bulleted) | inline (one centred row)
  numbered: false      # 1. 2. 3. instead of bullets
  skip: [license]      # section ids to leave out
  min_sections: 2      # skip the list entirely below this many entries
  targets: [readme]    # default: every target
  # banner: banners/contents.png   # auto-detected, like any section banner
```

`toc: true` takes every default; leaving `toc:` out means no list at all, so
existing pages are unchanged until you ask for one.

Entries link to `#<section-id>`, and each section header now carries that
anchor whether it renders as a banner or a plain heading. CurseForge's Markdown
mode strips the HTML an anchor needs, so `dist/curseforge.md` gets the same list
as plain text — an overview of the page rather than a jump list.


## Element generators

A page repeats what the repo already knows. The version in the changelog is the
version on the tag; the screenshots in the gallery are the files in
`assets/gallery/`; the loaders in the support table are the loaders three lines
higher in the same config. **Element generators** name that source once and let
the page follow it.

A generator returns *elements* -- plain dicts. Declare one under `generators:`
and reference it with `from:` wherever a list belongs:

```yaml
generators:
  releases:
    use: git.changelog        # every tagged release, with its commits
    match: "v*"
    limit: 5
  screenshots:
    use: files.glob
    pattern: "gallery/*.png"

sections:
  gallery:
    images: {from: screenshots}
  changelog:
    elements: {from: releases}
    collapsed: true
```

Tag `v1.3.0` and the changelog gains a release; drop a PNG in `assets/gallery/`
and the gallery gains a screenshot. Neither touches `modpage.yml`.

```bash
modpage generators          # what is available, and what yours produce right now
modpage build --no-generators   # leave every generated list empty
```

### Where a reference can go

`{from: <name>}` stands in for a list anywhere the config expects one. As a
*value* it becomes the list; as a *list entry* it splices, so generated and
hand-written entries sit side by side:

```yaml
sections:
  features:
    items:
      - title: Written by hand
        description: Still exactly as it was.
      - from: highlights        # ...and the rest generated
        limit: 3
```

Templates see every declared generator as `gen.<name>`, whether or not a
section uses it, so a custom template can lay them out its own way.

### Shaping what comes back

A generator fetches; it never formats. Every result -- at the declaration and
again at each reference -- passes through the same pipeline, applied in this
order:

| Key | Does |
| --- | --- |
| `where` | Keep elements matching `{field: value}`, or `{field: {op: value}}` with `eq`, `ne`, `in`, `not_in`, `contains`, `matches`, `gt`, `gte`, `lt`, `lte`, `exists` |
| `when` | Keep elements for which a Jinja expression over the element is truthy |
| `unique` | Drop later elements repeating a field |
| `sort` | `date`, `-date` for descending, or `{by: version, version: true}` for `1.10` after `1.9` |
| `reverse` | Flip the order |
| `offset` / `limit` | Trim |
| `map` | Add or overwrite fields; each value is a Jinja template over the element |
| `fields` | Keep only these keys |
| `group_by` | Fold into `{key, title, items}` groups |

```yaml
generators:
  highlights:
    use: git.commits
    types: [feat]             # a git.commits option: changes what is fetched
    limit: 5                  # a pipeline option: shapes what came back
    map:
      title: "{{ title }}"
      description: "shipped {{ date | date('%b %Y') }}"
```

Because the pipeline is available at the reference site too, one declaration
serves several sections: the same `releases` can be five entries in the
changelog and one line in the header.

### The built-in generators

| Name | Returns |
| --- | --- |
| `git.changelog` | One element per release: version, date, url, and its commits grouped into `Added` / `Fixed` / `Changed` / `Removed` by their Conventional Commit type |
| `git.tags` | Every tag as a version element |
| `git.commits` | Commits, with `type`, `scope` and `breaking` split out of the subject |
| `git.contributors` | Everyone who has committed, most commits first |
| `changelog.file` | A hand-written `CHANGELOG.md`, parsed into the same shape as `git.changelog` |
| `files.glob` | Files in the tree -- gallery images, slider slides, showcase art |
| `data.file` | Elements out of JSON or YAML in the repo (`fabric.mod.json`, a data pack) |
| `config.pluck` | Objects from elsewhere in `modpage.yml`, by dotted path |
| `config.versions` | The `minecraft:` block as one element per version or loader |

Each takes its own options -- `modpage generators` prints them with a one-line
summary of what each does. A repo without git (an exported tarball, a fresh
`init`) is not an error: the git generators warn once and return nothing, and
the page still builds.

### Layouts

`elements:` is drawn by the section's `layout:`, so the same list renders
correctly on all three sites without a template edit:

| Layout | Shape |
| --- | --- |
| `list` | Bulleted, `**title** — description`; nested `items` become sub-bullets |
| `cards` | Image beside text, or a bold heading and a paragraph |
| `table` | Pipe table; name the fields with `columns:` |
| `gallery` | Centred images with captions |
| `slider` | The same, until a target can carry a real carousel |
| `changelog` | Version, date and grouped bullets |
| `definition` | Bold term, paragraph body |

`collapsed: true` folds the whole list behind a `<details>` summary on the
targets that support one. `columns:` takes field names or
`{field: version, title: Minecraft}` pairs.

```yaml
custom_sections:
  - id: support
    title: Supported versions
    after: about
    layout: table
    columns: [{field: version, title: Minecraft}, {field: description, title: Loaders}]
    elements: {from: support}
```

### Writing your own

Drop a module in `.modpage/generators/` and decorate a function. It is imported
at build time, exactly as this repo's templates are read at build time -- there
is no sandbox, and none is implied:

```python
# .modpage/generators/showcase.py
from modpage.generators import generator


@generator("mymod.showcase")
def showcase(ctx):
    """One card per showcase image, captioned from the file name."""
    for path in ctx.glob("showcase/*.png"):
        yield {"title": path.stem.replace("_", " ").title(),
               "image": f"showcase/{path.name}"}
```

```yaml
generators:
  cards: {use: mymod.showcase}
```

`ctx` is the whole of what a generator may read: `ctx.root`, `ctx.raw` (the
config as written), `ctx.options` (its own settings, via `ctx.opt`, `ctx.opt_int`
and `ctx.opt_list`), `ctx.git` (tags, commits, remote), plus `ctx.glob`,
`ctx.read_text`, `ctx.load_data` and `ctx.pluck`. Call `ctx.warn` for something
worth saying and `ctx.fail` for a config a human has to fix. Return dicts,
strings, paths, or anything with an `as_element()`; the pipeline takes it from
there. A one-off script works too, without registering: `use: tools/pages.py:build`.

## Recipes

Declare `sections: { recipes: {} }` and `modpage build` reads the mod's own
recipe files — `data/<namespace>/recipe/*.json` (and the older `recipes/`) — and
draws each one as a small crafting card in `assets/recipes/`. The section is
folded behind a `<details>` and laid out as a compact grid, so a mod with thirty
recipes costs the reader one line of page.

- **Types**: shaped, shapeless, smelting/blasting/smoking/campfire,
  stonecutting, smithing. Unknown or modded types are skipped rather than
  guessed at.
- **JSON shapes**: `result` as a bare id, `{"item": …}` or `{"id": …}`;
  ingredients as an object, a bare string, or a list of alternatives — so 1.16
  through 1.21+ files parse without a version switch.
- **GIFs**: a slot holding a tag (`#minecraft:planks`) or a list of alternatives
  cycles through them, one second per frame, exactly like a recipe viewer in
  game. Single-item recipes stay a static PNG.
- **Compact by construction**: the grid is trimmed to its filled bounding box, so
  a two-ingredient recipe draws a 1x2 grid, not an empty 3x3.
- **Counts**: result and ingredient counts are drawn as Minecraft-style badges.

**Modded recipe types** are skipped by default — the tool will not guess at a
type it does not know — but it says so, with a count. Teach it one with
`custom_types`, naming the layout and where the result comes from:

```yaml
custom_types:
  "armorpieces:smithing_decoration":
    layout: smithing   # shaped | shapeless | single | smithing
    result: base       # the recipe computes its result in code; show the base item
```

Captions come from each recipe's file name, minus the prefix they all share, so
they are unique even when a dozen recipes make the same item. Override any of
them with `labels: {<recipe id>: "Name"}`.

Textures resolve in this order: the mod's own item/block model JSON, then its
`textures/item` and `textures/block`, then vanilla. Vanilla textures and tag
contents are fetched once from [misode/mcmeta](https://github.com/misode/mcmeta)
and cached in `.modpage/cache/`, so later builds need no network — pass
`--offline` to require the cache. Anything unresolved is drawn as the vanilla
missing-texture checker and reported as a warning, so a broken id is visible
rather than silent. A handful of vanilla items (shields, banners, blocks whose
icon is a 3D render) have no flat texture to find at all — point those at your
own PNG with `icons: {minecraft:shield: icons/shield.png}`.

```bash
modpage recipes             # just the images
modpage build --no-recipes  # skip re-rendering them
```

Prior art worth knowing about, none of which fit a build-time pipeline:
[ReciPic](https://github.com/NeRdTheNed/ReciPic) and
[Advanced Recipe Generator](https://github.com/Flow86/Advanced-Recipe-Generator-Mod)
are in-game mods that need the client running;
[Recipe Image Generator](https://www.curseforge.com/minecraft/mc-mods/recipe-image-generator)
does images and GIFs but is likewise a runtime mod;
[Shapescape's generator](https://shapescape-recipe-image-generator.readthedocs.io/)
is Bedrock-oriented and has no GIF support.

## Banners

Each section opens with a banner image. Drop a file at
`assets/banners/<section-id>.png` and it is picked up automatically — no config
line needed. `.png`, `.webp`, `.jpg`, `.gif` and `.svg` all work. A section with
no banner file falls back to a plain `## Heading`, so a repo can ship before its
art does.

Need placeholders to start with:

```bash
python tools/make_placeholder_banners.py path/to/your-mod-repo/assets/banners "Mod Name"
```

## Per-site markup

Each site keeps a different amount of what it is given, so the same skeleton
is rendered three ways:

| Target | File | Markup |
| --- | --- | --- |
| `readme` | `README.md` | GitHub Markdown plus the HTML GitHub allows (`<details>`, `<p align>`, `<img width>`) |
| `modrinth` | `dist/modrinth.md` | Markdown plus Modrinth's HTML whitelist -- centred banners, sized images, folded recipes |
| `curseforge` | `dist/curseforge.md` | Markdown with **no HTML at all** |

CurseForge's description editor has two modes, **WYSIWYG** and **Markdown**,
and no HTML source view. Its Markdown mode escapes raw HTML rather than
rendering it, so the Modrinth page pasted there only half works: lists, tables
and bold text render, but every centred banner, badge row and the recipe grid
show up as tag soup or vanish. `dist/curseforge.md` therefore uses plain
Markdown images (`![alt](url)`), `[![badge](img)](url)` badges and pipe tables
for the recipe grid. Switch the editor to Markdown and paste the whole file.

Two things Markdown alone cannot do: centre content or resize images. Banners
show at their natural pixel width on CurseForge, so export them at the width
you want them seen at (the example uses 720px for the header and 480px for
section banners). Recipes are not folded, because there is no `<details>`.

The old HTML page is still available as the opt-in `curseforge-html` target
(`modpage build -t curseforge-html`). Pasting its *source* into the editor
does not work; the one route that does is to open the file in a browser,
select all, copy, and paste the rendered result into the WYSIWYG editor.

## Asset URLs

The README uses repo-relative paths. Modrinth and CurseForge cannot resolve
those, so set the raw host once:

```yaml
assets:
  base_url: https://raw.githubusercontent.com/USER/REPO/main/
```

`modpage build` warns if it is missing, and warns for any image path that has no
file on disk.

## Customising the template

Copy the packaged templates and edit them per repo:

```bash
mkdir -p .modpage/templates/default
cp -r <this repo>/src/modpage/templates/default/* .modpage/templates/default/
```

Anything under `.modpage/templates/` in a mod repo takes precedence over the
packaged version. Point `template: <name>` at a differently named folder to keep
several looks side by side.

## Example

`examples/example-mod/` is a complete repo — config, banners, and the three
generated outputs. Build it with:

```bash
modpage build -c examples/example-mod/modpage.yml
```
