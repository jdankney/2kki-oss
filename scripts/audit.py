#!/usr/bin/env python3
"""Audit asset references in the extracted Yume 2kki data.

Walks the LDB (database), LMT (map tree) and every LMU (map), collects every
filename-shaped reference, and resolves it against ``build/game``.

Outputs:
  notes/asset-audit.md      human summary (counts, missing, unused)
  build/asset-audit.json    full machine-readable result

Reference layouts come from EasyRPG Player:
  * string commands use ``com.string`` (see Game_Interpreter::Command*)
  * ShowBattleAnimation* use ``parameters[0]`` as a 1-based animation id
  * ChangeMapTileset uses ``parameters[0]`` as a 1-based chipset id

Missing references are split into:
  * ``missing``  - expected folder exists but the file is absent
  * ``noship``   - the folder is not shipped at all (RTP: Backdrop/Monster/Movie)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Directories the Player resolves filenames from (filefinder categories).
DIRS = [
    "Backdrop", "Battle", "CharSet", "ChipSet", "FaceSet", "GameOver",
    "Monster", "Music", "Panorama", "Picture", "Sound", "System", "Title",
    "Movie", "midi",
]

SKIP_NAMES = {"", "(off)", "(none)", "(null)", "(no)", "#null"}

# ChangeFaceGraphic etc. -> folder.  Layout verified in game_interpreter.cpp.
STR_CMDS = {
    10130: "FaceSet",   # ChangeFaceGraphic
    10630: "CharSet",   # ChangeSpriteAssociation
    10640: "FaceSet",   # ChangeActorFace
    10650: "CharSet",   # ChangeVehicleGraphic
    10660: "Music",     # ChangeSystemBGM
    10670: "Sound",     # ChangeSystemSFX
    10680: "System",    # ChangeSystemGraphics
    11110: "Picture",   # ShowPicture
    11510: "Music",     # PlayBGM
    11550: "Sound",     # PlaySound
    11560: "Movie",     # PlayMovie
    11720: "Panorama",  # ChangePBG
    13210: "Backdrop",  # ChangeBattleBG
}
ANIM_CMDS = {11210, 13260}   # ShowBattleAnimation, ShowBattleAnimation_B
CHIPSET_CMDS = {11710}       # ChangeMapTileset

# EasyRPG rtp_table_2k category -> Player folder.
RTP_CATEGORY = {
    "backdrop": "Backdrop", "battle": "Battle", "charset": "CharSet",
    "chipset": "ChipSet", "faceset": "FaceSet", "gameover": "GameOver",
    "monster": "Monster", "movie": "Movie", "music": "Music",
    "panorama": "Panorama", "picture": "Picture", "sound": "Sound",
    "system": "System", "title": "Title",
}


def load_rtp_table(path: Path) -> dict[str, set[str]]:
    """Parse the 2k RTP filename manifest out of Player's rtp_table.cpp."""
    names: dict[str, set[str]] = {}
    if not path.is_file():
        return names
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"rtp_table_2k\[\]\[5\]\s*=\s*\{(.*?)\n\};", text, re.S)
    if not m:
        return names
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        strings = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        if len(strings) < 2:
            continue
        folder = RTP_CATEGORY.get(strings[0])
        if not folder:
            continue
        for n in strings[1:]:
            names.setdefault(folder, set()).add(n.lower())
    return names

# ---------------------------------------------------------------------------
# asset index
# ---------------------------------------------------------------------------
class AssetIndex:
    def __init__(self, game: Path):
        self.dirs: dict[str, dict] = {}
        # Game folders are matched case-insensitively (e.g. GameOver/Gameover).
        actual = {p.name.lower(): p for p in game.iterdir() if p.is_dir()}
        for d in DIRS:
            base = actual.get(d.lower())
            entry = {
                "exists": base is not None and base.is_dir(),
                "stems": {},   # lower(relpath w/o ext) -> [(relpath w/o ext, Path)]
                "bases": {},   # lower(basename w/o ext) -> [(basename w/o ext, Path)]
                "files": [],   # [(relpath w/o ext, basename w/o ext, Path)]
            }
            if entry["exists"]:
                for p in base.rglob("*"):
                    if not p.is_file():
                        continue
                    rel = p.relative_to(base)
                    stem = str(rel.with_suffix("")).replace(os.sep, "/")
                    bname = rel.name.rsplit(".", 1)[0] if "." in rel.name else rel.name
                    entry["files"].append((stem, bname, rel))
                    entry["stems"].setdefault(stem.lower(), []).append((stem, rel))
                    entry["bases"].setdefault(bname.lower(), []).append((bname, rel))
            self.dirs[d] = entry

    def resolve(self, d: str, name: str) -> tuple[str, Path | None]:
        entry = self.dirs.get(d)
        if not entry or not entry["exists"]:
            return "noship", None
        key = name.replace("\\", "/")
        lower = key.lower()
        base = lower.rsplit("/", 1)[-1]
        for table, needle, exact in (
            (entry["stems"], lower, key),
            (entry["bases"], base, key.rsplit("/", 1)[-1]),
        ):
            cands = table.get(needle)
            if not cands:
                continue
            for stem, rel in cands:
                if stem == exact:
                    return "ok", rel
            return "case", cands[0][1]
        return "missing", None


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
class Audit:
    def __init__(self, index: AssetIndex, rtp_names: dict[str, set[str]] | None = None):
        self.index = index
        self.rtp_names = rtp_names or {}
        self.animations: list[str] = []
        self.chipsets: list[str] = []
        self.counts = {
            "refs": 0, "ok": 0, "case": 0, "missing": 0,
            "noship": 0, "rtp": 0, "invalid": 0, "dynamic": 0, "skipped": 0,
        }
        self.by_dir = {
            d: {"refs": 0, "ok": 0, "case": 0, "missing": 0, "noship": 0,
                "rtp": 0, "invalid": 0}
            for d in DIRS
        }
        self.used = {d: set() for d in DIRS}
        self.missing: dict[tuple[str, str], tuple[str, str, str]] = {}
        self.case: dict[tuple[str, str], tuple[str, str, str]] = {}

    # -- reference bookkeeping --------------------------------------------
    def add(self, d: str, name: str, source: str, dynamic_ok: bool = False) -> None:
        # Do NOT strip: some asset names legitimately end with a space
        # (e.g. "夢箱-3 .png").
        name = name or ""
        if not name:
            if dynamic_ok:
                self.counts["dynamic"] += 1
            return
        if name.lower() in SKIP_NAMES:
            self.counts["skipped"] += 1
            return
        # Variable/escape based names cannot be resolved statically.
        if "\\" in name or "%" in name:
            self.counts["dynamic"] += 1
            return

        norm = name.replace("\\", "/")
        if norm.startswith("/") or ".." in norm.split("/"):
            self.counts["invalid"] += 1
            self.by_dir[d]["invalid"] += 1
            self.missing.setdefault((d, name.lower()), (name, source, "invalid path"))
            return

        self.counts["refs"] += 1
        stat = self.by_dir.setdefault(
            d, {"refs": 0, "ok": 0, "case": 0, "missing": 0, "noship": 0,
                "rtp": 0, "invalid": 0})
        stat["refs"] += 1

        status, rel = self.index.resolve(d, name)
        if status in ("missing", "noship") and name.lower() in self.rtp_names.get(d, set()):
            status = "rtp"
        if status == "ok":
            self.counts["ok"] += 1
            stat["ok"] += 1
        elif status == "case":
            self.counts["case"] += 1
            stat["case"] += 1
            self.case.setdefault((d, name.lower()), (name, str(rel), source))
        elif status == "noship":
            self.counts["noship"] += 1
            stat["noship"] += 1
            self.missing.setdefault((d, name.lower()), (name, source, "not shipped"))
        elif status == "rtp":
            self.counts["rtp"] += 1
            stat["rtp"] += 1
            self.missing.setdefault((d, name.lower()), (name, source, "RTP"))
        else:
            self.counts["missing"] += 1
            stat["missing"] += 1
            self.missing.setdefault((d, name.lower()), (name, source, "missing"))

        key = name.replace("\\", "/").lower()
        self.used[d].add(key)
        self.used[d].add(key.rsplit("/", 1)[-1])

    def _add_indexed(self, d: str, raw: str, names: list[str], source: str) -> None:
        raw = (raw or "").strip()
        if not raw:
            return
        try:
            idx = int(raw)
        except ValueError:
            self.counts["dynamic"] += 1
            return
        if 1 <= idx <= len(names):
            if names[idx - 1]:
                self.add(d, names[idx - 1], f"{source} [id {idx}]")
            else:
                self.counts["missing"] += 1
                self.by_dir[d]["missing"] += 1
                self.missing.setdefault(
                    (d, f"<empty id {idx}>"),
                    (f"<{d.lower()} id {idx}: empty>", source, "empty name"),
                )
            return
        self.counts["missing"] += 1
        self.by_dir[d]["missing"] += 1
        self.missing.setdefault(
            (d, f"<id {idx}>"),
            (f"<{d.lower()} id {idx}>", source, "out-of-range id"),
        )

    def add_anim(self, raw: str, source: str) -> None:
        self._add_indexed("Battle", raw, self.animations, source)

    def add_chipset(self, raw: str, source: str) -> None:
        self._add_indexed("ChipSet", raw, self.chipsets, source)

    # -- parsers -----------------------------------------------------------
    def parse_ldb(self, path: Path) -> None:
        root = ET.parse(path).getroot()
        self.animations = [
            (el.findtext("animation_name", "") or "").strip()
            for el in root.iter("Animation")
        ]
        self.chipsets = [
            (el.findtext("chipset_name", "") or "").strip()
            for el in root.iter("Chipset")
        ]

        for i, el in enumerate(root.iter("Actor"), 1):
            self.add("CharSet", el.findtext("character_name", ""), f"Actor#{i}.character")
            self.add("FaceSet", el.findtext("face_name", ""), f"Actor#{i}.face")
            self.add_anim(el.findtext("unarmed_animation", ""), f"Actor#{i}.unarmed")

        for i, el in enumerate(root.iter("Enemy"), 1):
            self.add("Monster", el.findtext("battler_name", ""), f"Enemy#{i}.battler")

        for i, el in enumerate(root.iter("Chipset"), 1):
            self.add("ChipSet", el.findtext("chipset_name", ""), f"Chipset#{i}")

        for i, el in enumerate(root.iter("Animation"), 1):
            self.add("Battle", el.findtext("animation_name", ""), f"Animation#{i}")

        for i, el in enumerate(root.iter("Skill"), 1):
            self.add_anim(el.findtext("animation_id", ""), f"Skill#{i}.animation")

        for i, el in enumerate(root.iter("Item"), 1):
            self.add_anim(el.findtext("animation_id", ""), f"Item#{i}.animation")

        for i, el in enumerate(root.iter("Terrain"), 1):
            self.add("Backdrop", el.findtext("background_name", ""), f"Terrain#{i}.background")

        sysel = next(root.iter("System"), None)
        if sysel is not None:
            simple = [
                ("title_name", "Title"), ("gameover_name", "GameOver"),
                ("system_name", "System"), ("system2_name", "System"),
                ("boat_name", "CharSet"), ("ship_name", "CharSet"),
                ("airship_name", "CharSet"), ("battletest_background", "Backdrop"),
            ]
            for field, d in simple:
                self.add(d, sysel.findtext(field, ""), f"System.{field}")
            for field in (
                "title_music", "battle_music", "battle_end_music", "inn_music",
                "boat_music", "ship_music", "airship_music", "gameover_music",
            ):
                self.add("Music", sysel.findtext(f"{field}/Music/name", ""),
                         f"System.{field}")
            for field in (
                "cursor_se", "decision_se", "cancel_se", "buzzer_se",
                "battle_se", "escape_se", "enemy_attack_se", "enemy_damaged_se",
                "actor_damaged_se", "dodge_se", "enemy_death_se", "item_se",
            ):
                self.add("Sound", sysel.findtext(f"{field}/Sound/name", ""),
                         f"System.{field}")

        for i, ce in enumerate(root.iter("CommonEvent"), 1):
            cid = ce.get("id", str(i))
            for ec in ce.iter("EventCommand"):
                self.handle_command(ec, f"CommonEvent#{cid}")

    def parse_lmt(self, path: Path) -> None:
        root = ET.parse(path).getroot()
        for mi in root.iter("MapInfo"):
            mid = mi.get("id", "?")
            self.add("Music", mi.findtext("music/Music/name", ""), f"MapInfo#{mid}.music")
            self.add("Backdrop", mi.findtext("background_name", ""),
                     f"MapInfo#{mid}.background")

    def parse_map(self, path: Path) -> None:
        root = ET.parse(path).getroot()
        m = root.find("Map")
        if m is None:
            m = root
        src = path.stem
        self.add("Panorama", m.findtext("parallax_name", ""), f"{src}.parallax")
        for ep in m.iter("EventPage"):
            self.add("CharSet", ep.findtext("character_name", ""), f"{src}.EventPage")
        for ec in m.iter("EventCommand"):
            self.handle_command(ec, src)

    def handle_command(self, ec: ET.Element, source: str) -> None:
        try:
            code = int(ec.findtext("code", "0") or 0)
        except ValueError:
            return
        if code in STR_CMDS:
            self.add(STR_CMDS[code], ec.findtext("string", ""),
                     f"{source}.cmd{code}", dynamic_ok=True)
            return
        params: list[int] = []
        raw = (ec.findtext("parameters", "") or "").split()
        for x in raw:
            try:
                params.append(int(x))
            except ValueError:
                params.append(-1)
        if code in ANIM_CMDS and params:
            self.add_anim(str(params[0]), f"{source}.cmd{code}")
        elif code in CHIPSET_CMDS and params:
            self.add_chipset(str(params[0]), f"{source}.cmd{code}")

    # -- reporting ---------------------------------------------------------
    def unused(self, d: str) -> list[tuple[str, Path]]:
        out = []
        for stem, bname, rel in self.index.dirs[d]["files"]:
            if stem.lower() in self.used[d] or bname.lower() in self.used[d]:
                continue
            out.append((stem, rel))
        return sorted(out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default="build/game")
    ap.add_argument("--xml", default="xml")
    ap.add_argument("--json", default="build/asset-audit.json")
    ap.add_argument("--report", default="notes/asset-audit.md")
    ap.add_argument("--maps-limit", type=int, default=0)
    ap.add_argument("--rtp-table", default="vendor/Player/src/rtp_table.cpp")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when genuine missing assets exist")
    args = ap.parse_args()

    game = Path(args.game)
    xml = Path(args.xml)
    t0 = time.time()

    index = AssetIndex(game)
    rtp_names = load_rtp_table(Path(args.rtp_table))
    audit = Audit(index, rtp_names)
    print("indexed: " + ", ".join(
        f"{d}={len(index.dirs[d]['files'])}" for d in DIRS if index.dirs[d]["exists"]))
    print(f"rtp names: {sum(len(v) for v in rtp_names.values())} across {len(rtp_names)} dirs")

    audit.parse_ldb(xml / "RPG_RT.edb")
    print(f"  ldb done ({time.time() - t0:.1f}s)")
    audit.parse_lmt(xml / "RPG_RT.emt")
    print(f"  lmt done ({time.time() - t0:.1f}s)")

    maps = sorted(xml.glob("*.emu"))
    if args.maps_limit:
        maps = maps[: args.maps_limit]
    for i, path in enumerate(maps, 1):
        audit.parse_map(path)
        if i % 500 == 0:
            print(f"  {i}/{len(maps)} maps ({time.time() - t0:.1f}s)")

    # ---- unused ----------------------------------------------------------
    unused = {d: audit.unused(d) for d in DIRS if index.dirs[d]["exists"]}

    # ---- unique counts ---------------------------------------------------
    unique = {"missing": 0, "rtp": 0, "invalid": 0}
    for _name, _src, kind in audit.missing.values():
        if kind == "RTP":
            unique["rtp"] += 1
        elif kind == "invalid path":
            unique["invalid"] += 1
        else:
            unique["missing"] += 1

    # ---- JSON ------------------------------------------------------------
    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "game": str(game),
        "maps": len(maps),
        "counts": audit.counts,
        "unique": unique,
        "by_dir": audit.by_dir,
        "rtp_table": str(args.rtp_table),
        "missing": [
            {"dir": d, "name": n, "source": s, "kind": k}
            for (d, _), (n, s, k) in sorted(audit.missing.items())
        ],
        "case_mismatch": [
            {"dir": d, "name": n, "file": f, "source": s}
            for (d, _), (n, f, s) in sorted(audit.case.items())
        ],
        "unused": {
            d: [str(rel) for _stem, rel in items]
            for d, items in unused.items()
        },
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1))

    # ---- markdown --------------------------------------------------------
    c = audit.counts
    lines = [
        "# Asset audit",
        "",
        f"Generated: {out['generated']}  ({time.time() - t0:.1f}s, {len(maps)} maps)",
        "",
        "## Summary",
        "",
        f"- references: **{c['refs']}**",
        f"- resolved: **{c['ok']}**",
        f"- case-only mismatch: **{c['case']}**",
        f"- missing: **{c['missing']}** occurrences / **{unique['missing']}** unique names",
        f"- provided by the RTP: **{c['rtp']}** occurrences / **{unique['rtp']}** unique names",
        f"- invalid path (../ or absolute): **{c['invalid']}** / **{unique['invalid']}** unique",
        f"- folder not shipped and not RTP: **{c['noship']}**",
        f"- dynamic/unknown (variable names): **{c['dynamic']}**",
        f"- skipped placeholders: **{c['skipped']}**",
        "",
        "## Per directory",
        "",
        "| dir | files | refs | ok | case | missing | RTP | bad path | unused |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for d in DIRS:
        s = audit.by_dir[d]
        nfiles = len(index.dirs[d]["files"])
        nused = len(unused.get(d, []))
        if not index.dirs[d]["exists"] and s["refs"] == 0:
            continue
        lines.append(
            f"| {d} | {nfiles} | {s['refs']} | {s['ok']} | {s['case']} "
            f"| {s['missing']} | {s['rtp']} | {s['invalid']} | {nused} |"
        )

    lines += ["", "## Missing references", ""]
    by_dir: dict[str, list] = {}
    rtp_hits: dict[str, list] = {}
    invalid_hits: dict[str, list] = {}
    for (d, _), (n, s, k) in audit.missing.items():
        if k == "RTP":
            rtp_hits.setdefault(d, []).append((n, s, k))
        elif k == "invalid path":
            invalid_hits.setdefault(d, []).append((n, s, k))
        else:
            by_dir.setdefault(d, []).append((n, s, k))
    if not by_dir:
        lines.append("_None._")
    for d in sorted(by_dir):
        items = sorted(by_dir[d])
        lines.append(f"### {d} ({len(items)})")
        lines.append("")
        for n, s, k in items[:25]:
            suffix = "" if k == "missing" else f" _{k}_"
            lines.append(f"- `{n}`{suffix}  (first seen: `{s}`)")
        if len(items) > 25:
            lines.append(f"- … {len(items) - 25} more in `{args.json}`")
        lines.append("")

    lines += ["## Invalid references", ""]
    lines.append("Names containing `..` or leading `/`. EasyRPG Player blocks these; "
                 "they are broken data, not missing assets.")
    lines.append("")
    if not invalid_hits:
        lines.append("_None._")
    else:
        for d in sorted(invalid_hits):
            for n, s, _k in sorted(invalid_hits[d]):
                lines.append(f"- {d}: `{n}` (first seen: `{s}`)")
    lines.append("")

    lines += ["## Provided by the RTP", ""]
    lines.append("These are standard RPG Maker 2000 RTP files, not game assets. "
                 "Install an RTP or point `--rtp-path` at one.")
    lines.append("")
    if not rtp_hits:
        lines.append("_None._")
    else:
        for d in sorted(rtp_hits):
            items = sorted(rtp_hits[d])
            examples = ", ".join(f"`{n}`" for n, _s, _k in items[:8])
            lines.append(f"- **{d}**: {len(items)} ({examples}{'…' if len(items) > 8 else ''})")
    lines.append("")

    lines += ["## Case-only mismatches", ""]
    if not audit.case:
        lines.append("_None._")
    else:
        for (d, _), (n, f, s) in sorted(audit.case.items())[:100]:
            lines.append(f"- {d}: ref `{n}` -> file `{f}` (first seen: `{s}`)")
    lines.append("")

    lines += ["## Unused files (approximate)", ""]
    lines.append("Files never referenced by LDB/LMT/LMU. Dynamic "
                 "(variable-named) references can cause false positives.")
    lines.append("")
    for d in DIRS:
        if d not in unused or not unused[d]:
            continue
        lines.append(f"- **{d}**: {len(unused[d])} / {len(index.dirs[d]['files'])} unused")
    lines.append("")

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text("\n".join(lines) + "\n")

    print()
    for k, v in c.items():
        print(f"  {k:8s} {v}")
    print(f"  report   {args.report}")
    print(f"  json     {args.json}")
    if args.strict and c["missing"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
