# Asset reference audit — findings

Script: `scripts/audit.py` (`make audit`). Raw output:
`notes/asset-audit.md` (generated) and `build/asset-audit.json` (full).

It walks the LDB, LMT and all 3930 LMU files, extracts every filename-shaped
reference, and resolves it against `build/game` case-insensitively.

## Headline numbers

| | occurrences | unique names |
|---|---:|---:|
| references | 965723 | |
| resolved | 944885 | |
| case-only mismatch | 1197 | 83 |
| **missing** | **1215** | **225** |
| provided by RTP | 19139 | 259 |
| invalid path (`../`) | 4 | 2 |
| dynamic (variable name) | 1767 | |
| placeholders skipped (`(OFF)`, `#null`) | 16693 | |

References per directory are dominated by event pages (CharSet: 654909) and
sound commands (Sound: 131635). Most of the volume is legitimate.

## The game needs the RPG Maker 2000 RTP

259 unique filenames (19139 occurrences) are standard RTP assets, not game
files. The biggest offender is `Sound`: 18451 references to default SE such as
`カーソル1`, `キャンセル1`, `ダメージ1`, `アイテム2`, `テレポート2`, `Bell`.
Plus battle animations (`打撃`, `爆発`, `雷`), backdrops (`草原`, `異空間`, …),
charsets (`乗り物`, …) and some music.

Classified using EasyRPG Player's own `vendor/Player/src/rtp_table.cpp`
manifest (Japanese + English + Don Miguel names).

**Action:** install the RPG Maker 2000 RTP (or point Player at one with
`--rtp-path` / `RPG2K_RTP_PATH`). Without it the game runs but many sounds and
all battle backdrops are missing.

## Genuine missing game assets (225 unique)

Most are dead references from years of collaboration. Groups:

### Empty LDB graphics (11)

- Battle animation ids 33, 199, 377 have an empty `animation_name`.
- Chipset ids 9, 10, 613, 615, 810, 1090, 1630, 2090 have an empty
  `chipset_name`.
These are database entries with no graphic; not recoverable and mostly unused.

### Error strings used as filenames (about 20)

Maps deliberately write a Japanese error message into a Picture/Panorama name
when a variable is invalid. They will always "fail" and are harmless:

- Panorama: `★MAPID:620 EVID:1[1] 未定義の処理が呼び出されました★` (x8),
  `★旧処理が呼び出されました (EVID:22[1]) ★`
- CharSet: `変数4270の値が不正です。移動先のマップ`,
  `変数4271の値が不正です。移動先のマップ`
- Picture: `ファイル　ファイル　…`, `x[]_pict#error`
- Sound: `デバッグの目印によく↑V↑の子達使っちゃう`,
  `音素材だとエラー落ちしません`, `聞こえていますか?`

### Broken relative paths (2)

- Panorama `../Picture/kamara_pic_sEV_6-44`
- Panorama `../Picture/kappa_closing`

Player blocks path traversal, so these are broken data (they probably meant
`Picture/...`).

### Corrupted names (contain literal `?`)

- Sound: `By????_575-otoyuka0_sasikae`, `octave_01_????`
- Music/Picture/Sound: `骰ｵ` is a lone CP932 fragment.

These were damaged before this release and cannot be recovered from this copy.

### Real missing assets (remainder, ~190)

Concentrated in `Music` (72), `Picture` (49), `ChipSet` (39), `Sound` (30),
`Panorama` (24). Examples: `ouri tileset9..13`, `qxy_chi_*`, `x[]_chip#*`,
`Kong_memorygame_X*`, `2i9_Picture_25a..d`, `pc yumegamen 03-1085..1092`.

They may be:
1. assets deleted before the 0.129h release (dead references),
2. part of a side patch not shipped here,
3. referenced with a typo / renamed file.

The full list is in `build/asset-audit.json` (`missing`, kind `missing`).
A follow-up pass could try fuzzy matching against the 6.9 GiB tree and the
`document/changelog*` files, but that is guesswork.

## Case-only mismatches are safe

83 unique (e.g. `mike_Charset_01` vs file `Mike_Charset_01.png`). EasyRPG
Player lowercases lookup paths (`filefinder.cpp: Utils::LowerCaseInPlace`), so
these resolve on every platform. Kept in the report for bookkeeping.

## Unused files (approximate)

Never referenced by LDB/LMT/LMU:

| dir | unused / total |
|---|---|
| Picture | 288 / 10515 |
| Panorama | 205 / 5515 |
| CharSet | 202 / 2928 |
| Sound | 1033 / 2431 |
| Music | 66 / 1866 |
| ChipSet | 47 / 1457 |

`Sound` has many unreferenced files and 1767 references are dynamic, so treat
this as an upper bound. These are candidates for a later "dead asset" prune,
but they cost nothing to keep for now.

## Recommendations

1. **Install the RTP** — highest impact for playability (SE, battle backdrops).
2. Do **not** chase error-string/`../` references; they are bugs in the data.
3. Treat the ~190 real missing names as optional; fix them only if a specific
   map looks broken.
4. Before any translation work, snapshot the reference index so renames can be
   checked mechanically (`make audit` is cheap: ~40 s).

## Reproduce

```sh
make audit
python3 scripts/audit.py --maps-limit 200   # quick sample
```
