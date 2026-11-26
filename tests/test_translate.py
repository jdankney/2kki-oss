import json

from conftest import load_script

translate = load_script("translate")

MSG, MSG2 = translate.SHOW_MESSAGE, translate.SHOW_MESSAGE_2
CHOICE, OPT, END = (translate.SHOW_CHOICE, translate.SHOW_CHOICE_OPTION,
                    translate.SHOW_CHOICE_END)


def test_message_box_lines_are_joined():
    cmds = [(MSG, "line 1", 0, []), (MSG2, "line 2", 0, []), (MSG, "next", 0, [])]
    assert translate.message_units(cmds) == [("", "line 1\nline 2"), ("", "next")]


def test_choice_options_are_joined_and_cancel_branch_skipped():
    cmds = [
        (CHOICE, "", 0, []),
        (OPT, "はい", 0, [0]),
        (MSG, "nested", 1, []),
        (OPT, "いいえ", 0, [1]),
        (OPT, "", 0, [4]),        # cancel branch, not shown to the player
        (END, "", 0, []),
    ]
    units = translate.message_units(cmds)
    assert units[0] == ("", "はい\nいいえ")


def test_glossary_line_by_line_and_overrides(tmp_path):
    g = tmp_path / "glossary.json"
    g.write_text(json.dumps({"strings": {"はい": "Yes", "いいえ": "No"},
                             "terms": {"gold": "Dreams"}}))
    o = tmp_path / "overrides.json"
    o.write_text(json.dumps({"messages": {"はい\nいいえ": "Sure\nNope"}}))
    gl = translate.Glossary(g, o)
    assert gl.string("　はい ") == "Yes"
    assert gl.string("はい\nいいえ") == "Sure\nNope"     # override wins
    assert gl.string("いいえ\nはい") == "No\nYes"       # line by line
    assert gl.string("いいえ\n未知") == ""             # all-or-nothing
    assert gl.term("gold") == "Dreams"


def test_po_escape():
    assert translate.po_escape('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_committed_glossary_and_overrides_parse():
    from conftest import REPO
    gl = translate.Glossary(REPO / "translation" / "glossary.json",
                            REPO / "translation" / "overrides.json")
    assert gl.term("yes") == "Yes"


def test_po_header_uses_the_language_code(tmp_path):
    gl = translate.Glossary(tmp_path / "none.json")
    po = tmp_path / "x.po"
    translate.write_po(po, [("", "はい")], gl, lang="de")
    assert '"Language: de\\n"' in po.read_text()


PO_SAMPLE = r'''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"

#. ID 6, Page 2
msgctxt "actors.name"
msgid "うろつき"
msgstr "Urotsuki"

#. lcftrans multi-line style
msgid ""
"\\>一行目\n"
"二行目 \"引用\""
msgstr ""
"\\>Line one\n"
"Line two \"quoted\""

msgid "未訳"
msgstr ""

#, fuzzy
msgid "あいまい"
msgstr "Fuzzy guess"

#~ msgid "古い"
#~ msgstr "Obsolete"
msgid "最後"
msgstr "Last"
'''


def test_read_po(tmp_path):
    po = tmp_path / "Map0001.po"
    po.write_text(PO_SAMPLE, encoding="utf-8")
    assert translate.read_po(po) == [
        ("actors.name", "うろつき", "Urotsuki"),
        ("", '\\>一行目\n二行目 "引用"', '\\>Line one\nLine two "quoted"'),
        ("", "未訳", ""),
        ("", "あいまい", ""),
        ("", "最後", "Last"),
    ]


def test_read_po_round_trips_what_write_po_writes(tmp_path):
    gl = translate.Glossary(tmp_path / "none.json")
    po = tmp_path / "x.po"
    entries = [("", 'a\\b "c"\nd'), ("skills.3.name", "技")]
    translate.write_po(po, entries, gl)
    assert [(c, m) for c, m, _s in translate.read_po(po)] == entries


def test_norm_ctx():
    assert translate.norm_ctx("actors.12.name") == "actors.name"
    assert translate.norm_ctx("terms.gold") == "terms.gold"
    assert translate.norm_ctx("actors.name") == "actors.name"
    assert translate.norm_ctx("") == ""


def test_translation_memory_prefers_same_file_then_moved():
    tm = translate.TranslationMemory()
    tm.add_file("RPG_RT.ldb.po", [("actors.name", "うろつき", "Urotsuki")])
    tm.add_file("Map0002.po", [("", "はい", "Yes (map 2)"), ("", "空", "")])
    tm.add_file("Map0005.po", [("", "はい", "Yes (map 5)"), ("", "移動", "Moved")])
    # Indexed DB context, case-insensitive catalogue name.
    assert tm.lookup("rpg_rt.ldb.po", "actors.1.name", "うろつき") == ("Urotsuki", "import")
    assert tm.lookup("Map0005.po", "", "はい") == ("Yes (map 5)", "import")
    # Message that sits in another map in the imported version.
    assert tm.lookup("Map0002.po", "", "移動") == ("Moved", "import-moved")
    # Empty translations are not memory.
    assert tm.lookup("Map0002.po", "", "空") == ("", "")
    assert tm.unused() == 1      # Map0002 "はい" was never asked for


def test_read_po_context_entry_followed_by_plain_entry(tmp_path):
    # No comment or blank line between entries (our own writer's style
    # has blank lines, but entries may also follow directly).
    po = tmp_path / "x.po"
    po.write_text('msgctxt "actors.name"\nmsgid "名前"\nmsgstr ""\n'
                  'msgid "本文"\nmsgstr "Body"\n'
                  '#, fuzzy\nmsgctxt "c"\nmsgid "曖昧"\nmsgstr "Guess"\n'
                  'msgid "次"\nmsgstr "Next"\n', encoding="utf-8")
    assert translate.read_po(po) == [
        ("actors.name", "名前", ""), ("", "本文", "Body"), ("c", "曖昧", ""), ("", "次", "Next")]
