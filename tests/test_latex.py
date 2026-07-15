import re

import pytest

from self_contained_draft.latex import (
    LatexParseError,
    bma_search,
    expand_to_target,
    match_to_bma,
    read_balanced,
    read_required_arguments,
    strip_comments,
    substitute_arguments,
)


def test_match_to_bma_splits_regex_match():
    text = "before \\input{file} after"
    match = re.search(r"\\input", text)

    result = match_to_bma(match, text)

    assert result.matched is True
    assert result.before == "before "
    assert result.middle == r"\input"
    assert result.after == "{file} after"


def test_match_to_bma_handles_missing_match():
    result = match_to_bma(None, "abc")

    assert result.matched is False
    assert result.before == "abc"
    assert result.middle == ""
    assert result.after == ""


def test_bma_search_forwards_to_regex_search():
    result = bma_search(r"b+", "aaabbbccc")

    assert result.before == "aaa"
    assert result.middle == "bbb"
    assert result.after == "ccc"


def test_strip_comments_preserves_escaped_percent_and_removes_comment_newlines():
    text = "a % remove this\nb \\% keep this\nc \\\\% remove this too\nd"

    assert strip_comments(text) == "a b \\% keep this\nc \\\\d"


def test_strip_comments_removes_indentation_after_line_continuation():
    text = "\\newcommand{\\topct}[1]{%\n\t\\topctPlaces{#1}{1}%\n}"

    assert strip_comments(text) == "\\newcommand{\\topct}[1]{\\topctPlaces{#1}{1}}"


def test_read_balanced_handles_nested_braces():
    result = read_balanced("{a {nested} value} tail")

    assert result.content == "a {nested} value"
    assert result.delimiter == "}"
    assert result.after == " tail"
    assert result.start == 0
    assert result.end == len("{a {nested} value}")


def test_read_balanced_raises_contextual_error_for_unclosed_brace():
    with pytest.raises(LatexParseError, match="Unclosed"):
        read_balanced("{missing", source="paper.tex")


def test_read_required_arguments_reads_sequential_arguments():
    arguments, tail = read_required_arguments("  {one}{two {nested}} tail", 2)

    assert arguments == ["one", "two {nested}"]
    assert tail == " tail"


def test_expand_to_target_matches_legacy_brace_behavior():
    before, middle, after = expand_to_target(
        r"a {nested \} literal} value} tail",
        left_bracket="{",
    )

    assert before == r"a {nested \} literal} value"
    assert middle == "}"
    assert after == " tail"


def test_expand_to_target_can_find_custom_target_at_depth():
    before, middle, after = expand_to_target(
        "a, {b, c}, d)",
        target=",",
        left_bracket="(",
        target_depth=1,
    )

    assert before == "a"
    assert middle == ","
    assert after == " {b, c}, d)"


def test_substitute_arguments_replaces_latex_placeholders():
    assert substitute_arguments(r"\input{#1/#2}", ["dir", "file"]) == r"\input{dir/file}"
