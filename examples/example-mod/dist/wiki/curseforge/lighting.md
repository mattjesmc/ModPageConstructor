# Lantern Lights — Lighting

*How the light follows the lantern, and what it costs.*

![Loaders](https://img.shields.io/badge/Loader-Fabric_|_NeoForge-5b21b6?style=for-the-badge) ![Minecraft versions](https://img.shields.io/badge/Minecraft-1.21.1_|_1.20.1-5b21b6?style=for-the-badge)

**Loaders:** Fabric, NeoForge • **Minecraft:** 1.21.1, 1.20.1

---

## About

The vanilla light engine stores light per block, not per entity. Lantern Lights writes a
light value into the block the lantern is attached to and clears it when the lantern moves,
which is why the light follows without a tick of lag and without a light-emitting entity.

---

## Where it works

| Minecraft | Loaders |
| --- | --- |
| 1.21.1 | Fabric, NeoForge |
| 1.20.1 | Fabric, NeoForge |

---

## Dependencies

**None.** This mod is standalone — no other mods are required.

---

## Incompatibilities

**None known.** No conflicts have been reported.

---

## FAQ

**Does it cost anything at range?**

No. A lantern out of view is not lit, because nothing is asking.

**Does it work on a server?**

Yes; the light is written server-side and travels in the ordinary chunk update.
