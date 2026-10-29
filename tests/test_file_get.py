"""Inlining expl3 file reads without executing their stored contents."""

import pytest

from self_contained_draft.build import build_draft, load_config
from self_contained_draft.flatten import (
    FlattenError, flatten_text, parse_file_get_command,
)
from self_contained_draft.latex import LatexParseError
from self_contained_draft.processor import process_text


@pytest.fixture(params=[flatten_text, process_text], ids=['utility', 'build-processor'])
def flatten(request):
    return request.param


def test_parse_file_get_with_comments_and_braced_variable():
    text = (
        '\\file_get:nnN% } ignored\n{data/val% } ignored\n  ue.dat}'
        '{% setup comment\n} {% target comment\n\\l_result_tl }after'
    )
    command = parse_file_get_command(text, 0)
    assert command.path_text == 'data/value.dat'
    assert not command.setup.strip()
    assert command.variable == r'\l_result_tl'
    assert text[command.end:] == 'after'


@pytest.mark.parametrize('text', [
    r'\file_get:nnN{file}{}',
    r'\file_get:nnN{file}{}not-a-variable',
    r'\file_get:nnN{file}{}{\first\second}',
    r'\file_get:nnN{file}{}{\first trailing}',
    r'\file_get:nnN{file}',
])
def test_malformed_file_get_is_rejected(text):
    with pytest.raises(LatexParseError):
        parse_file_get_command(text, 0)


def test_file_get_assigns_instead_of_inserting_content(flatten, tmp_path):
    (tmp_path / 'value.dat').write_text('0.282')
    text = r'\file_get:nnN{value.dat}{}\l_value_tl\tl_use:N\l_value_tl'
    assert flatten(text, source_path=tmp_path / 'paper.tex') == (
        '\\tl_set:Nn \\l_value_tl{0.282\n}' r'\tl_use:N\l_value_tl'
    )


def test_file_get_resolves_relative_to_nested_input_and_search_paths(flatten, tmp_path):
    (tmp_path / 'sections').mkdir()
    (tmp_path / 'data').mkdir()
    (tmp_path / 'sections/body.tex').write_text(
        r'\file_get:nnN{local}{}\l_first_tl'
        r'\file_get:nnN{shared.dat}{}\l_second_tl'
    )
    (tmp_path / 'sections/local.tex').write_text('local')
    (tmp_path / 'data/shared.dat').write_text('shared')
    # The root has a different file of the same name: the including file wins.
    (tmp_path / 'local.tex').write_text('root')
    result = flatten(r'\input{sections/body}', source_path=tmp_path / 'paper.tex',
                     search_paths=(tmp_path / 'data',))
    assert result == '\\tl_set:Nn \\l_first_tl{local\n}\\tl_set:Nn \\l_second_tl{shared\n}'


def test_file_get_does_not_process_or_execute_stored_tex(flatten, tmp_path):
    data = r'\input{missing}\def\choice{changed}\file_get:nnN{missing}{}\l_tmpa_tl'
    (tmp_path / 'value.dat').write_text(data)
    text = r'\def\choice{original}\file_get:nnN{value.dat}{}\l_value_tl\choice'
    result = flatten(text, source_path=tmp_path / 'paper.tex')
    assert result == (r'\def\choice{original}\tl_set:Nn \l_value_tl{' + data + '\n}' + r'\choice')


@pytest.mark.parametrize('strip', [True, False])
def test_file_get_comments_and_eof_preserve_assignment_braces(flatten, tmp_path, strip):
    (tmp_path / 'value.dat').write_text('0.% continuation\n  282% eof }')
    result = flatten(r'\file_get:nnN{value.dat}{}\l_value_tl',
                     source_path=tmp_path / 'paper.tex',
                     **({'strip_comments': strip} if flatten is flatten_text else {'strip_tex_comments': strip}))
    content = '0.282' if strip else '0.% continuation\n  282% eof }\n'
    assert result == r'\tl_set:Nn \l_value_tl{' + content + '}'


def test_file_get_ignores_commented_escaped_and_variant_commands(flatten, tmp_path):
    text = ('% \\file_get:nnN{missing}{}\\l_tmpa_tl\n'
            r'\\file_get:nnN{missing}{}\l_tmpa_tl' '\n'
            r'\file_get:nnNTF{missing}{}\l_tmpa_tl{yes}{no}' '\n'
            r'\file_get:VnN\l_path_tl{}\l_tmpa_tl')
    options = {'strip_comments': False} if flatten is flatten_text else {'strip_tex_comments': False}
    assert flatten(text, source_path=tmp_path / 'paper.tex', **options) == text


def test_file_get_missing_uses_input_policy(flatten, tmp_path):
    text = r'\file_get:nnN{missing}{}\l_value_tl'
    with pytest.raises(FlattenError, match=r'Could not resolve.*file_get:nnN'):
        flatten(text, source_path=tmp_path / 'paper.tex')
    retained = flatten(text, source_path=tmp_path / 'paper.tex', allow_missing_inputs=True)
    assert 'file_get:nnN' in retained and 'missing' in retained and r'\l_value_tl' in retained


def test_file_get_rejects_nonempty_setup(flatten, tmp_path):
    (tmp_path / 'value.dat').write_text('value')
    with pytest.raises(FlattenError, match='Nonempty.*setup'):
        flatten(r'\file_get:nnN{value.dat}{\ExplSyntaxOff}\l_value_tl',
                source_path=tmp_path / 'paper.tex')


@pytest.mark.parametrize('content', ['{unclosed', 'extra}', r'\{literal}'])
def test_unbalanced_file_contents_are_rejected(flatten, tmp_path, content):
    (tmp_path / 'value.dat').write_text(content)
    with pytest.raises(FlattenError, match='unbalanced file contents'):
        flatten(r'\file_get:nnN{value.dat}{}\l_value_tl', source_path=tmp_path / 'paper.tex')


@pytest.mark.parametrize('content', ['', '{balanced}', r'\{escaped\}', 'value\n', '#1'])
def test_balanced_file_contents_and_empty_files(flatten, tmp_path, content):
    (tmp_path / 'value.dat').write_text(content)
    result = flatten(r'\file_get:nnN{value.dat}{}\l_value_tl', source_path=tmp_path / 'paper.tex')
    expected = content + ('\n' if content and not content.endswith('\n') else '')
    assert result == r'\tl_set:Nn \l_value_tl{' + expected + '}'


def test_build_file_get_expands_path_helpers_and_active_definitions(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/first.dat').write_text('1.25')
    (tmp_path / 'data/second.dat').write_text('2.5')
    (tmp_path / 'paper.tex').write_text(
        r'\ExplSyntaxOn' '\n'
        r'\def\datadir{data}' '\n'
        r'\newcommand{\readValue}[1]{\file_get:nnN{\datadir/#1.dat}{}\l_value_tl}' '\n'
        r'\newcommand{\readOther}[1]{\readValue{#1}}' '\n'
        r'\readOther{first}' '\n'
        r'\input{redefine}' '\n'
        r'\file_get:nnN{\current}{}\l_other_tl' '\n'
        r'\ExplSyntaxOff'
    )
    (tmp_path / 'redefine.tex').write_text(r'\def\current{data/second.dat}')
    config_path = tmp_path / 'paper.yml'
    config_path.write_text('input: paper.tex\n')
    output = build_draft(load_config(config_path)).output_tex.read_text()
    assert r'\file_get:nnN' not in output
    assert '\\tl_set:Nn \\l_value_tl{1.25\n}' in output
    assert '\\tl_set:Nn \\l_other_tl{2.5\n}' in output
    assert r'\newcommand{\readValue}' not in output


def test_conditional_selection_skips_discarded_file_get_calls(tmp_path):
    (tmp_path / 'value.dat').write_text('42')
    text = (
        r'\ifLoadData\file_get:nnN{value.dat}{}\l_value_tl'
        r'\else\file_get:nnN{missing}{unsupported}\l_value_tl\fi'
    )
    result = process_text(text, source_path=tmp_path / 'paper.tex',
                          conditional_flags={'LoadData': True})
    assert result == '\\tl_set:Nn \\l_value_tl{42\n}'


def test_missing_braced_variable_keeps_token_separator(flatten, tmp_path):
    text = r'\file_get:nnN{missing}{}{\result}after'
    assert flatten(text, source_path=tmp_path / 'paper.tex', allow_missing_inputs=True) == text


def test_file_get_build_errors_are_readable_at_cli(tmp_path):
    from self_contained_draft.cli import main

    (tmp_path / 'paper.tex').write_text(r'\file_get:nnN{value.dat}{custom-setup}\l_value_tl')
    config = tmp_path / 'paper.yml'
    config.write_text('input: paper.tex\n')
    with pytest.raises(SystemExit, match='Nonempty.*setup'):
        main(['build', str(config)])
