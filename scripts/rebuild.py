#!/usr/bin/env python3
"""Rebuild LCF files in build/game from edited XML in xml/.

This is the other half of the remake loop::

    make extract          # original -> build/game + xml/
    edit xml/*.emu        # maps, events, database ...
    make data             # xml/ -> build/game/*.lmu
    make run

``lcf2xml`` is bidirectional: given ``.emu/.edb/.emt`` it writes
``.lmu/.ldb/.lmt`` into the current directory. We run it with
``cwd=build/game`` so the output lands next to the runnable data.

The target file is unlinked before conversion so a hardlink to ``original/``
is never truncated (``original/`` is read-only by project rule).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

XML_EXT = {".emu": ".lmu", ".edb": ".ldb", ".emt": ".lmt", ".esd": ".lsd"}
TARGET_ENC = "cp932"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xml", default="xml")
    ap.add_argument("--game", default="build/game")
    ap.add_argument("--lcf2xml", default="build/liblcf/lcf2xml")
    ap.add_argument("--force", action="store_true", help="rebuild even if up to date")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    xml_dir = Path(args.xml)
    game_dir = Path(args.game)
    lcf2xml = Path(args.lcf2xml).resolve()

    if not lcf2xml.is_file():
        sys.exit(f"error: lcf2xml not found: {lcf2xml}")
    if not xml_dir.is_dir():
        sys.exit(f"error: XML dir not found: {xml_dir}")
    if not game_dir.is_dir():
        sys.exit(f"error: game dir not found: {game_dir}")

    todo: list[tuple[Path, Path]] = []
    skipped = 0
    for src in sorted(xml_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() not in XML_EXT:
            continue
        dst = game_dir / (src.stem + XML_EXT[src.suffix.lower()])
        if (not args.force and dst.is_file()
                and dst.stat().st_size > 0
                and dst.stat().st_mtime >= src.stat().st_mtime):
            skipped += 1
            continue
        todo.append((src, dst))

    print(f"XML files to rebuild: {len(todo)} (skipped {skipped})")
    if not todo:
        return 0

    t0 = time.time()
    chunk = 200
    for i in range(0, len(todo), chunk):
        batch = todo[i:i + chunk]
        if not args.dry_run:
            # Break any hardlink first; lcf2xml truncates its output file.
            for _src, dst in batch:
                if dst.exists() or dst.is_symlink():
                    os.unlink(dst)
        # Inputs must be absolute: lcf2xml runs with cwd=game_dir and writes
        # its output into the current directory.
        cmd = [str(lcf2xml), "--2k", "--encoding", TARGET_ENC] + [str(s.resolve()) for s, _d in batch]
        if args.dry_run:
            print(f"  [dry-run] {' '.join(cmd[:4])} ... ({len(batch)} files)")
            continue
        res = subprocess.run(cmd, cwd=str(game_dir))
        if res.returncode != 0:
            sys.exit(f"error: lcf2xml failed on batch {i // chunk + 1}")

        missing = [str(d) for _s, d in batch if not d.is_file() or d.stat().st_size == 0]
        if missing:
            sys.exit(f"error: conversion produced no output for {missing[0]}")
        print(f"  rebuilt {min(i + chunk, len(todo))}/{len(todo)}")

    print(f"done in {time.time() - t0:.1f}s -> {game_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
