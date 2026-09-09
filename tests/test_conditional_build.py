import json

import pytest

from self_contained_draft.build import BuildError, build_draft, load_config
from self_contained_draft.cli import main


def config_file(tmp_path, extra=""):
    path = tmp_path / "paper.yml"
    path.write_text("input: paper.tex\n" + extra)
    return path


def test_config_defaults_and_overrides(tmp_path):
    path = config_file(tmp_path)
    assert load_config(path).conditional_flags == {}
    path = config_file(tmp_path, "conditional_flags:\n  MyFlag: true\n  Other: false\n")
    assert load_config(path, conditional_flags_override={"MyFlag": False}).conditional_flags == {
        "MyFlag": False, "Other": False,
    }


@pytest.mark.parametrize("yaml_value", ["null", "[]", "false", "{MyFlag: 'false'}", "{MyFlag: 1}",
                                        "{Bad1: true}", "{ifMyFlag: true}"])
def test_invalid_yaml_flags_fail(tmp_path, yaml_value):
    with pytest.raises(BuildError):
        load_config(config_file(tmp_path, "conditional_flags: " + yaml_value + "\n"))


def test_cli_overrides_and_last_value_wins(tmp_path):
    (tmp_path / "paper.tex").write_text(r"\ifMyFlag yes\else no\fi\ifOther A\else B\fi")
    path = config_file(tmp_path, "conditional_flags: {MyFlag: true, Other: false}\n")
    assert main(["build", str(path), "--flag", "MyFlag=true", "--flag", "MyFlag=false"]) == 0
    assert (tmp_path / "submission" / "paper.tex").read_text() == "noB"


def test_cli_flag_without_yaml_flags(tmp_path):
    (tmp_path / "paper.tex").write_text(r"\ifMyFlag yes\else no\fi")
    assert main(["build", str(config_file(tmp_path)), "--flag", "MyFlag=true"]) == 0
    assert (tmp_path / "submission" / "paper.tex").read_text() == "yes"


@pytest.mark.parametrize("argument", ["MyFlag", "MyFlag=1", "MyFlag=True", "=true", "Bad1=true",
                                      "\\MyFlag=true", "MyFlag=true=false"])
def test_invalid_cli_flag_is_an_argument_error(tmp_path, argument, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["build", str(config_file(tmp_path)), "--flag", argument])
    assert exc.value.code == 2
    assert "--flag" in capsys.readouterr().err


def test_missing_fi_is_a_contextual_build_error(tmp_path):
    (tmp_path / "paper.tex").write_text(r"\ifMyFlag yes")
    path = config_file(tmp_path, "conditional_flags: {MyFlag: true}\n")
    with pytest.raises(BuildError, match=r"Missing.*paper.tex.*offset"):
        build_draft(load_config(path))


def test_included_declarations_and_selected_macro_definitions(tmp_path):
    (tmp_path / "flags.tex").write_text(r"\newif\ifOther")
    (tmp_path / "body.tex").write_text(r"\ifMyFlag\def\word{yes}\else\def\word{no}\fi")
    (tmp_path / "paper.tex").write_text(
        r"\input{flags}\input{body}\word "
        r"\ifMyFlag\ifOther A\else B\fi\else C\fi"
    )
    path = config_file(tmp_path, "conditional_flags: {MyFlag: true}\nexpand_macros: [word]\n")
    result = build_draft(load_config(path))
    assert result.output_tex.read_text() == r"\newif\ifOther\def\word{yes}yes \ifOther A\else B\fi"


def test_expanded_helpers_with_conditionals_and_path_arguments(tmp_path):
    (tmp_path / "yes.tex").write_text("selected")
    (tmp_path / "paper.tex").write_text(
        r"\newcommand{\choose}[1]{\ifMyFlag #1\else\input{missing}\fi}"
        r"\choose{\input{\ifMyFlag yes\else absent\fi}}"
    )
    path = config_file(tmp_path, "conditional_flags: {MyFlag: true}\nexpand_macros: [choose]\n")
    assert build_draft(load_config(path)).output_tex.read_text() == "selected"


def test_conditional_bundle_acceptance(tmp_path):
    (tmp_path / "plot.pdf").write_bytes(b"selected figure")
    (tmp_path / "unused.pdf").write_bytes(b"discarded figure")
    (tmp_path / "refs.bib").write_text("@article{selected}")
    (tmp_path / "body.tex").write_text(
        r"\ifPublish\prop_gput:Nnn \g_values_prop {key} {1}"
        r"\includegraphics{plot}\bibliography{refs}"
        r"\else\input{missing}\includegraphics{unused}\includegraphics{absent}"
        r"\bibliography{missing}\prop_gput:Nnn \g_values_prop {key} {999}\fi"
    )
    (tmp_path / "paper.tex").write_text(
        r"\newif\ifPublish \Publishfalse "
        r"\cs_new:Npn \value #1 { \prop_item:Nn \g_values_prop {#1} }"
        r"\input{body}\value{key}"
    )
    path = config_file(tmp_path, "conditional_flags: {Publish: true}\n"
                       "copy_support_files: true\ninline_property_macros: [value]\n")
    result = build_draft(load_config(path))
    output = result.output_tex.read_text()
    assert r"\Publishfalse" in output
    assert r"\includegraphics{fig_1}" in output
    assert output.endswith("1")
    assert "999" not in output
    assert "missing" not in output
    assert result.inlined_property_replacements == 1
    assert result.removed_property_assignments == 1
    assert sorted(p.name for p in result.output_tex.parent.iterdir()) == [
        "fig_1.pdf", "paper.tex", "refs.bib", "self_contained_manifest.json",
    ]
    manifest = json.loads((result.output_tex.parent / "self_contained_manifest.json").read_text())
    assert len(manifest) == 1
    assert manifest[0]["original_path"] == "plot"


def test_discarded_macro_argument_is_not_expanded(tmp_path):
    (tmp_path / "paper.tex").write_text(
        r"\def\loop{\loop}\newcommand{\identity}[1]{#1}"
        r"\identity{\ifMyFlag yes\else\loop\fi}"
    )
    path = config_file(tmp_path, "conditional_flags: {MyFlag: true}\nexpand_macros: [identity]\n")
    assert build_draft(load_config(path)).output_tex.read_text() == r"\def\loop{\loop}yes"
