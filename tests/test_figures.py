import json

import pytest

from self_contained_draft.figures import (
    FigureError,
    assign_output_names,
    find_includegraphics,
    resolve_graphics_path,
    rewrite_figures,
)


def test_find_includegraphics_preserves_options_and_path_span():
    text = r"\includegraphics[width=\textwidth,page=2]{figures/source}"

    include = find_includegraphics(text)[0]

    assert include.options == r"width=\textwidth,page=2"
    assert include.path_text == "figures/source"
    assert text[include.path_start : include.path_end] == "{figures/source}"


def test_assign_output_names_for_document_order_and_panels():
    text = (
        r"\begin{figure}"
        r"\includegraphics{a}"
        r"\includegraphics{b}"
        r"\end{figure}"
        r"\includegraphics{c}"
    )
    includes = find_includegraphics(text)

    assert assign_output_names(includes) == {
        includes[0].start: "fig_1a",
        includes[1].start: "fig_1b",
        includes[2].start: "fig_2",
    }


def test_single_include_inside_figure_has_no_panel_suffix():
    text = r"\begin{figure}\includegraphics{a}\end{figure}"
    includes = find_includegraphics(text)

    assert assign_output_names(includes) == {includes[0].start: "fig_1"}


def test_resolve_graphics_path_tries_common_extensions(tmp_path):
    figure = tmp_path / "plot.pdf"
    figure.write_bytes(b"pdf")

    assert resolve_graphics_path("plot", current_dir=tmp_path) == figure.resolve()


def test_resolve_graphics_path_uses_search_paths(tmp_path):
    source = tmp_path / "tex"
    figures = tmp_path / "figures"
    source.mkdir()
    figures.mkdir()
    figure = figures / "plot.png"
    figure.write_bytes(b"png")

    assert (
        resolve_graphics_path("plot", current_dir=source, search_paths=(figures,))
        == figure.resolve()
    )


def test_rewrite_figures_copies_assets_and_preserves_options(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    source.mkdir()
    figure = source / "plot.pdf"
    figure.write_bytes(b"pdf-data")
    text = r"\includegraphics[width=\linewidth]{plot}"

    result = rewrite_figures(text, source_dir=source, output_dir=output)

    assert result.text == r"\includegraphics[width=\linewidth]{fig_1}"
    assert (output / "fig_1.pdf").read_bytes() == b"pdf-data"
    assert result.assets[0].original_path == "plot"
    assert result.assets[0].output_name == "fig_1.pdf"


def test_rewrite_figures_writes_manifest(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    source.mkdir()
    (source / "plot.pdf").write_bytes(b"pdf")

    rewrite_figures(r"\includegraphics{plot}", source_dir=source, output_dir=output)

    manifest = json.loads((output / "self_contained_manifest.json").read_text())
    assert manifest[0]["original_path"] == "plot"
    assert manifest[0]["output_name"] == "fig_1.pdf"


def test_rewrite_figures_reuses_copied_asset_for_duplicate_source(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    source.mkdir()
    (source / "plot.pdf").write_bytes(b"pdf")
    text = r"\includegraphics{plot} and \includegraphics{plot}"

    result = rewrite_figures(text, source_dir=source, output_dir=output)

    assert result.text == r"\includegraphics{fig_1} and \includegraphics{fig_1}"
    assert [asset.output_name for asset in result.assets] == ["fig_1.pdf"]


def test_rewrite_figures_names_subfigures(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    source.mkdir()
    (source / "left.pdf").write_bytes(b"left")
    (source / "right.pdf").write_bytes(b"right")
    text = (
        r"\begin{figure}"
        r"\includegraphics{left}"
        r"\includegraphics{right}"
        r"\end{figure}"
    )

    result = rewrite_figures(text, source_dir=source, output_dir=output)

    assert result.text == (
        r"\begin{figure}"
        r"\includegraphics{fig_1a}"
        r"\includegraphics{fig_1b}"
        r"\end{figure}"
    )
    assert (output / "fig_1a.pdf").exists()
    assert (output / "fig_1b.pdf").exists()


def test_rewrite_figures_can_use_aux_labels_for_output_names(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    source.mkdir()
    (source / "left.pdf").write_bytes(b"left")
    (source / "right.pdf").write_bytes(b"right")
    aux = source / "paper.aux"
    aux.write_text(
        r"\newlabel{fig:left}{{A.1a}{3}{Left}{figure.caption.1}{}}"
        "\n"
        r"\newlabel{fig:right}{{A.1b}{3}{Right}{figure.caption.1}{}}"
    )
    text = (
        r"\begin{figure}"
        r"\includegraphics{left}\label{fig:left}"
        r"\includegraphics{right}\label{fig:right}"
        r"\end{figure}"
    )

    result = rewrite_figures(text, source_dir=source, output_dir=output, aux_file=aux)

    assert result.text == (
        r"\begin{figure}"
        r"\includegraphics{fig_A1a}\label{fig:left}"
        r"\includegraphics{fig_A1b}\label{fig:right}"
        r"\end{figure}"
    )
    assert (output / "fig_A1a.pdf").read_bytes() == b"left"
    assert (output / "fig_A1b.pdf").read_bytes() == b"right"


def test_rewrite_figures_falls_back_when_aux_label_is_missing(tmp_path):
    source = tmp_path / "paper"
    output = tmp_path / "submission"
    source.mkdir()
    (source / "plot.pdf").write_bytes(b"pdf")
    aux = source / "paper.aux"
    aux.write_text("")

    result = rewrite_figures(
        r"\begin{figure}\includegraphics{plot}\label{fig:plot}\end{figure}",
        source_dir=source,
        output_dir=output,
        aux_file=aux,
    )

    assert result.text == r"\begin{figure}\includegraphics{fig_1}\label{fig:plot}\end{figure}"
    assert (output / "fig_1.pdf").exists()


def test_rewrite_figures_can_preserve_missing_figures(tmp_path):
    output = tmp_path / "submission"

    result = rewrite_figures(
        r"\includegraphics{missing}",
        source_dir=tmp_path,
        output_dir=output,
        allow_missing_figures=True,
    )

    assert result.text == r"\includegraphics{missing}"
    assert result.assets == ()


def test_rewrite_figures_raises_for_missing_figures_by_default(tmp_path):
    with pytest.raises(FigureError, match="Could not resolve"):
        rewrite_figures(r"\includegraphics{missing}", source_dir=tmp_path, output_dir=tmp_path)
