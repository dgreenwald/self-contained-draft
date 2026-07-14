import pytest

from self_contained_draft.macros import (
    MacroExpansionError,
    expand_configured_macros,
    parse_macros,
)
from self_contained_draft.flatten import flatten_text


def test_parse_def_macro():
    macros = parse_macros(r"\def\dira{..}")

    macro = macros["dira"]
    assert macro.name == "dira"
    assert macro.nargs == 0
    assert macro.content == ".."
    assert macro.kind == "def"


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


def test_expand_only_configured_macro_names():
    text = r"\def\dira{..} A \dira B \other"
    macros = parse_macros(text)

    assert expand_configured_macros(text, macros, ["dira"]) == r"\def\dira{..} A .. B \other"


def test_expand_macro_with_arguments():
    text = r"\newcommand{\readResult}[1]{\input{#1.tex}} \readResult{table}"
    macros = parse_macros(text)

    assert (
        expand_configured_macros(text, macros, ["readResult"])
        == r"\newcommand{\readResult}[1]{\input{#1.tex}} \input{table.tex}"
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


def test_expanded_path_macro_can_be_flattened(tmp_path):
    section_dir = tmp_path / "sections"
    section_dir.mkdir()
    (section_dir / "intro.tex").write_text("body")
    source = tmp_path / "paper.tex"
    text = r"\def\sectiondir{sections}" "\n" r"\input{\sectiondir/intro}"
    macros = parse_macros(text)

    expanded = expand_configured_macros(text, macros, ["sectiondir"])

    assert flatten_text(expanded, source_path=source) == r"\def\sectiondir{sections}" "\nbody"
