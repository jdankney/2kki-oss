# LCF <-> XML round-trip notes

Tool: `build/liblcf/lcf2xml` (liblcf 0.8.1, built from `vendor/liblcf`).
Always pass `--2k --encoding CP932`.

## Byte-identical conversion

Converting a file to XML and back reproduces the original bytes exactly:

```
$ lcf2xml --2k --encoding CP932 Map0001.lmu      # -> Map0001.emu
$ lcf2xml --2k --encoding CP932 Map0001.emu      # -> Map0001.lmu
$ cmp Map0001.lmu <game>/Map0001.lmu             # identical
```

Verified for `Map0001` (LMU), `RPG_RT.ldb` (LDB) and `RPG_RT.lmt` (LMT):
all byte-identical.

`make extract` deliberately keeps the original binary LCF files in
`build/game/` (they are copied, never hardlinked) and touches them after
extraction. `make data` then only rebuilds XML files that were edited
afterwards. Result: all 3932 LCF files stay byte-exact until you change them.

## Known non-round-trippable fields

A *full* XML -> LCF rebuild of every file changes 37 of 3932 LCF files:

### 1. Trailing carriage return in strings (31 maps)

Some event message strings end with a literal `\r` (`0x0D`). liblcf's XML
writer emits it literally (`writer_xml.cpp:WriteString`, `case '\r'`).
XML parsers normalise literal CR to LF, so the rebuilt file loses it.

Example (`Map2053`):

```
$ diff xml/Map2053.emu <reconverted>.emu
< <string>[X]マップ地形を編集する^M
> <string>[X]マップ地形を編集する
```

Fix (not applied): change `writer_xml.cpp` to emit `&#xD;` for `\r`; the XML
parser then restores the byte. This is a one-line, spec-correct change but it
lives in the `vendor/liblcf` submodule, so it is left as an optional patch.

### 2. `save_count_2k3e` reset (6 maps)

`save_count_2k3e` is an RPG Maker 2003 English-only counter. It is written for
2k3e but zeroed when saving as RPG Maker 2000 (`--2k`). It is unused by this
game.

Maps: `Map2053, Map2059, Map2052, Map2056, Map2058, Map2060, Map2236, Map2284,
Map2820, Map2981, Map2983, Map2994, Map3093, Map3151, Map3154, Map3155,
Map3158, Map3159, Map3219, Map3421, Map3944, Map3945, Map4082, Map4083,
Map4085, Map4086, Map4088, Map4089, Map1042, Map1604, Map1969, Map2051,
Map2054, Map2055, Map2057, Map2813, Map2818` (the union of both classes).

Again: only matters if you rebuild those specific files from edited XML.

## Practical rule

- `make extract` — derive `build/game` + `xml/` from `original/`.
- edit `xml/*.emu`.
- `make data` — rebuild only the edited maps into `build/game`.
- `make run` — play.
- do **not** re-run `make extract` after editing XML (it would replace the
  rebuilt LCF with the originals; the XML edits are safe because `xml/` is
  cached, but `make data` would then see fresh LCF and skip).
