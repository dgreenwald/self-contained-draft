import json

from self_contained_draft.build import build_draft, load_config


def test_acceptance_builds_self_contained_submission_bundle(tmp_path):
    sections = tmp_path / "sections"
    figures = tmp_path / "figures"
    output = tmp_path / "submission"
    sections.mkdir()
    figures.mkdir()

    (figures / "panel_a.pdf").write_bytes(b"a")
    (figures / "panel_b.pdf").write_bytes(b"b")
    (tmp_path / "refs.bib").write_text("@article{x}")
    (tmp_path / "journal.cls").write_text("class")
    (tmp_path / "appendix.aux").write_text(
        r"\newlabel{sec:appendix}{{A.1}{1}{Appendix}{appendix.A}{}}"
    )
    (sections / "body.tex").write_text(
        r"Body % remove comment"
        "\n"
        r"See Appendix \ref{sec:appendix}."
        "\n"
        r"\begin{figure}"
        "\n"
        r"\includegraphics[width=.45\linewidth]{\figdir/panel_a}"
        "\n"
        r"\includegraphics[width=.45\linewidth]{\figdir/panel_b}"
        "\n"
        r"\end{figure}"
        "\n"
        r"Again \includegraphics{\figdir/panel_a}."
    )
    (tmp_path / "paper.tex").write_text(
        r"\documentclass{journal}"
        "\n"
        r"\def\figdir{figures}"
        "\n"
        r"\input{sections/body}"
        "\n"
        r"\bibliography{refs}"
    )
    config = tmp_path / "paper.yml"
    config.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "output_tex: final.tex",
                "expand_macros:",
                "  - figdir",
                "external_aux:",
                "  - appendix.aux",
                "copy_support_files: true",
            ]
        )
        + "\n"
    )

    result = build_draft(load_config(config))

    final_text = (output / "final.tex").read_text()
    assert final_text == (
        r"\documentclass{journal}"
        "\n"
        r"\def\figdir{figures}"
        "\n"
        "Body \n"
        "See Appendix A.1.\n"
        r"\begin{figure}"
        "\n"
        r"\includegraphics[width=.45\linewidth]{fig_1a}"
        "\n"
        r"\includegraphics[width=.45\linewidth]{fig_1b}"
        "\n"
        r"\end{figure}"
        "\n"
        r"Again \includegraphics{fig_1a}."
        "\n"
        r"\bibliography{refs}"
    )
    assert (output / "fig_1a.pdf").read_bytes() == b"a"
    assert (output / "fig_1b.pdf").read_bytes() == b"b"
    assert (output / "refs.bib").exists()
    assert (output / "journal.cls").exists()
    assert result.replaced_refs == ("sec:appendix",)
    assert sorted(file.output_name for file in result.support_files) == [
        "journal.cls",
        "refs.bib",
    ]

    manifest = json.loads((output / "self_contained_manifest.json").read_text())
    assert [item["output_name"] for item in manifest] == ["fig_1a.pdf", "fig_1b.pdf"]
