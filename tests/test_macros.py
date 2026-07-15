import pytest

from self_contained_draft.macros import (
    MacroExpansionError,
    expand_configured_macros,
    parse_macro_definitions,
    parse_macros,
    remove_macro_definitions,
)
from self_contained_draft.flatten import flatten_text


def test_parse_def_macro():
    macros = parse_macros(r"\def\dira{..}")

    macro = macros["dira"]
    assert macro.name == "dira"
    assert macro.nargs == 0
    assert macro.content == ".."
    assert macro.kind == "def"


def test_parse_def_skips_parameterized_plain_tex_def():
    macros = parse_macros(r"\def\sym#1{\ifmmode^{#1}\fi} \def\dira{..}")

    assert "sym" not in macros
    assert macros["dira"].content == ".."


def test_parse_newcommand_with_arguments():
    macros = parse_macros(r"\newcommand{\readResult}[1]{\input{\pfdir/#1}\unskip}")

    macro = macros["readResult"]
    assert macro.nargs == 1
    assert macro.content == r"\input{\pfdir/#1}\unskip"


def test_parse_newcommand_without_braced_name():
    macros = parse_macros(r"\newcommand\foo[2]{#1/#2}")

    assert macros["foo"].nargs == 2
    assert macros["foo"].content == "#1/#2"


def test_parse_renewcommand_and_starred_newcommand():
    macros = parse_macros(r"\newcommand*{\foo}{a} \renewcommand{\foo}{b}")

    assert macros["foo"].content == "b"


def test_parse_macro_definitions_returns_duplicate_definitions():
    definitions = parse_macro_definitions(r"\newcommand{\foo}{a} \newcommand{\foo}{b}")

    assert [definition.content for definition in definitions if definition.name == "foo"] == [
        "a",
        "b",
    ]


def test_expand_only_configured_macro_names():
    text = r"\def\dira{..} A \dira B \other"
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["dira"]) == r"\def\dira{..} A .. B \other"


def test_expand_uses_active_definition_at_use_site():
    text = r"\def\thisdir{first} \thisdir \def\thisdir{second} \thisdir"
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["thisdir"]) == (
        r"\def\thisdir{first} first \def\thisdir{second} second"
    )


def test_expand_dependencies_use_active_definition_at_use_site():
    text = (
        r"\def\base{first}"
        "\n"
        r"\def\thisdir{\base/path}"
        "\n"
        r"\thisdir"
        "\n"
        r"\def\base{second}"
        "\n"
        r"\thisdir"
    )
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["thisdir"]) == (
        r"\def\base{first}"
        "\n"
        r"\def\thisdir{\base/path}"
        "\n"
        "first/path"
        "\n"
        r"\def\base{second}"
        "\n"
        "second/path"
    )


def test_expand_does_not_replace_prefix_of_longer_macro_name():
    text = r"\def\drop{/Users/dan/Dropbox} \dropbox \drop"
    macros = parse_macros(text)

    assert (
        expand_configured_macros(text, macros, ["drop"])
        == r"\def\drop{/Users/dan/Dropbox} \dropbox /Users/dan/Dropbox"
    )


def test_expand_macro_with_arguments():
    text = r"\newcommand{\readResult}[1]{\input{#1.tex}} \readResult{table}"
    macros = parse_macros(text)

    assert (
        expand_configured_macros(text, macros, ["readResult"])
        == r"\newcommand{\readResult}[1]{\input{#1.tex}} \input{table.tex}"
    )


def test_expand_skips_configured_macros_inside_consumed_arguments():
    text = (
        r"\def\dir{tables}"
        "\n"
        r"\newcommand{\readimp}[2]{\input{#1/#2}}"
        "\n"
        r"\readimp{\dir}{value}"
    )
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["dir", "readimp"]).endswith(
        r"\input{tables/value}"
    )


def test_expand_skips_argument_macro_mentioned_without_arguments():
    text = r"\newcommand{\row}[2]{#1/#2} expand = \row, call = \row{a}{b}"
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["row"]) == (
        r"\newcommand{\row}[2]{#1/#2} expand = \row, call = a/b"
    )


def test_expand_resolves_zero_argument_dependencies_in_replacement():
    text = (
        r"\def\dira{..}"
        "\n"
        r"\def\dirModPlots{\dira/Replication/Model/plots}"
        "\n"
        r"\def\pfdir{\dirModPlots/perfect_foresight}"
        "\n"
        r"\input{\pfdir/result}"
    )
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["pfdir"]).endswith(
        r"\input{../Replication/Model/plots/perfect_foresight/result}"
    )


def test_expand_configured_macro_can_use_argument_and_dependency():
    text = (
        r"\def\pfdir{../plots}"
        "\n"
        r"\newcommand{\readDetResult}[1]{\input{\pfdir/#1}\unskip}"
        "\n"
        r"\readDetResult{data/value}"
    )
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["readDetResult"]).endswith(
        r"\input{../plots/data/value}\unskip"
    )


def test_unconfigured_macro_is_preserved():
    text = r"\def\dira{..} \dira"
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, []) == text


def test_recursive_macro_dependency_raises():
    text = r"\def\a{\b} \def\b{\a} \a"
    macros = parse_macros(text)

    with pytest.raises(MacroExpansionError, match="recursive macro"):
        expand_configured_macros(text, macros, ["a"])


def test_remove_macro_definitions_removes_only_configured_min_arg_macros():
    text = (
        r"\def\dir{figures}"
        "\n"
        r"\newcommand{\readfig}[1]{\input{\dir/#1}}"
        "\n"
        r"\readfig{plot}"
    )
    macros = parse_macros(text)

    assert remove_macro_definitions(text, macros, ["dir", "readfig"], min_args=1) == (
        r"\def\dir{figures}" "\n\n" r"\readfig{plot}"
    )


def test_remove_macro_definitions_can_remove_duplicate_definitions():
    text = r"\newcommand{\read}[1]{a} keep \newcommand{\read}[1]{b} \read{x}"
    definitions = parse_macro_definitions(text)

    assert remove_macro_definitions(text, definitions, ["read"], min_args=1) == " keep  \\read{x}"


def test_expanded_path_macro_can_be_flattened(tmp_path):
    section_dir = tmp_path / "sections"
    section_dir.mkdir()
    (section_dir / "intro.tex").write_text("body")
    source = tmp_path / "paper.tex"
    text = r"\def\sectiondir{sections}" "\n" r"\input{\sectiondir/intro}"
    macros = parse_macros(text)

    expanded = expand_configured_macros(text, macros, ["sectiondir"])

    assert flatten_text(expanded, source_path=source) == r"\def\sectiondir{sections}" "\nbody"
