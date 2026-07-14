from self_contained_draft import __version__
from self_contained_draft.cli import main


def test_package_exports_version():
    assert __version__ == "0.1.0"


def test_cli_help_runs(capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "self-contained-draft" in captured.out
