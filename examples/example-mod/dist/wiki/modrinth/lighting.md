<h1 align="center">Lantern Lights — Lighting</h1>

<p align="center"><i>How the light follows the lantern, and what it costs.</i></p>

<p align="center">
  <img alt="Loaders" src="https://img.shields.io/badge/Loader-Fabric_|_NeoForge-5b21b6?style=for-the-badge">
  <img alt="Minecraft versions" src="https://img.shields.io/badge/Minecraft-1.21.1_|_1.20.1-5b21b6?style=for-the-badge">
</p>

<p align="center">
<b>Loaders:</b> Fabric, NeoForge &nbsp;•&nbsp; <b>Minecraft:</b> 1.21.1, 1.20.1
</p>

---
<a id="about"></a>

## About

The vanilla light engine stores light per block, not per entity. Lantern Lights writes a
light value into the block the lantern is attached to and clears it when the lantern moves,
which is why the light follows without a tick of lag and without a light-emitting entity.

---
<a id="support"></a>

## Where it works

| Minecraft | Loaders |
| --- | --- |
| 1.21.1 | Fabric, NeoForge |
| 1.20.1 | Fabric, NeoForge |

---
<a id="dependencies"></a>

## Dependencies

**None.** This mod is standalone — no other mods are required.

---
<a id="incompatibilities"></a>

## Incompatibilities

**None known.** No conflicts have been reported.

---
<a id="faq"></a>

## FAQ

**Does it cost anything at range?**

No. A lantern out of view is not lit, because nothing is asking.

**Does it work on a server?**

Yes; the light is written server-side and travels in the ordinary chunk update.
