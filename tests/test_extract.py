from pathlib import Path

from conftest import load_script, write

extract = load_script("extract")


def test_repair_component_fixes_cp866_mojibake():
    # "ゆめ2っき" in CP932, wrongly decoded as CP866.
    mojibake = "ゆめ2っき".encode("cp932").decode("cp866")
    assert extract.repair_component(mojibake) == ("ゆめ2っき", True)


def test_repair_component_leaves_ascii_and_correct_names():
    assert extract.repair_component("Picture") == ("Picture", False)
    # Already-correct Japanese (the patch zip was unpacked properly).
    assert extract.repair_component("ゆめ2っき") == ("ゆめ2っき", False)


def test_repair_relpath_repairs_every_component():
    moj = "ゆめ2っき".encode("cp932").decode("cp866")
    fixed, changed = extract.repair_relpath(Path(moj) / "Picture" / "a.png")
    assert changed
    assert fixed == Path("ゆめ2っき") / "Picture" / "a.png"


def test_choose_roots_picks_base_and_patch(game_src):
    base, patches = extract.choose_roots(game_src)
    assert base == game_src / "Game_v1" / "game"
    assert patches == [game_src / "Game_v1_patch1" / "game"]


def test_escape_cr_in_xml(tmp_path):
    p = tmp_path / "a.emu"
    p.write_bytes(b"<string>text\r</string>\n")
    assert extract.escape_cr_in_xml(p)
    assert p.read_bytes() == b"<string>text&#xD;</string>\n"
    assert not extract.escape_cr_in_xml(p)


def test_choose_roots_ignores_patch_in_parent_dirs(tmp_path):
    src = tmp_path / "my-patches-checkout" / "original"
    write(src / "Game" / "RPG_RT.ldb", b"x")
    write(src / "Game" / "Map0001.lmu", b"x")
    write(src / "Game_patch1" / "RPG_RT.ldb", b"x")
    base, patches = extract.choose_roots(src)
    assert base == src / "Game"
    assert patches == [src / "Game_patch1"]


def test_choose_roots_orders_patches_naturally(tmp_path):
    src = tmp_path / "original"
    write(src / "Game" / "RPG_RT.ldb", b"x")
    for n in (10, 2, 1):
        write(src / f"Game_patch{n}" / "RPG_RT.ldb", b"x")
    _base, patches = extract.choose_roots(src)
    assert [p.name for p in patches] == ["Game_patch1", "Game_patch2", "Game_patch10"]


def test_extract_layers_patch_over_base(extracted):
    game = extracted / "build" / "game"
    assert (game / "RPG_RT.ldb").read_bytes() == b"LDB-patch"
    assert (game / "Map0002.lmu").read_bytes() == b"MAP2-patch"
    assert (game / "Map0001.lmu").read_bytes() == b"MAP1-base"
    assert (game / "Picture" / "pic.png").read_bytes() == b"PNG"
    assert b"Encoding=932" in (game / "RPG_RT.ini").read_bytes()
    assert (extracted / "xml" / "Map0001.emu").is_file()


