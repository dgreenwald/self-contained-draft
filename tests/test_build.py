from self_contained_draft.build import build_draft, load_config


def test_load_config_defaults_copy_support_files_to_false(tmp_path):
    config_file = tmp_path / "paper.yml"
    (tmp_path / "paper.tex").write_text("text")
    config_file.write_text("input: paper.tex\n")

    config = load_config(config_file)

    assert config.copy_support_files is False
    assert config.output_tex == "paper.tex"
    assert config.output_dir == (tmp_path / "submission").resolve()


def test_build_draft_writes_flattened_tex_and_copies_figures(tmp_path):
    root = tmp_path / "paper.tex"
    section = tmp_path / "body.tex"
    figure = tmp_path / "plot.pdf"
    output = tmp_path / "submission"
    root.write_text(
        r"\def\figdir{.}"
        "\n"
        r"\input{body}"
        "\n"
        r"\includegraphics{\figdir/plot}"
    )
    section.write_text(r"See \ref{sec:appendix}.")
    figure.write_bytes(b"pdf")
    aux = tmp_path / "appendix.aux"
    aux.write_text(r"\newlabel{sec:appendix}{{A}{1}{Appendix}{appendix.A}{}}")

    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "output_tex: final.tex",
                "expand_macros:",
                "  - figdir",
                "external_aux:",
                "  - appendix.aux",
            ]
        )
        + "\n"
    )

    result = build_draft(load_config(config_file))

    assert result.output_tex == output.resolve() / "final.tex"
    assert result.output_tex.read_text() == (
        r"\def\figdir{.}"
        "\n"
        r"See A."
        "\n"
        r"\includegraphics{fig_1}"
    )
    assert (output / "fig_1.pdf").exists()
    assert result.replaced_refs == ("sec:appendix",)


def test_build_draft_does_not_copy_support_files_by_default(tmp_path):
    root = tmp_path / "paper.tex"
    bib = tmp_path / "master.bib"
    output = tmp_path / "submission"
    root.write_text(r"\bibliography{master}")
    bib.write_text("@article{x}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\bibliography{master}"
    assert not (output / "master.bib").exists()


def test_build_draft_can_copy_support_files(tmp_path):
    root = tmp_path / "paper.tex"
    bib = tmp_path / "refs.bib"
    cls = tmp_path / "journal.cls"
    output = tmp_path / "submission"
    root.write_text(r"\documentclass{journal}" "\n" r"\bibliography{refs}")
    bib.write_text("@article{x}")
    cls.write_text("class")
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "copy_support_files: true",
            ]
        )
        + "\n"
    )

    result = build_draft(load_config(config_file))

    assert (output / "refs.bib").exists()
    assert (output / "journal.cls").exists()
    assert sorted(file.output_name for file in result.support_files) == [
        "journal.cls",
        "refs.bib",
    ]
