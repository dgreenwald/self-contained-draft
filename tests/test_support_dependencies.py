"""Local template dependencies and explicit bundle files."""

import pytest

from self_contained_draft.build import BuildError, build_draft, load_config
from self_contained_draft.cli import main
from self_contained_draft.support_files import ExtraFile, SupportFileError, copy_support_files


def write_file(root, name, content=""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    return path


def test_build_collects_class_style_image_chain(tmp_path):
    write_file(tmp_path, "paper.tex", r"\documentclass{template/journal}")
    write_file(tmp_path, "template/journal.cls", r"\RequirePackage{local-style}")
    style = r"\newcommand{\emailicon}{\includegraphics[height=1em]{thumbnails/cas-email.jpeg}}"
    write_file(tmp_path, "template/local-style.sty", style)
    image = b"\xff\xd8local thumbnail\xff\xd9"
    write_file(tmp_path, "template/thumbnails/cas-email.jpeg", image)
    config_path = write_file(tmp_path, "config.yml", "input: paper.tex\ncopy_support_files: true\n")

    config = load_config(config_path)
    result = build_draft(config)

    assert result.output_tex.read_text() == r"\documentclass{journal}"
    assert (config.output_dir / "journal.cls").read_text() == r"\RequirePackage{local-style}"
    assert (config.output_dir / "local-style.sty").read_text() == style
    assert (config.output_dir / "thumbnails/cas-email.jpeg").read_bytes() == image
    assert {file.output_name for file in result.support_files} == {
        "journal.cls", "local-style.sty", "thumbnails/cas-email.jpeg",
    }
    # A fresh invocation may overwrite outputs from an earlier build.
    assert build_draft(config).support_files == result.support_files


def test_transitive_inputs_options_comments_and_external_packages(tmp_path):
    cls = (
        "% \\RequirePackage{commented} }\n"
        "\\LoadClass[option]{base}\n"
        "\\RequirePackage% } ignored brace\n [foo={a]b}]{styles/local,installed}\n"
        "\\input{fragments/first}\n"
    )
    write_file(tmp_path, "templates/journal.cls", cls)
    write_file(tmp_path, "templates/base.cls", r"\LoadClass{installed-base}")
    write_file(tmp_path, "templates/styles/local.sty", r"\input{from-root}")
    write_file(tmp_path, "from-root.tex", r"\RequirePackage{from-search}")
    write_file(tmp_path, "search/from-search.sty", "search style")
    write_file(tmp_path, "templates/fragments/first.tex", r"\input{second.tex}")
    write_file(tmp_path, "templates/fragments/second.tex", (
        r"\includegraphics*[width=2em]{icons/logo}" "\n"
        r"\includegraphics{\computed}" "\n"
        r"\input{missing}" "\n"
        r"\includegraphics{missing-image}" "\n"
        r"\input unbraced.tex" "\n"
        r"\includegraphics{icons/lo% } ignored" "\n  go.jpeg}"
    ))
    write_file(tmp_path, "templates/fragments/icons/logo.jpeg", b"jpeg")
    # A commented-out reference must not copy even an existing local package.
    write_file(tmp_path, "templates/commented.sty", "commented")
    write_file(tmp_path, "templates/fragments/unbraced.tex", "unbraced")
    out = tmp_path / "out"

    result = copy_support_files(
        r"\documentclass{templates/journal}", source_dir=tmp_path,
        output_dir=out, search_paths=(tmp_path / "search",),
    )

    assert {file.output_name for file in result.files} == {
        "journal.cls", "base.cls", "local.sty", "from-root.tex", "from-search.sty",
        "fragments/first.tex", "second.tex", "icons/logo.jpeg",
    }
    copied_cls = (out / "journal.cls").read_text()
    assert "{local,installed}" in copied_cls
    assert "% \\RequirePackage{commented} }" in copied_cls
    assert r"\input{fragments/first.tex}" in copied_cls
    assert (out / "fragments/first.tex").read_text() == r"\input{second.tex}"
    copied_fragment = (out / "second.tex").read_text()
    assert r"\includegraphics*[width=2em]{icons/logo.jpeg}" in copied_fragment
    assert r"\includegraphics{\computed}" in copied_fragment
    assert r"\input{missing}" in copied_fragment
    assert r"\includegraphics{missing-image}" in copied_fragment


def test_escaping_and_absolute_dependencies_are_relocated(tmp_path):
    image = write_file(tmp_path, "external/logo.png", b"png")
    write_file(tmp_path, "templates/style.sty", (
        r"\includegraphics{../external/logo.png}" "\n"
        + r"\includegraphics{" + str(image) + "}"
    ))
    out = tmp_path / "out"
    result = copy_support_files(r"\usepackage{templates/style}", source_dir=tmp_path, output_dir=out)
    assert (out / "style.sty").read_text().count(r"\includegraphics{logo.png}") == 2
    assert [file.output_name for file in result.files] == ["style.sty", "logo.png"]


def test_shared_dependencies_and_multiple_asset_destinations(tmp_path):
    write_file(tmp_path, "a.sty", r"\RequirePackage{common}\includegraphics{logo.png}")
    write_file(tmp_path, "b.sty", r"\RequirePackage{common}\includegraphics{alias.png}")
    write_file(tmp_path, "common.sty", "common")
    image = write_file(tmp_path, "logo.png", b"png")
    (tmp_path / "alias.png").symlink_to(image)
    out = tmp_path / "out"
    result = copy_support_files(r"\usepackage{a,b}", source_dir=tmp_path, output_dir=out)
    assert len(result.files) == 5
    assert (out / "logo.png").read_bytes() == (out / "alias.png").read_bytes()
    assert (out / "common.sty").read_text() == "common"


def test_cycle_fails_with_chain_before_copying(tmp_path):
    write_file(tmp_path, "a.cls", r"\RequirePackage{b}")
    write_file(tmp_path, "b.sty", r"\input{c.tex}")
    write_file(tmp_path, "c.tex", r"\LoadClass{a}")
    out = tmp_path / "out"
    with pytest.raises(SupportFileError, match="cycle") as error:
        copy_support_files(r"\documentclass{a}", source_dir=tmp_path, output_dir=out)
    assert f"{tmp_path / 'a.cls'} -> {tmp_path / 'b.sty'} -> {tmp_path / 'c.tex'} -> {tmp_path / 'a.cls'}" in str(error.value)
    assert not out.exists()


def test_distinct_sources_with_same_basename_fail_before_copying(tmp_path):
    write_file(tmp_path, "one/local.sty", "one")
    write_file(tmp_path, "two/local.sty", "two")
    out = tmp_path / "out"
    with pytest.raises(SupportFileError, match="Filename collision.*local.sty"):
        copy_support_files(r"\usepackage{one/local,two/local}", source_dir=tmp_path, output_dir=out)
    assert not out.exists()


@pytest.mark.parametrize("destination", ["../outside", "/absolute", ".", ""])
def test_extra_files_reject_invalid_destinations(tmp_path, destination):
    config_path = write_file(tmp_path, "config.yml", (
        "input: paper.tex\nextra_files:\n"
        f"  - source: file.dat\n    destination: '{destination}'\n"
    ))
    with pytest.raises(BuildError, match="destination"):
        load_config(config_path)


@pytest.mark.parametrize("entry", ["42", "{}", "{source: file.dat}", "{source: 42, destination: out}"])
def test_extra_files_reject_invalid_entries(tmp_path, entry):
    config_path = write_file(tmp_path, "config.yml", f"input: paper.tex\nextra_files: [{entry}]\n")
    with pytest.raises(BuildError, match="extra_files"):
        load_config(config_path)


def test_extra_files_resolve_against_yaml_and_copy_without_support_flag(tmp_path, capsys):
    write_file(tmp_path, "manuscript/paper.tex", r"\documentclass{local}")
    write_file(tmp_path, "config/local.sty", r"\input{undiscovered}")
    write_file(tmp_path, "config/undiscovered.tex", "must not be copied")
    write_file(tmp_path, "config/thumbnails/custom.jpeg", b"jpeg")
    write_file(tmp_path, "shared/data.dat", b"data")
    config_path = write_file(tmp_path, "config/build.yml", (
        "input: ../manuscript/paper.tex\nextra_files:\n"
        "  - thumbnails/custom.jpeg\n  - local.sty\n"
        "  - source: ../shared/data.dat\n    destination: data/template.dat\n"
    ))
    config = load_config(config_path)
    assert not config.copy_support_files
    assert config.extra_files[0].source == tmp_path / "config/thumbnails/custom.jpeg"
    assert main(["build", str(config_path)]) == 0
    assert "Copied 3 support file(s)" in capsys.readouterr().out
    assert (config.output_dir / "thumbnails/custom.jpeg").read_bytes() == b"jpeg"
    assert (config.output_dir / "data/template.dat").read_bytes() == b"data"
    assert (config.output_dir / "local.sty").read_text() == r"\input{undiscovered}"
    assert not (config.output_dir / "undiscovered.tex").exists()


@pytest.mark.parametrize("name,is_directory", [("missing.dat", False), ("directory", True)])
def test_missing_or_directory_extra_file_fails(tmp_path, name, is_directory):
    write_file(tmp_path, "paper.tex", "paper")
    if is_directory:
        (tmp_path / name).mkdir()
    config_path = write_file(tmp_path, "config.yml", f"input: paper.tex\nextra_files: [{name}]\n")
    with pytest.raises(BuildError, match="Could not resolve extra file"):
        build_draft(load_config(config_path))


@pytest.mark.parametrize("destination", ["paper.tex", "self_contained_manifest.json", "fig_1.pdf", "fig_1.pdf/child"])
def test_extra_file_cannot_overwrite_generated_outputs(tmp_path, destination):
    write_file(tmp_path, "paper.tex", r"\includegraphics{plot}")
    write_file(tmp_path, "plot.pdf", b"pdf")
    write_file(tmp_path, "data.dat", "data")
    config_path = write_file(tmp_path, "config.yml", (
        "input: paper.tex\nextra_files:\n  - source: data.dat\n"
        f"    destination: {destination}\n"
    ))
    config = load_config(config_path)
    with pytest.raises(BuildError, match="collision"):
        build_draft(config)
    assert list(config.output_dir.iterdir()) == []


def test_support_asset_cannot_overwrite_figure(tmp_path):
    write_file(tmp_path, "paper.tex", r"\usepackage{local}\includegraphics{plot}")
    write_file(tmp_path, "local.sty", r"\includegraphics{fig_1.pdf}")
    write_file(tmp_path, "fig_1.pdf", b"template image")
    write_file(tmp_path, "plot.pdf", b"manuscript figure")
    config_path = write_file(tmp_path, "config.yml", "input: paper.tex\ncopy_support_files: true\n")
    with pytest.raises(BuildError, match="collision.*fig_1.pdf"):
        build_draft(load_config(config_path))


def test_extra_files_share_existing_destination_only_for_same_source(tmp_path):
    source = write_file(tmp_path, "local.sty", "style")
    other = write_file(tmp_path, "other.sty", "other")
    out = tmp_path / "out"
    result = copy_support_files(
        r"\usepackage{local}", source_dir=tmp_path, output_dir=out,
        extra_files=(ExtraFile(source, "./local.sty"),),
    )
    assert len(result.files) == 1
    with pytest.raises(SupportFileError, match="collision"):
        copy_support_files(
            r"\usepackage{local}", source_dir=tmp_path, output_dir=out,
            extra_files=(ExtraFile(other, "local.sty"),),
        )


def test_existing_file_directory_conflict_and_output_symlink_escape(tmp_path):
    source = write_file(tmp_path, "data.dat", "data")
    out = tmp_path / "out"
    write_file(out, "data", "existing file")
    with pytest.raises(SupportFileError, match="File/directory collision"):
        copy_support_files("", source_dir=tmp_path, output_dir=out,
                           extra_files=(ExtraFile(source, "data/child"),))
    (out / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SupportFileError, match="escapes"):
        copy_support_files("", source_dir=tmp_path, output_dir=out,
                           extra_files=(ExtraFile(source, "escape/child"),))


def test_absolute_extra_source_and_default(tmp_path):
    source = write_file(tmp_path, "data.dat", b"data")
    write_file(tmp_path, "paper.tex", "paper")
    config_path = write_file(tmp_path, "config.yml", "input: paper.tex\n")
    assert load_config(config_path).extra_files == ()
    config_path.write_text(
        f"input: paper.tex\nextra_files:\n  - source: {source}\n    destination: assets/data.dat\n"
    )
    config = load_config(config_path)
    build_draft(config)
    assert (config.output_dir / "assets/data.dat").read_bytes() == b"data"


def test_generated_output_destinations_cannot_collide(tmp_path):
    write_file(tmp_path, "paper.tex", "paper")
    config_path = write_file(tmp_path, "config.yml", (
        "input: paper.tex\noutput_tex: self_contained_manifest.json\n"
    ))
    with pytest.raises(BuildError, match="collision"):
        build_draft(load_config(config_path))


def test_cli_cycle_error_has_no_traceback(tmp_path):
    write_file(tmp_path, "paper.tex", r"\documentclass{local}")
    write_file(tmp_path, "local.cls", r"\RequirePackage{style}")
    write_file(tmp_path, "style.sty", r"\LoadClass{local}")
    config_path = write_file(tmp_path, "config.yml", "input: paper.tex\ncopy_support_files: true\n")
    with pytest.raises(SystemExit, match="Support dependency cycle"):
        main(["build", str(config_path)])
