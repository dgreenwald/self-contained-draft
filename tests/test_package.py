from self_contained_draft import __version__
from self_contained_draft.cli import main


def test_package_exports_version():
    assert __version__ == "0.1.0"


def test_cli_help_runs(capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "self-contained-draft" in captured.out


def test_cli_build_runs_from_config(tmp_path, capsys):
    paper = tmp_path / "paper.tex"
    figure = tmp_path / "plot.pdf"
    config = tmp_path / "paper.yml"
    paper.write_text(r"\includegraphics{plot}")
    figure.write_bytes(b"pdf")
    config.write_text("input: paper.tex\noutput_dir: submission\n")

    assert main(["build", str(config)]) == 0

    captured = capsys.readouterr()
    assert "Wrote" in captured.out
    assert (tmp_path / "submission" / "paper.tex").read_text() == r"\includegraphics{fig_1}"
    assert (tmp_path / "submission" / "fig_1.pdf").exists()


def test_cli_build_copy_support_files_override(tmp_path):
    paper = tmp_path / "paper.tex"
    bib = tmp_path / "refs.bib"
    config = tmp_path / "paper.yml"
    paper.write_text(r"\bibliography{refs}")
    bib.write_text("@article{x}")
    config.write_text("input: paper.tex\noutput_dir: submission\ncopy_support_files: false\n")

    assert main(["build", str(config), "--copy-support-files"]) == 0

    assert (tmp_path / "submission" / "refs.bib").exists()
