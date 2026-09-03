![Lantern Lights](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/header.png)

*Hand-placed lanterns that actually light the world.*

[![Modrinth](https://img.shields.io/modrinth/dt/lantern-lights?style=for-the-badge&logo=modrinth&logoColor=white&label=Modrinth&color=00AF5C)](https://modrinth.com/mod/lantern-lights) [![CurseForge](https://img.shields.io/badge/CurseForge-Download-F16436?style=for-the-badge&logo=curseforge&logoColor=white)](https://www.curseforge.com/minecraft/mc-mods/lantern-lights) [![GitHub release](https://img.shields.io/github/v/release/Matthijs/lantern-lights?style=for-the-badge&logo=github&logoColor=white&label=Release&color=5b21b6)](https://github.com/Matthijs/lantern-lights/releases/latest) [![Loaders](https://img.shields.io/badge/Loader-Fabric_|_NeoForge-5b21b6?style=for-the-badge)](https://modrinth.com/mod/lantern-lights) [![Minecraft versions](https://img.shields.io/badge/Minecraft-1.21.1_|_1.20.1-5b21b6?style=for-the-badge)](https://modrinth.com/mod/lantern-lights) ![License](https://img.shields.io/badge/License-MIT-5b21b6?style=for-the-badge)

**Loaders:** Fabric, NeoForge • **Minecraft:** 1.21.1, 1.20.1 • **Side:** Client & Server

[GitHub](https://github.com/Matthijs/lantern-lights) • [Modrinth](https://modrinth.com/mod/lantern-lights) • [CurseForge](https://www.curseforge.com/minecraft/mc-mods/lantern-lights) • [Issues](https://github.com/Matthijs/lantern-lights/issues)

---

![About](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/about.png)

Lantern Lights replaces the vanilla lantern with a dynamic light source that
follows the block it is attached to, so corridors, mineshafts and boats stay
lit without a single command block.

It is a drop-in change: no new items, no world data, nothing to migrate.

---

![Features](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/features.png)

- **Dynamic lighting** — Lanterns emit light along the path they are carried.
- **Zero config required** — Sensible defaults out of the box; every value is tunable.
- **Server-side friendly, with client-only rendering**

---

![Gallery](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/gallery.png)

![A lit mineshaft, no torches placed](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/gallery/overview.png)

*A lit mineshaft, no torches placed*

---

![Recipes](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/recipes.png)

Every recipe below is generated straight from the mod's data files.

| ![Smelting recipe for Glow Ingot From Smelting](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/recipes/lantern_lights__glow_ingot_from_smelting.png) | ![Crafting recipe for Glow Lantern From Planks](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/recipes/lantern_lights__glow_lantern_from_planks.gif) | ![Crafting recipe for Lantern](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/recipes/lantern_lights__lantern.png) |
| :---: | :---: | :---: |
| Glow Ingot From Smelting *(Smelting)* | Glow Lantern From Planks | Lantern |
| ![Stonecutting recipe for Lantern Block Cut](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/recipes/lantern_lights__lantern_block_cut.gif) | ![Shapeless recipe for Lantern Dust](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/recipes/lantern_lights__lantern_dust.png) |
| Lantern Block Cut *(Stonecutting)* | Lantern Dust *(Shapeless)* |

---

![Dependencies](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/dependencies.png)

**Required**

| Mod | Version | Notes |
| --- | --- | --- |
| [Fabric API](https://modrinth.com/mod/fabric-api) | >=0.100.0 | Fabric builds only |

**Optional**

| Mod | Version | Notes |
| --- | --- | --- |
| [Mod Menu](https://modrinth.com/mod/modmenu) | — | In-game config screen |

---

![Incompatibilities](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/incompatibilities.png)

| Mod | Conflict | Workaround |
| --- | --- | --- |
| [Shimmer](https://modrinth.com/mod/shimmer) | Both patch the light engine | Disable Shimmer's dynamic lights |

---

![Installation](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/installation.png)

1. Install [Fabric Loader](https://fabricmc.net/use/) or NeoForge.
2. Drop `lantern-lights.jar` (and Fabric API on Fabric) into `mods/`.
3. Launch the game.

---

![Configuration](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/configuration.png)

The config lives at `config/lantern-lights.json`:

| Key | Default | Meaning |
| --- | --- | --- |
| `radius` | `12` | Light radius in blocks |
| `smooth` | `true` | Fade light in and out |

---

![FAQ](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/faq.png)

**Does it work on a server?**

Yes. Install it on both sides for the full effect.

**Does it break shaders?**

No, it uses the vanilla light engine.

---

![Credits](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/credits.png)

Textures by **@someone**. Thanks to the Fabric community for the light engine notes.

---

![License](https://raw.githubusercontent.com/Matthijs/lantern-lights/main/assets/banners/license.png)

Released under the **MIT** license.

---

Issues and pull requests are welcome.
