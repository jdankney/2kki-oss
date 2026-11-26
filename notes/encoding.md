# Encoding findings (Yume 2kki 0.129h + patch1)

Status: confirmed, automated in `scripts/extract.py`.

## TL;DR

1. The game **data** uses **CP932 / Shift-JIS** (RPG Maker 2000).
2. The distributed **archive filenames** were unpacked with CP932 bytes wrongly
   decoded as **CP866** (DOS Cyrillic). Every Japanese filename is therefore
   mojibake on disk.
3. Disk filenames must be repaired (`CP866 -> bytes -> CP932`) or EasyRPG
   Player cannot find assets, because the LDB/LMU still reference the original
   CP932 names.
4. `RPG_RT.ini` has no `[EasyRPG] Encoding` key, and the Linux locale is not
   Japanese, so the Player falls back to codepage 1252. The extracted
   `build/game/RPG_RT.ini` gets `[EasyRPG] Encoding=932` appended.

## Evidence 1 — the game is CP932

`original/Yume2kki_ver0.129h/ВфВ▀2В┴Вл/RPG_RT.ini` is a CP932 text file:

```
$ file original/Yume2kki_ver0.129h/*/RPG_RT.ini
Non-ISO extended-ASCII text, with CRLF line terminators

$ iconv -f CP932 -t UTF-8 original/Yume2kki_ver0.129h/*/RPG_RT.ini
[RPG_RT]
GameTitle=ゆめ2っき
MapEditMode=2
MapEditZoom=1
WinW=320
WinH=240
```

Converting the binary database with `lcf2xml --2k --encoding CP932` yields
correct Japanese strings, e.g. charset names `うろつき`, `マップ到達`,
`デフォルト1`. Without `--encoding CP932` liblcf falls back to the locale
codec (1252 on this machine, `reader_util.cpp:GetLocaleEncoding`).

## Evidence 2 — filenames are CP866 mojibake

The game folder name on disk is `ВфВ▀2В┴Вл`. Encoding that UTF-8 string back to
CP866 gives the original CP932 byte sequence:

```
$ python3 -c "print('ВфВ▀2В┴Вл'.encode('cp866').hex())"
82e482df3282c182ab
$ python3 -c "print(bytes.fromhex('82e482df3282c182ab').decode('cp932'))"
ゆめ2っき
```

More examples (all round-trip cleanly):

| on disk (mojibake) | repaired |
|---|---|
| `ВфВ▀2В┴Вл` | `ゆめ2っき` |
| `КeГ}ГbГvБAСfН▐В╠ЧШЧpЛKЦё.txt` | `各マップ、素材の利用規約.txt` |
| `6МЕУ№Ч═09.png` | `6桁入力09.png` |
| `100.ПO_byВтВэВчВй (louder.wav` | `100.衆_byやわらか (louder.wav` |
| `changelog 103bВйВч105bВ▄В┼.txt` | `changelog 103bから105bまで.txt` |

Counts from `scripts/extract.py`: ~1155 path components need repair across
`CharSet/`, `ChipSet/`, `Picture/`, `Panorama/`, `Sound/`, `Music/`, `Battle/`
and `document/`.

The repair is only applied when a name contains non-ASCII characters **and**
encodes to CP866 **and** decodes as CP932 without replacement characters.
Already-correct UTF-8 Japanese names (e.g. the patch folder `ゆめ2っき/`) are
left untouched, which is why the check is needed.

## Evidence 3 — text files are mixed-encoding

Not every `.txt` is CP932:

- `original/Yume2kki_ver0.129h/КeГ}ГbГvБAСfН▐В╠ЧШЧpЛKЦё.txt` is CP932.
- `original/.../document/copyright.txt` is **UTF-8** (starts `e2 98 85` = `★`).
- `original/Yume2kki_ver0.129h_patch1/#このパッチについて.txt` is **UTF-8**.

Do not assume a single codec for docs; detect per file.

## Consequences for the remake

- `build/game/` must contain repaired names; `xml/` already contains UTF-8
  (lcf2xml writes `<?xml version="1.0" encoding="UTF-8"?>`).
- When converting XML back to LCF, pass `--encoding CP932` again, otherwise
  Japanese text is re-encoded with the wrong codec.
- Keep asset filenames case-sensitively consistent with the LDB strings: Linux
  is case-sensitive, Windows is not.

## Reproduction

```
make extract
python3 scripts/verify.py --game build/game --xml xml
```
