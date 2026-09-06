# Changelog

Releases are `major.minor.patch`. The first two numbers are the *series*; a
patch never changes what `modpage.yml` means, a new series may. Every series
entry below says what changed in the config format. See *Versioning* in the
README.

## 0.4.2

- `modpage init` writes the config series (`modpage: "0.4"`) into the
  scaffold and pins the series tag (`@v0.4`) in the workflow it drops.
- `modpage build` checks the `modpage:` line against the running version:
  a newer series is an error, an older one a warning, none is silent.
- Release workflow: a `vX.Y.Z` tag moves the `vX.Y` series tag and publishes
  a GitHub release, after the example builds clean.

## 0.4.1

- Stack counts on recipe images are drawn from a built-in pixel font instead
  of whichever system font Pillow found, so every platform renders the same
  pixels. Images are only rewritten when their decoded frames change.
- GitHub Actions dependencies moved to their Node 24 majors.

## 0.4.0

**Config changes in this series**

- New top-level `generators:` block and `{from: <name>}` references anywhere
  a list is expected. Existing configs without them are unaffected.
- New top-level `toc:` block for a contents list. Off unless present.
- Sections accept `elements:` and `layout:`.

**Also**

- Composite GitHub Action at the repository root; `modpage init` writes a
  workflow that runs it on pushes to `main` and on `v*` tags.
- Install from the git URL; there is no PyPI package.

## 0.2.0

- CurseForge renders as HTML-free Markdown (`dist/curseforge.md`); the HTML
  page is the opt-in `curseforge-html` target.
