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


def test_build_draft_expands_root_macros_after_flattening(tmp_path):
    root = tmp_path / "paper.tex"
    section = tmp_path / "body.tex"
    figure_dir = tmp_path / "figures"
    output = tmp_path / "submission"
    figure_dir.mkdir()
    (figure_dir / "plot.pdf").write_bytes(b"pdf")
    root.write_text(r"\def\figdir{figures}" "\n" r"\input{body}")
    section.write_text(r"\includegraphics{\figdir/plot}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "expand_macros:",
                "  - figdir",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\def\figdir{figures}" "\n" r"\includegraphics{fig_1}"
    assert (output / "fig_1.pdf").exists()


def test_build_draft_can_inline_configured_property_macros(tmp_path):
    root = tmp_path / "paper.tex"
    values = tmp_path / "values.tex"
    output = tmp_path / "submission"
    root.write_text(
        r"\input{values}"
        "\n"
        r"Debt share: \topct{\steady{baseline_debt_share}}."
    )
    values.write_text(
        r"\ExplSyntaxOn"
        "\n"
        r"\prop_if_exist:NF \g_equilibrium_steady_prop { \prop_new:N \g_equilibrium_steady_prop }"
        "\n"
        r"\prop_gput:Nnn \g_equilibrium_steady_prop {baseline_debt_share} {0.282}"
        "\n"
        r"\cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} }"
        "\n"
        r"\ExplSyntaxOff"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "inline_property_macros:",
                "  - steady",
            ]
        )
        + "\n"
    )

    result = build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == (
        r"\ExplSyntaxOn"
        "\n"
        r"\cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} }"
        "\n"
        r"\ExplSyntaxOff"
        "\n"
        r"Debt share: \topct{0.282}."
    )
    assert result.inlined_property_macros == ("steady",)
    assert result.inlined_property_replacements == 1
    assert result.removed_property_assignments == 1


def test_build_draft_uses_figure_aux_for_output_names(tmp_path):
    root = tmp_path / "paper.tex"
    figure = tmp_path / "plot.pdf"
    aux = tmp_path / "paper.aux"
    output = tmp_path / "submission"
    figure.write_bytes(b"pdf")
    aux.write_text(r"\newlabel{fig:plot}{{B.2}{4}{Plot}{figure.caption.2}{}}")
    root.write_text(r"\begin{figure}\includegraphics{plot}\label{fig:plot}\end{figure}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "figure_aux: paper.aux",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == (
        r"\begin{figure}\includegraphics{fig_B2}\label{fig:plot}\end{figure}"
    )
    assert (output / "fig_B2.pdf").exists()


def test_build_draft_does_not_expand_commented_configured_macros(tmp_path):
    root = tmp_path / "paper.tex"
    output = tmp_path / "submission"
    root.write_text(
        r"%\newcommand{\readValue}[1]{bad}"
        "\n"
        r"\newcommand{\readValue}[2]{#1/#2}"
        "\n"
        r"\readValue{a}{b}"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "expand_macros:",
                "  - readValue",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == "\na/b"


def test_build_draft_does_not_flatten_input_inside_expanded_helper_definition(tmp_path):
    root = tmp_path / "paper.tex"
    data = tmp_path / "data"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "value.tex").write_text("42")
    root.write_text(
        r"\def\datadir{data}"
        "\n"
        r"\newcommand{\readValue}[1]{\input{\datadir/#1}}"
        "\n"
        r"\readValue{value}"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "expand_macros:",
                "  - datadir",
                "  - readValue",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\def\datadir{data}" "\n\n42"


def test_build_draft_removes_helper_definitions_after_offset_shifting_expansion(tmp_path):
    root = tmp_path / "paper.tex"
    data = tmp_path / "long-directory-name"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "value.tex").write_text("42")
    root.write_text(
        r"\def\dir{long-directory-name}"
        "\n"
        r"\input{\dir/value}"
        "\n"
        r"\newcommand{\readValue}[1]{\input{\dir/#1}}"
        "\n"
        r"\readValue{value}"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "expand_macros:",
                "  - dir",
                "  - readValue",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\def\dir{long-directory-name}" "\n42\n\n42"


def test_build_draft_honors_if_file_exists_localpath_override(tmp_path):
    root = tmp_path / "paper.tex"
    output = tmp_path / "submission"
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    (local_data / "value.tex").write_text("local")
    (tmp_path / "localpaths.tex").write_text(r"\def\drop{local_data}")
    root.write_text(
        r"\def\drop{/missing}"
        "\n"
        r"\IfFileExists{localpaths.tex}{\input{localpaths.tex}}{}"
        "\n"
        r"\def\datadir{\drop}"
        "\n"
        r"\input{\datadir/value}"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "expand_macros:",
                "  - drop",
                "  - datadir",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text().endswith("\nlocal")


def test_build_draft_flattens_inputs_created_by_macros_in_included_files(tmp_path):
    root = tmp_path / "paper.tex"
    section = tmp_path / "section.tex"
    data = tmp_path / "data"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "value.tex").write_text("included")
    root.write_text(r"\input{section}")
    section.write_text(
        r"\def\thisdir{data}"
        "\n"
        r"\newcommand{\readValue}[1]{\input{\thisdir/#1}}"
        "\n"
        r"\readValue{value}"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "expand_macros:",
                "  - thisdir",
                "  - readValue",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\def\thisdir{data}" "\n\nincluded"


def test_build_draft_auto_resolves_root_path_macros_in_nested_inputs(tmp_path):
    root = tmp_path / "paper.tex"
    section = tmp_path / "section.tex"
    data = tmp_path / "data"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "value.tex").write_text("nested")
    root.write_text(r"\def\datadir{data}" "\n" r"\input{section}")
    section.write_text(r"\input{\datadir/value}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\def\datadir{data}" "\n" "nested"


def test_build_draft_auto_uses_nested_path_macro_redefinition(tmp_path):
    root = tmp_path / "paper.tex"
    section = tmp_path / "section.tex"
    data = tmp_path / "section-data"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "plot.pdf").write_bytes(b"pdf")
    root.write_text(r"\def\thisdir{root-data}" "\n" r"\input{section}")
    section.write_text(r"\def\thisdir{section-data}" "\n" r"\includegraphics{\thisdir/plot}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == (
        r"\def\thisdir{root-data}" "\n" r"\def\thisdir{section-data}" "\n" r"\includegraphics{fig_1}"
    )
    assert (output / "fig_1.pdf").exists()


def test_build_draft_auto_expands_path_helper_macros(tmp_path):
    root = tmp_path / "paper.tex"
    data = tmp_path / "data"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "value.tex").write_text("42")
    root.write_text(
        r"\def\datadir{data}"
        "\n"
        r"\newcommand{\readValue}[1]{\input{\datadir/#1}}"
        "\n"
        r"\readValue{value}"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\def\datadir{data}" "\n\n42"


def test_build_draft_auto_expands_transitive_path_helper_macros(tmp_path):
    root = tmp_path / "paper.tex"
    data = tmp_path / "data"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "a.tex").write_text("1")
    (data / "b.tex").write_text("2")
    root.write_text(
        r"\def\datadir{data}"
        "\n"
        r"\newcommand{\readValue}[1]{\input{\datadir/#1}}"
        "\n"
        r"\newcommand{\readRow}[2]{\readValue{#1} & \readValue{#2} \\}"
        "\n"
        r"\readRow{a}{b}"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == "\\def\\datadir{data}\n\n\n1 & 2 \\\\"


def test_build_draft_auto_expands_zero_argument_path_helper_macros(tmp_path):
    root = tmp_path / "paper.tex"
    data = tmp_path / "data"
    output = tmp_path / "submission"
    data.mkdir()
    (data / "value.tex").write_text("42")
    root.write_text(
        r"\def\datadir{data}"
        "\n"
        r"\newcommand{\readValue}{\input{\datadir/value}}"
        "\n"
        r"\readValue"
    )
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\def\datadir{data}" "\n\n42"


def test_build_draft_leaves_non_path_macros_unexpanded_unless_configured(tmp_path):
    root = tmp_path / "paper.tex"
    output = tmp_path / "submission"
    root.write_text(r"\newcommand{\term}[1]{Term: #1}" "\n" r"\term{spread}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == (
        r"\newcommand{\term}[1]{Term: #1}" "\n" r"\term{spread}"
    )


def test_build_draft_expands_configured_non_path_macros(tmp_path):
    root = tmp_path / "paper.tex"
    output = tmp_path / "submission"
    root.write_text(r"\newcommand{\term}[1]{Term: #1}" "\n" r"\term{spread}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text(
        "\n".join(
            [
                "input: paper.tex",
                "output_dir: submission",
                "expand_macros:",
                "  - term",
            ]
        )
        + "\n"
    )

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == "\nTerm: spread"


def test_build_draft_auto_resolves_path_macros_in_support_files(tmp_path):
    root = tmp_path / "paper.tex"
    refs = tmp_path / "refs"
    output = tmp_path / "submission"
    refs.mkdir()
    (refs / "main.bib").write_text("@article{x}")
    root.write_text(r"\def\bibdir{refs}" "\n" r"\bibliography{\bibdir/main}")
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

    assert (output / "paper.tex").read_text() == r"\def\bibdir{refs}" "\n" r"\bibliography{main}"
    assert (output / "main.bib").exists()
    assert [file.output_name for file in result.support_files] == ["main.bib"]


def test_build_draft_auto_expands_support_file_helper_macros(tmp_path):
    root = tmp_path / "paper.tex"
    refs = tmp_path / "refs"
    output = tmp_path / "submission"
    refs.mkdir()
    (refs / "main.bib").write_text("@article{x}")
    root.write_text(
        r"\def\bibdir{refs}"
        "\n"
        r"\newcommand{\loadrefs}{\bibliography{\bibdir/main}}"
        "\n"
        r"\loadrefs"
    )
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

    assert (output / "paper.tex").read_text() == r"\def\bibdir{refs}" "\n\n" r"\bibliography{main}"
    assert (output / "main.bib").exists()
    assert [file.output_name for file in result.support_files] == ["main.bib"]


def test_build_draft_does_not_parse_bibliographystyle_as_bibliography(tmp_path):
    root = tmp_path / "paper.tex"
    style = tmp_path / "journal.bst"
    output = tmp_path / "submission"
    style.write_text("style")
    root.write_text(r"\bibliographystyle{journal}")
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

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == r"\bibliographystyle{journal}"
    assert (output / "journal.bst").exists()


def test_build_draft_does_not_parse_special_command_prefixes(tmp_path):
    root = tmp_path / "paper.tex"
    output = tmp_path / "submission"
    root.write_text(r"\inputfoo{not-a-file}" "\n" r"\bibliographyextra{not-a-bib}")
    config_file = tmp_path / "paper.yml"
    config_file.write_text("input: paper.tex\noutput_dir: submission\n")

    build_draft(load_config(config_file))

    assert (output / "paper.tex").read_text() == (
        r"\inputfoo{not-a-file}" "\n" r"\bibliographyextra{not-a-bib}"
    )


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


def test_build_draft_skips_missing_support_files_when_copying(tmp_path):
    root = tmp_path / "paper.tex"
    bib = tmp_path / "refs.bib"
    output = tmp_path / "submission"
    root.write_text(r"\documentclass{missing-local-class}" "\n" r"\bibliography{refs}")
    bib.write_text("@article{x}")
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
    assert not (output / "missing-local-class.cls").exists()
    assert [file.output_name for file in result.support_files] == ["refs.bib"]
