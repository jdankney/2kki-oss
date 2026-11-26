# Initial content audit (0.129h + patch1)

Generated from `make extract` output. Numbers are cheap counts from the XML;
they are a starting point, not a full dependency audit.

## Snapshot

| item | value |
|---|---|
| base | `Yume2kki_ver0.129h` |
| patch | `Yume2kki_ver0.129h_patch1` (applied) |
| map files | 3930 |
| total files | 28978 placed |
| source size | ~6.9 GiB (hardlinked, so ~0 extra on disk) |
| XML size | ~2.6 GiB (3932 files) |

Patch application verified by hash: `build/game/RPG_RT.ldb`,
`build/game/RPG_RT.lmt` and `Map2841.lmu` all match the patch versions, not the
base versions.

## Database objects (`xml/RPG_RT.edb`)

| object | count |
|---|---|
| Actor | 100 |
| Skill | 4750 |
| Item | 100 |
| CommonEvent | 375 |
| Terrain | 140 |
| Animation | 450 |
| Chipset | 3250 |
| Switch | 5040 |
| Variable | 5000 |
| Enemy / Troop | 1 / 1 |

Title graphic `title3_2`, system graphic `system1`, gameover `dammy`.

## Map tree (`xml/RPG_RT.emt`)

- 4601 `MapInfo` entries, ids 0..4600.
- 3930 `.lmu` files, **all present in the tree**.
- **671 tree entries have no `.lmu` file** (1 root + 670 type=1 map nodes).
  This is the biggest structural cleanup item: either restore the maps or prune
  the tree.

## Asset directories (files on disk)

| dir | files |
|---|---|
| Picture | 10515 |
| Panorama | 5515 |
| CharSet | 2928 |
| Sound | 2431 |
| Music | 1866 |
| ChipSet | 1457 |
| System | 134 |
| Battle | 79 |
| FaceSet | 70 |
| Title | 7 |
| midi | 3 |
| Gameover | 1 |
| document | 18 |

1157 of these path components had to be repaired from CP866 mojibake.

## Good next audits

1. For every `character_name`, `title_name`, `system_name`, `battleback_name`,
   `battler_name`, picture/music/sound command and chipset name in the XML,
   check the target file exists (case-insensitively on Linux).
2. Cross-reference the 670 dangling `MapInfo` ids against teleport/escape
   commands to find whether they are still referenced.
3. Count unreferenced assets to estimate how much of the 6.9 GiB is dead weight.
