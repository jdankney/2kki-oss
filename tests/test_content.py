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


def test_apply_twice_is_a_no_op(tmp_path):
    write(tmp_path / "xml" / "Map0002.emu", "one\ntwo\nthree\n")
    entry = make_patch(tmp_path, "Map0002.emu", "one\ntwo\nthree\n", "one\nTWO\nthree\n")
    make_content(tmp_path, modified=[entry])

    apply(tmp_path)
    after_first = snapshot(tmp_path / "xml")
    assert after_first == {"Map0002.emu": b"one\nTWO\nthree\n"}

    res = apply(tmp_path, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "already applied" in res.stdout
    assert snapshot(tmp_path / "xml") == after_first     # no .rej, no revert


def test_conflicting_patch_fails_without_touching_xml(tmp_path):
    write(tmp_path / "xml" / "Map0002.emu", "something\nelse\nentirely\n")
    entry = make_patch(tmp_path, "Map0002.emu", "one\ntwo\nthree\n", "one\nTWO\nthree\n")
    make_content(tmp_path, modified=[entry])
    before = snapshot(tmp_path / "xml")
    res = apply(tmp_path, check=False)
    assert res.returncode == 1
    assert "FAIL Map0002.emu" in res.stderr
    assert snapshot(tmp_path / "xml") == before
