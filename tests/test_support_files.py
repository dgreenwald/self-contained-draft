import pytest

from self_contained_draft.support_files import (
    SupportFileError,
    copy_support_files,
    resolve_support_path,
)


def test_resolve_support_path_tries_kind_extension(tmp_path):
    bib = tmp_path / "master.bib"
    bib.write_text("@article{x}")

    assert resolve_support_path("master", kind="bibliography", current_dir=tmp_path) == bib.resolve()


def test_copy_support_files_copies_and_rewrites_bibliography_paths(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    bib_dir = tmp_path / "bib"
    source.mkdir()
    bib_dir.mkdir()
    (bib_dir / "master.bib").write_text("@article{x}")
    text = r"\bibliography{../bib/master}"

    result = copy_support_files(text, source_dir=source, output_dir=output)

    assert result.text == r"\bibliography{master}"
    assert (output / "master.bib").read_text() == "@article{x}"
    assert result.files[0].kind == "bibliography"
    assert result.files[0].output_name == "master.bib"


def test_copy_support_files_copies_class_style_and_bst(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    source.mkdir()
    (source / "journal.cls").write_text("class")
    (source / "local.sty").write_text("style")
    (source / "plainnat.bst").write_text("bst")
    text = (
        r"\documentclass{journal}"
        "\n"
        r"\usepackage{local}"
        "\n"
        r"\bibliographystyle{plainnat}"
    )

    result = copy_support_files(text, source_dir=source, output_dir=output)

    assert result.text == text
    assert sorted(path.name for path in output.iterdir()) == [
        "journal.cls",
        "local.sty",
        "plainnat.bst",
    ]


def test_copy_support_files_rewrites_addbibresource_to_filename(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    bib_dir = tmp_path / "bib"
    source.mkdir()
    bib_dir.mkdir()
    (bib_dir / "refs.bib").write_text("@book{x}")

    result = copy_support_files(
        r"\addbibresource{../bib/refs.bib}",
        source_dir=source,
        output_dir=output,
    )

    assert result.text == r"\addbibresource{refs.bib}"
    assert (output / "refs.bib").exists()


def test_copy_support_files_raises_for_missing_by_default(tmp_path):
    with pytest.raises(SupportFileError, match="Could not resolve"):
        copy_support_files(r"\bibliography{missing}", source_dir=tmp_path, output_dir=tmp_path)


def test_copy_support_files_can_allow_missing(tmp_path):
    result = copy_support_files(
        r"\bibliography{missing}",
        source_dir=tmp_path,
        output_dir=tmp_path,
        allow_missing=True,
    )

    assert result.text == r"\bibliography{missing}"
    assert result.files == ()
