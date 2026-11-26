#!/usr/bin/env python3
"""Generate EasyRPG Player translation catalogues (.po) from the XML data.

EasyRPG Player reads translations from ``language/<lang>/``:

  rpg_rt.ldb.po         database strings (context ``actors.1.name`` etc.)
  rpg_rt.ldb.common.po  common-event message boxes
  rpg_rt.ldb.battle.po  troop message boxes
  rpg_rt.lmt.po         map names
  Map0001.po            message boxes of one map
  meta.ini              language metadata

Message ``msgid`` is the *whole message box* (lines joined with ``\\n``), or
the choice list, matching ``Translation::RewriteEventCommandMessage`` in
``vendor/Player/src/translation.cpp``.

The glossary (``translation/glossary.json``) seeds translations:

  {"meta": {...},
   "terms":   {"gold": "Dreams", ...},        # keyed by Terms field
   "strings": {"はい": "Yes", ...}}           # keyed by source text

Run ``make translate`` then ``make run-en``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# DB containers with per-object fields, and the fields worth translating.
CONTAINERS = [
    "actors", "classes", "skills", "items", "weapons", "armors", "enemies",
    "terrains", "attributes", "states", "animations", "chipsets",
]
FIELDS = {
    "name", "title", "description", "using_message1", "using_message2",
    "failure_message", "skill_name", "using_message",
    "easyrpg_battle2k3_message", "easyrpg_using_message",
    "message_actor", "message_enemy", "message_use", "message_affected",
    "message_recovery",
}
SKIP_VALUES = {"", "-", "default_term"}

# Event command codes (lcf::rpg::EventCommand::Code).
SHOW_MESSAGE = 10110
SHOW_MESSAGE_2 = 20110
SHOW_CHOICE = 10140
SHOW_CHOICE_OPTION = 20140
SHOW_CHOICE_END = 20141
CHANGE_HERO_NAME = 10610
CONDITIONAL_BRANCH = 12010
CHANGE_HERO_TITLE = 10620
MANIAC_SHOW_STRING_PICTURE = 3007


# ---------------------------------------------------------------------------
# PO writing
# ---------------------------------------------------------------------------
def po_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def write_po(path: Path, entries: list[tuple[str, str]], glossary: "Glossary",
             terms: bool = False, lang: str = "en") -> tuple[int, int]:
    seen: set[tuple[str, str]] = set()
    total = translated = 0
    lines = [
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: yume2kki-oss\\n"',
        f'"Language: {lang}\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        "",
    ]
    for ctx, msgid in entries:
        key = (ctx, msgid)
        if key in seen:
            continue
        seen.add(key)
        total += 1
        if terms and ctx.startswith("terms."):
            msgstr = glossary.term(ctx.split(".", 1)[1])
        else:
            msgstr = glossary.string(msgid)
        if msgstr:
            translated += 1
        if ctx:
            lines.append(f'msgctxt "{po_escape(ctx)}"')
        lines.append(f'msgid "{po_escape(msgid)}"')
        lines.append(f'msgstr "{po_escape(msgstr)}"')
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return total, translated


# ---------------------------------------------------------------------------
# PO reading / translation memory
# ---------------------------------------------------------------------------
_PO_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def po_unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _PO_ESCAPES.get(m.group(1), "\\" + m.group(1)), s)


def read_po(path: Path) -> list[tuple[str, str, str]]:
    """Return (msgctxt, msgid, msgstr) for every entry except the header.

    Handles multi-line strings (``msgid ""`` + continuation lines, as
    lcftrans writes them) and skips obsolete (``#~``) entries. ``#, fuzzy``
    translations are returned with an empty msgstr, as gettext treats them
    as untranslated. Plural forms are ignored (Player does not use them).
    """
    entries: list[tuple[str, str, str]] = []
    cur: dict[str, str] = {}
    cur_fuzzy = next_fuzzy = False
    field = ""

    def flush() -> None:
        if cur.get("msgid"):
            entries.append((cur.get("msgctxt", ""), cur["msgid"],
                            "" if cur_fuzzy else cur.get("msgstr", "")))
        cur.clear()

    for raw in path.read_text(encoding="utf-8-sig").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # Comments only appear between entries: the previous one is done.
            flush()
            field = ""
            if line.startswith("#,") and "fuzzy" in line:
                next_fuzzy = True
            continue
        if line.startswith('"'):
            if field:
                cur[field] += po_unescape(line[1:-1])
            continue
        keyword, _, rest = line.partition(" ")
        if keyword not in ("msgctxt", "msgid", "msgstr"):
            field = ""
            continue
        # A new entry starts at msgctxt, or at msgid unless only its own
        # msgctxt has been read so far.
        if keyword == "msgctxt" or (keyword == "msgid" and "msgid" in cur):
            flush()
            cur_fuzzy, next_fuzzy = next_fuzzy, False
        elif keyword == "msgid" and not cur:
            cur_fuzzy, next_fuzzy = next_fuzzy, False
        field = keyword
        cur[field] = po_unescape(rest.strip()[1:-1])
    flush()
    return entries


_DB_CTX = re.compile(r"^([a-z0-9_]+)\.\d+\.([a-z0-9_]+)$")


def norm_ctx(ctx: str) -> str:
    """``actors.1.name`` -> ``actors.name`` (Player tries both, in that order)."""
    m = _DB_CTX.match(ctx)
    return f"{m.group(1)}.{m.group(2)}" if m else ctx


class TranslationMemory:
    """Existing translations (e.g. a community .po set), keyed by msgid.

    Lookup prefers the same catalogue file (``Map0042.po``), then the same
    context and msgid in any other file of the set: a message moved
    between maps or into a common event between game versions still
    matches. Text that changed between versions does not match at all;
    nothing is guessed.
    """

    def __init__(self) -> None:
        self.by_file: dict[tuple[str, str, str], str] = {}
        # (ctx, msgid) -> file key it first came from
        self.anywhere: dict[tuple[str, str], tuple[str, str, str]] = {}
        self.used: set[tuple[str, str, str]] = set()
        self.files = 0

    def add_file(self, name: str, entries: list[tuple[str, str, str]]) -> None:
        self.files += 1
        fname = name.lower()
        for ctx, msgid, msgstr in entries:
            if not msgid or not msgstr:
                continue
            key = (norm_ctx(ctx), msgid)
            self.by_file[(fname, *key)] = msgstr
            self.anywhere.setdefault(key, (fname, *key))

    def load_dir(self, directory: Path) -> None:
        for po in sorted(directory.glob("*.po")):
            self.add_file(po.name, read_po(po))

    def lookup(self, po_name: str, ctx: str, msgid: str) -> tuple[str, str]:
        key = (norm_ctx(ctx), msgid)
        fkey = (po_name.lower(), *key)
        if fkey in self.by_file:
            self.used.add(fkey)
            return self.by_file[fkey], "import"
        if key in self.anywhere:
            origin = self.anywhere[key]
            self.used.add(origin)
            return self.by_file[origin], "import-moved"
        return "", ""

    def unused(self) -> int:
        """Imported translations this game version never asked for.

        A high number means the imported set targets a different game
        version (text that changed or was added after it)."""
        return len(self.by_file.keys() - self.used)


class Glossary:
    def __init__(self, path: Path, overrides: Path | None = None):
        data = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        self.meta = data.get("meta", {})
        self._messages = dict(data.get("messages", {}))
        if overrides and overrides.is_file():
            extra = json.loads(overrides.read_text(encoding="utf-8"))
            self._messages.update(extra.get("messages", {}))
        self._terms = {
            k.strip(" \u3000"): v for k, v in data.get("terms", {}).items()
        }
        self._strings = {
            k.strip(" \u3000"): v for k, v in data.get("strings", {}).items()
        }

    def term(self, field: str) -> str:
        return self._terms.get(field, "")

    def string(self, msgid: str) -> str:
        # Exact whole-message override wins (used for control-code menus).
        if msgid in self._messages:
            return self._messages[msgid]
        key = msgid.strip(" \u3000")
        if key in self._strings:
            return self._strings[key]
        # Multi-line message boxes / choice lists: translate line by line when
        # every line is a known phrase (e.g. "はい\nいいえ" -> "Yes\nNo").
        if "\n" in msgid:
            lines = msgid.split("\n")
            out = []
            for line in lines:
                k = line.strip(" \u3000")
                if k and k not in self._strings:
                    return ""
                out.append(self._strings.get(k, line))
            return "\n".join(out)
        return ""


# ---------------------------------------------------------------------------
# database strings
# ---------------------------------------------------------------------------
def db_entries(db: ET.Element) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for container in CONTAINERS:
        el = db.find(container)
        if el is None:
            continue
        for idx, obj in enumerate(list(el), 1):
            for field in obj:
                if field.tag not in FIELDS:
                    continue
                value = field.text or ""
                if value.strip() in SKIP_VALUES:
                    continue
                out.append((f"{container}.{idx}.{field.tag}", value))

    terms = db.find("terms/Terms")
    if terms is not None:
        for field in terms:
            value = field.text or ""
            if value.strip() in SKIP_VALUES:
                continue
            out.append((f"terms.{field.tag}", value))
    return out


# ---------------------------------------------------------------------------
# event messages
# ---------------------------------------------------------------------------
def commands_of(container: ET.Element) -> list[tuple[int, str, int, list[int]]]:
    cmds = []
    for ec in container.iter("EventCommand"):
        try:
            code = int(ec.findtext("code", "0") or 0)
        except ValueError:
            code = 0
        s = ec.findtext("string", "") or ""
        try:
            indent = int(ec.findtext("indent", "0") or 0)
        except ValueError:
            indent = 0
        params: list[int] = []
        for x in (ec.findtext("parameters", "") or "").split():
            try:
                params.append(int(x))
            except ValueError:
                params.append(0)
        cmds.append((code, s, indent, params))
    return cmds


def message_units(cmds) -> list[tuple[str, str]]:
    """Return (context, msgid) pairs exactly as Player looks them up."""
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(cmds):
        code, s, indent, params = cmds[i]

        if code == SHOW_MESSAGE:
            lines = [s]
            i += 1
            while i < len(cmds) and cmds[i][0] == SHOW_MESSAGE_2:
                lines.append(cmds[i][1])
                i += 1
            out.append(("", "\n".join(lines)))
            continue

        if code == SHOW_CHOICE:
            opts = []
            j = i + 1
            # Player uses the indent of the first command after ShowChoice.
            opt_indent = cmds[j][2] if j < len(cmds) else indent
            while j < len(cmds):
                c = cmds[j]
                if c[2] == opt_indent:
                    if c[0] == SHOW_CHOICE_OPTION and (c[3][0] if c[3] else 0) < 4:
                        opts.append(c[1])
                    if c[0] == SHOW_CHOICE_END:
                        break
                j += 1
            if opts:
                out.append(("", "\n".join(opts)))
            i += 1
            continue

        if code == CHANGE_HERO_NAME or (
            code == CONDITIONAL_BRANCH and len(params) > 2
            and params[0] == 5 and params[2] == 1
        ):
            if s:
                out.append(("actors.name", s))
        elif code == CHANGE_HERO_TITLE:
            if s:
                out.append(("actors.title", s))
        elif code == MANIAC_SHOW_STRING_PICTURE:
            if s.startswith("\x01"):
                end = len(s)
                for k in range(1, len(s)):
                    if s[k] in "\x01\x02\x03":
                        end = k
                        break
                term = s[1:end].replace("\r\n", "\n")
                if term:
                    out.append(("strpic", term))
        i += 1
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xml", default="xml")
    ap.add_argument("--out", default="translation")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--glossary", default="translation/glossary.json")
    ap.add_argument("--overrides", default="translation/overrides.json")
    ap.add_argument("--maps-limit", type=int, default=0)
    ap.add_argument("--no-maps", action="store_true")
    ap.add_argument("--stats", default="build/translation-stats.json")
    args = ap.parse_args()

    xml = Path(args.xml)
    out = Path(args.out) / args.lang
    glossary = Glossary(Path(args.glossary), Path(args.overrides))
    t0 = time.time()

    if not xml.is_dir():
        sys.exit(f"error: XML dir not found: {xml}")
    out.mkdir(parents=True, exist_ok=True)

    meta = glossary.meta
    lang_code = meta.get("code", args.lang)
    (out / "meta.ini").write_text(
        "[Language]\n"
        f"Name={meta.get('name', 'English')}\n"
        f"Description={meta.get('description', '')}\n"
        f"Code={lang_code}\n"
        f"Term={meta.get('term', 'Language')}\n"
        f"GameTitle={meta.get('game_title', 'Yume 2kki')}\n",
        encoding="utf-8",
    )

    totals = {"files": 0, "entries": 0, "translated": 0}
    per_file: dict[str, dict[str, int]] = {}

    def emit(name: str, entries, terms=False):
        n, t = write_po(out / name, entries, glossary, terms=terms, lang=lang_code)
        totals["files"] += 1
        totals["entries"] += n
        totals["translated"] += t
        per_file[name] = {"entries": n, "translated": t}

    # ---- database --------------------------------------------------------
    db = ET.parse(xml / "RPG_RT.edb").getroot().find("Database")
    if db is None:
        sys.exit("error: no <Database> in RPG_RT.edb")
    emit("rpg_rt.ldb.po", db_entries(db), terms=True)
    print(f"  db      {per_file['rpg_rt.ldb.po']}")

    ce = db.find("commonevents")
    if ce is not None:
        entries = []
        for ev in ce:
            entries += message_units(commands_of(ev))
        emit("rpg_rt.ldb.common.po", entries)
        print(f"  common  {per_file['rpg_rt.ldb.common.po']}")

    troops = db.find("troops")
    if troops is not None:
        entries = []
        for troop in troops:
            for page in troop.findall("pages/TroopPage"):
                entries += message_units(commands_of(page))
        emit("rpg_rt.ldb.battle.po", entries)
        print(f"  battle  {per_file['rpg_rt.ldb.battle.po']}")

    # ---- map names -------------------------------------------------------
    lmt = ET.parse(xml / "RPG_RT.emt").getroot()
    entries = []
    for mi in lmt.iter("MapInfo"):
        name = mi.findtext("name", "")
        if name:
            entries.append(("", name))
    emit("rpg_rt.lmt.po", entries)
    print(f"  lmt     {per_file['rpg_rt.lmt.po']}")

    # ---- map messages ----------------------------------------------------
    if not args.no_maps:
        maps = sorted(xml.glob("Map*.emu"))
        if args.maps_limit:
            maps = maps[: args.maps_limit]
        for i, path in enumerate(maps, 1):
            root = ET.parse(path).getroot()
            entries = []
            for page in root.iter("EventPage"):
                entries += message_units(commands_of(page))
            emit(path.stem + ".po", entries)
            if i % 500 == 0:
                print(f"  maps    {i}/{len(maps)} ({time.time() - t0:.1f}s)")
        print(f"  maps    {len(maps)} files")

    stats = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "lang": args.lang,
        "totals": totals,
        "files": per_file,
    }
    Path(args.stats).parent.mkdir(parents=True, exist_ok=True)
    Path(args.stats).write_text(json.dumps(stats, ensure_ascii=False, indent=1))

    pct = (100.0 * totals["translated"] / totals["entries"]) if totals["entries"] else 0
    print()
    print(f"entries    {totals['entries']}")
    print(f"translated {totals['translated']} ({pct:.2f}%)")
    print(f"files      {totals['files']} in {out}")
    print(f"stats      {args.stats}")
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
