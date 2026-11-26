# Yume 2kki — open-source remake workspace

A reproducible pipeline for working on **Yume 2kki** (RPG Maker 2000) with the
open-source **EasyRPG Player** and **liblcf** toolchain.

The game ships thousands of binary LCF files. This workspace extracts them to
text XML so the game becomes diffable, editable and scriptable, while keeping a
runnable game directory.

> **Status:** extraction pipeline + Player build verified. All 3932 LCF files
> convert to XML and back **byte-identically**. The game boots in EasyRPG Player
> 0.8.1 from `build/game/`. Asset audit and map-tree prune are complete. The
> CR round-trip fix makes 3921/3930 maps byte-exact (the rest differ only in
> unused metadata). An English translation pipeline exists and the whole
> UI/real-room PC menu is translated; the dream-world text is a work in
> progress (~0.3% of 35k catalogue entries so far).

## Layout

```
original/                  read-only source (not committed)
  Yume2kki_ver0.129h/      base game 0.129h
  Yume2kki_ver0.129h_patch1/  patch 1 (applied on top)
vendor/liblcf/             LCF <-> XML library + lcf2xml (submodule)
vendor/Player/             EasyRPG Player (submodule)
scripts/extract.py         original/ -> build/game + xml/ (+ manifest, report)
scripts/rebuild.py         xml/ -> build/game LCF (only edited files)
scripts/verify.py          sanity checks
scripts/audit.py           asset reference audit (missing / RTP / unused)
scripts/map_tree.py        analyse / prune the RPG_RT.lmt map tree
scripts/translate.py       generate EasyRPG Player .po catalogues
translation/glossary.json  curated English glossary (terms + phrases)
translation/overrides.json curated whole-message translations
notes/encoding.md          CP932/CP866 filename mojibake evidence
notes/roundtrip.md         XML round-trip fidelity notes
notes/assets.md            asset audit findings
notes/map-tree.md          map tree cleanup findings
notes/translation.md       translation pipeline + English coverage
build/                     generated (gitignored)
xml/                       extracted XML, Map*.emu / RPG_RT.edb / RPG_RT.emt
```

## Quick start

Requirements: CMake ≥ 3.22, Ninja, a C++17 compiler, and the EasyRPG Player
deps (SDL2, pixman, libpng, zlib, fmt, freetype, harfbuzz, ICU, expat, inih).
On Debian/Ubuntu the packaged dev packages are enough.

```sh
make extract     # build lcf2xml, repair names, extract build/game + xml/
make verify      # sanity checks
make audit       # resolve every asset reference (missing / RTP / unused)
make map-tree    # analyse the map tree, write build/pruned/RPG_RT.emt
make prune-tree  # apply the pruned tree + rebuild RPG_RT.lmt
make translate   # generate translation/en/*.po
make player      # build EasyRPG Player -> build/player/easyrpg-player
make run         # play build/game
make run-en      # play build/game with the English translation
```

See `notes/assets.md` for the first audit results (~40 s): 965k references,
225 genuinely missing names, and 259 unique RTP files the game expects.

Then edit maps/database in `xml/` and rebuild just those:

```sh
$EDITOR xml/Map0001.emu
make data        # xml -> build/game/*.lmu (only edited files)
make run
```

## Important: filename encoding

The archive was unpacked with **CP932 bytes decoded as CP866**, so every
Japanese filename in `original/` is mojibake (`ВфВ▀2В┴Вл` = `ゆめ2っき`).
EasyRPG Player cannot find assets under those names, because the LDB/LMU still
reference the original CP932 names.

`make extract` repairs filenames (`CP866 -> CP932`) and writes
`[EasyRPG] Encoding=932` into `build/game/RPG_RT.ini` so the Player does not
fall back to codepage 1252.

Details and evidence: [`notes/encoding.md`](notes/encoding.md).

## Warnings

- `original/` is **read-only**. Never write to it. `build/game` gets copies of
  LCF files (not hardlinks) precisely so a rebuild cannot corrupt the source.
- EasyRPG Player auto-detects the engine as RPG Maker 2000. Pass
  `--encoding 932` manually if you run a game dir that lacks the patched ini.
- The game expects the **RPG Maker 2000 RTP** (19k references, 259 unique
  names: default SE, battle animations/backdrops). Install an RTP or pass
  `--rtp-path` / set `RPG2K_RTP_PATH`. Without it the game runs, but many
  sounds and battle backdrops are silent/missing.
- The 0.129h + patch1 combination is what gets extracted. If you add another
  patch, drop it under `original/` with `patch` in the directory name and
  re-run `make extract`.

## Licensing reality check

This repository contains **tooling**, not game content:

- EasyRPG Player: GPLv3. liblcf: MIT. Both are vendored as submodules.
- Yume 2kki assets, maps and events are © their respective creators.
  `read_me.txt` and `document/copyright.txt` explicitly prohibit
  redistribution and secondary use without permission.

Therefore `original/`, `build/` and `xml/` are gitignored. Every contributor
must supply their own copy of the game. If the goal is a *fully redistributable*
open-source game, the assets and map data have to be replaced with original or
permissively licensed content — that is a separate, much larger content effort.

## Next steps

Done: asset audit (`notes/assets.md`), map-tree prune (`notes/map-tree.md`),
translation pipeline (`notes/translation.md`), CR round-trip fix
(`notes/roundtrip.md`).

1. **RTP:** install the RPG Maker 2000 RTP (or point `--rtp-path` at one) so
   default SE, battle animations and backdrops resolve.
2. **Finish the English pass:** map-by-map, starting with the PC menu and the
   first dream maps. ~4k unique lines remain.
3. **Map index:** graph of teleports, connections and common-event calls so the
   map tree is navigable in text.
4. **Original content:** track new/edited maps as XML diffs against the base,
   so the project can carry its own content without redistributing the originals.
