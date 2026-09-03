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

## Install (once, on this machine)

```bash
python -m pip install -e C:/Users/Matthijs/ModPageConstructor
```

If `modpage` is not on your PATH afterwards, `python -m modpage <args>` works
identically.

## Use (in each mod repo)

```bash
cd path/to/your-mod-repo
modpage init            # writes a commented modpage.yml + assets/ folders
modpage build           # renders all three targets
modpage build -t readme # or just one
modpage build -t all    # also the opt-in curseforge-html page (see below)
modpage build --check   # exit 1 if a generated file is out of date (CI)
modpage sections        # print the shared section skeleton
```

`modpage build` only rewrites files whose content actually changed, so it is safe
to run on every commit.

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
| `faq` | | `q` / `a` pairs |
| `credits` | | Markdown body |
| `license` | | Defaults to the top-level `license:` |

Add your own with `custom_sections:` and place them with `after: features`.
Reorder everything with a top-level `order:` list (it must still contain
`dependencies` and `incompatibilities`).

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
