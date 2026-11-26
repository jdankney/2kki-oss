import difflib
import json
from pathlib import Path

from conftest import age, run_script, snapshot, write


def make_content(work: Path, modified=(), added=()) -> Path:
    content = work / "content"
    write(content / "content.json", json.dumps(
        {"modified": list(modified), "added": list(added), "deleted": []}))
    return content


def make_patch(work: Path, rel: str, old: str, new: str) -> dict:
    diff = "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    write(work / "content" / "patches" / f"{rel}.patch", diff)
    return {"path": rel, "patch": f"patches/{rel}.patch", "kind": "patch"}


def apply(work: Path, *extra, check=True):
    return run_script("content", "apply", *extra, cwd=work, check=check)


def test_full_file_entry_reaches_the_game(extracted, lcf2xml):
    # The committed full file is older than the freshly extracted LCF
    # (git checkout happened before `make extract`).
    full = write(extracted / "content" / "files" / "Map0001.emu", b"OUR MAP")
    age(full, 7200)
    make_content(extracted, modified=[
        {"path": "Map0001.emu", "file": "files/Map0001.emu", "kind": "full"}])
    apply(extracted)
    run_script("rebuild", "--lcf2xml", lcf2xml, cwd=extracted)
    game = extracted / "build" / "game"
    assert (game / "Map0001.lmu").read_bytes() == b"converted:OUR MAP"

