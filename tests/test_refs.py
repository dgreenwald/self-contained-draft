import pytest

from self_contained_draft.refs import (
    ReferenceError,
    parse_aux_file,
    parse_aux_files,
    parse_aux_labels,
    replace_external_refs,
)


def test_parse_aux_labels_reads_basic_newlabel():
    labels = parse_aux_labels(r"\newlabel{sec:model}{{A.1}{3}{Model Details}{section.A.1}{}}")

    assert labels == {"sec:model": "A.1"}


def test_parse_aux_labels_allows_common_label_characters():
    labels = parse_aux_labels(
        r"\newlabel{fig:credit-relaxation-by-H}{{A.6}{16}{Title}{figure.caption.15}{}}"
    )

    assert labels["fig:credit-relaxation-by-H"] == "A.6"


def test_parse_aux_labels_handles_nested_braces_after_value():
    labels = parse_aux_labels(
        r"\newlabel{tab:johnson}{{A.1}{11}{Comparison: Model vs. \cite {johnson2020}}{table.caption.11}{}}"
    )

    assert labels["tab:johnson"] == "A.1"


def test_parse_aux_file_reads_labels(tmp_path):
    aux_file = tmp_path / "appendix.aux"
    aux_file.write_text(r"\newlabel{eq:test}{{B.2}{4}{Equation}{equation.B.2}{}}")

    assert parse_aux_file(aux_file) == {"eq:test": "B.2"}


def test_parse_aux_files_later_files_override(tmp_path):
    first = tmp_path / "first.aux"
    second = tmp_path / "second.aux"
    first.write_text(r"\newlabel{sec:test}{{A}{1}{Title}{appendix.A}{}}")
    second.write_text(r"\newlabel{sec:test}{{B}{1}{Title}{appendix.B}{}}")

    assert parse_aux_files((first, second)) == {"sec:test": "B"}


def test_parse_aux_file_raises_for_missing_file(tmp_path):
    with pytest.raises(ReferenceError, match="Could not read aux file"):
        parse_aux_file(tmp_path / "missing.aux")


def test_replace_external_refs_replaces_ref_and_eqref():
    text = r"See Section \ref{sec:model} and equation \eqref{eq:test}."
    result = replace_external_refs(text, {"sec:model": "A.1", "eq:test": "B.2"})

    assert result.text == "See Section A.1 and equation (B.2)."
    assert result.replaced == ("sec:model", "eq:test")
    assert result.unresolved == ()


def test_replace_external_refs_preserves_unknown_refs_and_tracks_them():
    text = r"See \ref{sec:known}, \ref{sec:unknown}, and \eqref{eq:unknown}."
    result = replace_external_refs(text, {"sec:known": "A"})

    assert result.text == r"See A, \ref{sec:unknown}, and \eqref{eq:unknown}."
    assert result.replaced == ("sec:known",)
    assert result.unresolved == ("sec:unknown", "eq:unknown")


def test_replace_external_refs_can_skip_unresolved_tracking():
    result = replace_external_refs(r"\ref{missing}", {}, track_unresolved=False)

    assert result.unresolved == ()
