import pytest

from self_contained_draft.conditionals import ConditionalError, ConditionalSimplifier, validate_flags
from self_contained_draft.processor import process_text


def simplify(text, flags=None):
    return ConditionalSimplifier({"MyFlag": True} if flags is None else flags).simplify(text)


@pytest.mark.parametrize(("enabled", "expected"), [(True, "yes"), (False, "no")])
def test_selects_branch(enabled, expected):
    assert simplify(r"\ifMyFlag yes\else no\fi", {"MyFlag": enabled}) == expected


@pytest.mark.parametrize(("text", "enabled", "expected"), [
    (r"A\ifMyFlag B\fi C", True, "ABC"),
    (r"A\ifMyFlag B\fi C", False, "AC"),
    (r"A\ifMyFlag\else B\fi C", True, "AC"),
    (r"A\ifMyFlag B\else\fi C", False, "AC"),
    (r"\ifMyFlag yes \else no \fi", True, "yes "),
    (r"\ifMyFlag yes \else no \fi", False, "no "),
])
def test_optional_else_empty_branches_and_spaces(text, enabled, expected):
    assert simplify(text, {"MyFlag": enabled}) == expected


def test_nested_configured_and_unconfigured_conditionals():
    text = r"\ifMyFlag A\ifOther B\else C\fi D\else E\fi"
    assert simplify(text, {"MyFlag": True, "Other": False}) == "ACD"
    assert simplify(text, {"MyFlag": False, "Other": True}) == "E"
    text = r"\iftrue\ifMyFlag A\else B\fi\else C\fi"
    assert simplify(text) == r"\iftrue{}A\else C\fi"


def test_newif_operands_and_unconfigured_nested_flags():
    prefix = r"\newif\ifOther \newif\ifMyFlag \MyFlagfalse "
    text = prefix + r"\ifMyFlag A\ifOther B\else C\fi D\else E\fi"
    assert simplify(text) == prefix + r"A\ifOther B\else C\fi D"


def test_newif_in_discarded_branch_does_not_register_flag():
    engine = ConditionalSimplifier({"MyFlag": False})
    assert engine.simplify(r"\ifMyFlag\newif\ifOther\else B\fi") == "B"
    assert engine.declared == set()


def test_nested_ifcase_and_or_are_preserved():
    text = r"\ifMyFlag\ifcase0 A\or B\else C\fi\else D\fi"
    assert simplify(text) == r"\ifcase0 A\or B\else C\fi"


def test_comments_escaped_percent_and_control_symbols():
    text = "% \\ifMyFlag ignored\n" + r"\ifMyFlag yes\%\else no\fi"
    assert simplify(text) == "% \\ifMyFlag ignored\nyes\\%"
    assert simplify(r"\\ifMyFlag plain") == r"\\ifMyFlag plain"
    assert simplify(r"\ifMyFlag A\\else B\else C\fi") == r"A\\else B"


def test_comments_in_retained_branch_are_preserved():
    text = "\\ifMyFlag% keep\n  yes% \\else fake\n\\else no\\fi% tail\nnext"
    assert simplify(text) == "% keep\nyes% \\else fake\n% tail\nnext"


@pytest.mark.parametrize(("text", "expected"), [
    ("\\ifMyFlag\n  yes\\else\n  no\\fi\n  tail", "yestail"),
    ("\\ifMyFlag\n\n  yes\\fi", "\n\n  yes"),
    ("\\ifMyFlag yes\\fi\n\n tail", "yes\n\n tail"),
    (r"\unskip\ifMyFlag yes\fi", r"\unskip{}yes"),
    (r"\ifMyFlag\unskip\else no\fi tail", r"\unskip{}tail"),
    (r"\ifMyFlag\unskip \fi tail", r"\unskip tail"),
])
def test_token_and_paragraph_boundaries(text, expected):
    assert simplify(text) == expected


def test_exact_names_and_unconfigured_text():
    text = r"\ifMyFlagExtra A\else B\fi \ifmyflag C\else D\fi"
    assert simplify(text) == text


@pytest.mark.parametrize(("text", "message"), [
    (r"\ifMyFlag yes", "Missing"),
    (r"\ifMyFlag A\else B\else C\fi", "Duplicate"),
    (r"\ifMyFlag\ifUnknown A\fi\fi", "Unsupported conditional nesting"),
    (r"\ifMyFlag A\or B\fi", "Unexpected"),
])
def test_malformed_or_ambiguous_blocks_fail_with_context(text, message):
    with pytest.raises(ConditionalError, match=message) as exc:
        ConditionalSimplifier({"MyFlag": True}).simplify(text, source="paper.tex")
    assert "paper.tex" in str(exc.value)
    assert "offset" in str(exc.value)


@pytest.mark.parametrize("value", [None, [], "MyFlag", {"": True}, {"\\MyFlag": True},
                                      {"Flag1": True}, {1: True}, {"MyFlag": "false"},
                                      {"MyFlag": 0}, {"true": False}])
def test_invalid_flag_configuration(value):
    with pytest.raises(ConditionalError):
        validate_flags(value)


@pytest.mark.parametrize("strip_comments", [True, False])
def test_processor_ignores_commented_delimiters(strip_comments, tmp_path):
    text = "\\ifMyFlag% opening\n  yes% \\else fake\n\\else no\\fi"
    actual = process_text(text, source_path=tmp_path / "paper.tex",
                          strip_tex_comments=strip_comments, conditional_flags={"MyFlag": True})
    assert actual == ("yes" if strip_comments else "% opening\nyes% \\else fake\n")


def test_macro_definition_and_source_setters_are_preserved(tmp_path):
    text = r"\newif\ifMyFlag \MyFlagfalse \newcommand{\word}{\ifMyFlag yes\else no\fi}\word"
    assert process_text(text, source_path=tmp_path / "paper.tex", conditional_flags={"MyFlag": True}) == (
        r"\newif\ifMyFlag \MyFlagfalse \newcommand{\word}{yes}\word"
    )


def test_empty_configuration_preserves_conditionals(tmp_path):
    text = r"\newif\ifMyFlag \ifMyFlag yes\else no\fi"
    assert process_text(text, source_path=tmp_path / "paper.tex") == text


@pytest.mark.parametrize("prefix", ["unless", "noexpand", "string"])
def test_unsupported_prefix_on_configured_flag_is_rejected(prefix, tmp_path):
    text = "\\" + prefix + r"\ifMyFlag A\else B\fi"
    with pytest.raises(ConditionalError, match="Unsupported"):
        process_text(text, source_path=tmp_path / "paper.tex", conditional_flags={"MyFlag": True})


def test_conditional_tokens_used_as_primitive_operands_are_preserved(tmp_path):
    text = r"\ifMyFlag\ifx\ifMyFlag\ifOther A\else B\fi\else C\fi"
    expected = r"\ifx\ifMyFlag\ifOther A\else B\fi"
    assert simplify(text) == expected
    assert process_text(text, source_path=tmp_path / "paper.tex", conditional_flags={"MyFlag": True}) == expected


def test_discarding_branch_does_not_merge_escaped_backslash_with_text(tmp_path):
    text = r"\\word\ifMyFlag\else ignored\fi tail"
    assert simplify(text) == r"\\wordtail"
    assert process_text(text, source_path=tmp_path / "paper.tex", conditional_flags={"MyFlag": True}) == r"\\wordtail"
