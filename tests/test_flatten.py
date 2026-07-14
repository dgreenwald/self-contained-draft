import pytest

from self_contained_draft.flatten import (
    FlattenError,
    flatten_file,
    flatten_text,
    parse_input_command,
    resolve_input_path,
)


def test_parse_braced_input_command():
    command = parse_input_command(r"before \input { sections/intro } after", 7)

    assert command.raw == r"\input { sections/intro }"
    assert command.path_text == "sections/intro"
    assert command.end == len(r"before \input { sections/intro }")


def test_parse_unbraced_input_command():
    command = parse_input_command(r"\input intro.tex more", 0)

    assert command.raw == r"\input intro.tex"
    assert command.path_text == "intro.tex"


def test_resolve_input_path_tries_tex_extension(tmp_path):
    tex_file = tmp_path / "intro.tex"
    tex_file.write_text("hello")

    assert resolve_input_path("intro", current_dir=tmp_path) == tex_file.resolve()


def test_resolve_input_path_uses_search_paths(tmp_path):
    root = tmp_path / "root"
    shared = tmp_path / "shared"
    root.mkdir()
    shared.mkdir()
    tex_file = shared / "defs.tex"
    tex_file.write_text("definitions")

    assert (
        resolve_input_path("defs", current_dir=root, search_paths=(shared,))
        == tex_file.resolve()
    )


def test_flatten_file_inlines_nested_inputs_relative_to_including_file(tmp_path):
    root = tmp_path / "paper.tex"
    sections = tmp_path / "sections"
    sections.mkdir()
    root.write_text("A\n\\input{sections/intro}\nD")
    (sections / "intro.tex").write_text("B\n\\input{detail}\n")
    (sections / "detail.tex").write_text("C")

    assert flatten_file(root) == "A\nB\nC\n\nD"


def test_flatten_file_strips_comments_before_scanning_inputs(tmp_path):
    root = tmp_path / "paper.tex"
    keep = tmp_path / "keep.tex"
    hidden = tmp_path / "hidden.tex"
    keep.write_text("visible")
    hidden.write_text("hidden")
    root.write_text("% \\input{hidden}\n\\input{keep}")

    assert flatten_file(root) == "\nvisible"


def test_flatten_file_can_preserve_missing_inputs(tmp_path):
    root = tmp_path / "paper.tex"
    root.write_text(r"A \input{missing} B")

    assert flatten_file(root, allow_missing_inputs=True) == r"A \input{missing} B"


def test_flatten_file_raises_for_missing_input_by_default(tmp_path):
    root = tmp_path / "paper.tex"
    root.write_text(r"A \input{missing} B")

    with pytest.raises(FlattenError, match="Could not resolve"):
        flatten_file(root)


def test_flatten_file_detects_input_cycles(tmp_path):
    first = tmp_path / "first.tex"
    second = tmp_path / "second.tex"
    first.write_text(r"\input{second}")
    second.write_text(r"\input{first}")

    with pytest.raises(FlattenError, match="cycle"):
        flatten_file(first)


def test_flatten_text_uses_source_path_for_relative_inputs(tmp_path):
    source = tmp_path / "paper.tex"
    included = tmp_path / "body.tex"
    source.write_text("")
    included.write_text("body")

    assert flatten_text(r"\input{body}", source_path=source) == "body"


def test_flatten_file_can_disable_comment_stripping(tmp_path):
    root = tmp_path / "paper.tex"
    root.write_text("A % keep comment")

    assert flatten_file(root, strip_comments=False) == "A % keep comment"
