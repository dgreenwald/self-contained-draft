"""Path-aware LaTeX processing for self-contained draft builds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
import re

from .conditionals import ConditionalSimplifier, validate_flags
from .flatten import FlattenError, resolve_input_path
from .latex import (
    LatexParseError,
    append_tex_replacement,
    iter_control_sequences,
    join_tex_fragments,
    protect_trailing_control_word,
    read_balanced,
    read_required_argument,
    read_macro_arguments,
    read_macro_parameters,
    strip_comments,
)
from .macros import MacroDefinition, substitute_arguments


class ProcessError(RuntimeError):
    """Raised when path-aware LaTeX processing fails."""


@dataclass(frozen=True)
class ProcessOptions:
    search_paths: tuple[Path, ...] = ()
    strip_comments: bool = True
    allow_missing_inputs: bool = False
    explicit_macros: frozenset[str] = frozenset()
    conditionals: ConditionalSimplifier | None = None


COMMAND_PATTERN = re.compile(
    r"\\(?:(?:IfFileExists|input|includegraphics|bibliographystyle|bibliography|"
    r"addbibresource|documentclass|usepackage|(?:re)?newcommand\*?|def)(?![A-Za-z@])|"
    r"[A-Za-z@]+)"
)
SUPPORT_COMMANDS = {
    "bibliography",
    "bibliographystyle",
    "addbibresource",
    "documentclass",
    "usepackage",
}
PATH_COMMAND_TOKENS = tuple(
    rf"\{name}"
    for name in (
        "input",
        "includegraphics",
        "bibliography",
        "bibliographystyle",
        "addbibresource",
        "documentclass",
        "usepackage",
    )
)


def process_file(
    path: str | Path,
    *,
    search_paths: tuple[str | Path, ...] = (),
    strip_tex_comments: bool = True,
    allow_missing_inputs: bool = False,
    explicit_macros: tuple[str, ...] = (),
    conditional_flags: Mapping[str, bool] | None = None,
) -> str:
    """Flatten a root file while resolving macros only in path contexts."""

    root = Path(path).expanduser().resolve()
    options = ProcessOptions(
        search_paths=_normalize_search_paths(search_paths, base_dir=root.parent),
        strip_comments=strip_tex_comments,
        allow_missing_inputs=allow_missing_inputs,
        explicit_macros=frozenset(_normalize_name(name) for name in explicit_macros),
        conditionals=_conditional_options(conditional_flags),
    )
    return _process_file(root, env={}, options=options, stack=())


def process_text(
    text: str,
    *,
    source_path: str | Path,
    search_paths: tuple[str | Path, ...] = (),
    strip_tex_comments: bool = True,
    allow_missing_inputs: bool = False,
    explicit_macros: tuple[str, ...] = (),
    conditional_flags: Mapping[str, bool] | None = None,
) -> str:
    """Process already-loaded text with a source path for relative resolution."""

    source = Path(source_path).expanduser().resolve()
    options = ProcessOptions(
        search_paths=_normalize_search_paths(search_paths, base_dir=source.parent),
        strip_comments=strip_tex_comments,
        allow_missing_inputs=allow_missing_inputs,
        explicit_macros=frozenset(_normalize_name(name) for name in explicit_macros),
        conditionals=_conditional_options(conditional_flags),
    )
    return _process_text(text, source_path=source, env={}, options=options, stack=(source,))


def expand_path_text(text: str, env: dict[str, MacroDefinition]) -> str:
    """Expand zero-argument macros in a path-like string."""

    return _expand_zero_arg_macros(text, env, stack=())


def _conditional_options(flags: Mapping[str, bool] | None) -> ConditionalSimplifier | None:
    validated = validate_flags({} if flags is None else flags)
    return ConditionalSimplifier(validated) if validated else None


def _process_file(
    path: Path,
    *,
    env: dict[str, MacroDefinition],
    options: ProcessOptions,
    stack: tuple[Path, ...],
) -> str:
    resolved = path.resolve()
    if resolved in stack:
        chain = " -> ".join(str(item) for item in (*stack, resolved))
        raise FlattenError(f"Detected recursive \\input cycle: {chain}")
    try:
        text = resolved.read_text()
    except OSError as exc:
        raise FlattenError(f"Could not read input file {resolved}: {exc}") from exc
    return _process_text(
        text,
        source_path=resolved,
        env=env,
        options=options,
        stack=(*stack, resolved),
    )


def _process_text(
    text: str,
    *,
    source_path: Path,
    env: dict[str, MacroDefinition],
    options: ProcessOptions,
    stack: tuple[Path, ...],
) -> str:
    if options.strip_comments:
        text = strip_comments(text)

    output: list[str] = []
    cursor = 0
    tokens = iter(iter_control_sequences(text)) if options.conditionals is not None else None
    while cursor < len(text):
        if tokens is not None:
            token = next(tokens, None)
            while token is not None and token.start < cursor:
                token = next(tokens, None)
            match = COMMAND_PATTERN.match(text, token.start) if token is not None else None
            if token is not None and match is None:
                output.append(text[cursor:token.end])
                cursor = token.end
                continue
        else:
            match = COMMAND_PATTERN.search(text, cursor)
        if match is None:
            output.append(text[cursor:])
            break

        command = match.group(0)
        name = command.removeprefix("\\")
        output.append(text[cursor : match.start()])

        if options.conditionals is not None:
            if name == "newif":
                end = options.conditionals.declaration_end(text, token)
                output.append(text[match.start():end])
                cursor = end
                continue
            if options.conditionals.configured(name):
                branch, end = options.conditionals.select(text, token, source=str(source_path))
                replacement = _process_text(
                    branch, source_path=source_path, env=env, options=options, stack=stack,
                )
                # The deleted delimiters used to separate adjacent TeX tokens.
                combined = join_tex_fragments("".join(output), replacement)
                output = [protect_trailing_control_word(combined, following=text[end:])]
                cursor = end
                continue
            operand_end = options.conditionals.operand_end(text, token, source=str(source_path))
            if operand_end > token.end:
                output.append(text[match.start():operand_end])
                cursor = operand_end
                continue

        if name == "def":
            definition = _parse_def(text, match.start(), source=str(source_path))
            if definition is None:
                output.append(command)
                cursor = match.end()
                continue
            original_content = definition.content
            definition = _simplify_definition(definition, options, source_path)
            env[definition.name] = definition
            if _should_remove_definition(definition, options, env):
                cursor = definition.end
            else:
                output.append(_definition_text(text, match.start(), definition, original_content))
                cursor = definition.end
            continue

        if name in {"newcommand", "renewcommand", "newcommand*", "renewcommand*"}:
            definition = _parse_newcommand(text, match.start(), source=str(source_path))
            original_content = definition.content
            definition = _simplify_definition(definition, options, source_path)
            env[definition.name] = definition
            if _should_remove_definition(definition, options, env):
                cursor = definition.end
            else:
                output.append(_definition_text(text, match.start(), definition, original_content))
                cursor = definition.end
            continue

        if name == "IfFileExists":
            replacement, end = _process_if_file_exists(
                text,
                match.start(),
                source_path=source_path,
                env=env,
                options=options,
                stack=stack,
            )
            append_tex_replacement(output, replacement, following=text[end:])
            cursor = end
            continue

        if name == "input":
            replacement, end = _process_input(
                text,
                match.start(),
                source_path=source_path,
                env=env,
                options=options,
                stack=stack,
            )
            append_tex_replacement(output, replacement, following=text[end:])
            cursor = end
            continue

        if name == "includegraphics":
            replacement, end = _rewrite_single_path_command(
                text,
                match.start(),
                command_name="includegraphics",
                env=env,
                source=str(source_path),
                allow_optional=True,
                conditionals=options.conditionals,
            )
            append_tex_replacement(output, replacement, following=text[end:])
            cursor = end
            continue

        if name in SUPPORT_COMMANDS:
            replacement, end = _rewrite_comma_path_command(
                text,
                match.start(),
                command_name=name,
                env=env,
                source=str(source_path),
                allow_optional=name in {"documentclass", "usepackage"},
                conditionals=options.conditionals,
            )
            append_tex_replacement(output, replacement, following=text[end:])
            cursor = end
            continue

        macro = env.get(name)
        if macro is not None and _should_expand_call(macro, options, env):
            expanded, end = _expand_macro_call(
                text,
                macro,
                match.end(),
                env=env,
                source=str(source_path),
                conditionals=options.conditionals,
            )
            if expanded is not None:
                append_tex_replacement(
                    output,
                    _process_text(
                        expanded,
                        source_path=source_path,
                        env=env,
                        options=options,
                        stack=stack,
                    ),
                    following=text[end:],
                )
                cursor = end
                continue

        output.append(command)
        cursor = match.end()

    return "".join(output)


def _simplify_definition(
    definition: MacroDefinition, options: ProcessOptions, source_path: Path,
) -> MacroDefinition:
    if options.conditionals is None:
        return definition
    return replace(
        definition,
        content=options.conditionals.simplify(definition.content, source=str(source_path)),
    )


def _definition_text(text: str, start: int, definition: MacroDefinition, original_content: str) -> str:
    # The final balanced group is the body, whose original span may have changed.
    body_start = definition.end - len(original_content) - 1
    return text[start:body_start] + definition.content + "}"


def _process_input(
    text: str,
    start: int,
    *,
    source_path: Path,
    env: dict[str, MacroDefinition],
    options: ProcessOptions,
    stack: tuple[Path, ...],
) -> tuple[str, int]:
    argument = read_required_argument(text, start=start + len(r"\input"), source=str(source_path))
    content = _simplify_fragment(argument.content, options.conditionals, source=str(source_path))
    path_text = expand_path_text(content.strip(), env)
    input_path = resolve_input_path(
        path_text,
        current_dir=source_path.parent,
        search_paths=options.search_paths,
    )
    if input_path is None:
        if options.allow_missing_inputs:
            return rf"\input{{{path_text}}}", argument.end
        raise FlattenError(f"Could not resolve \\input{{{path_text}}} from {source_path}")
    return _process_file(input_path, env=env, options=options, stack=stack), argument.end


def _process_if_file_exists(
    text: str,
    start: int,
    *,
    source_path: Path,
    env: dict[str, MacroDefinition],
    options: ProcessOptions,
    stack: tuple[Path, ...],
) -> tuple[str, int]:
    file_arg = read_required_argument(text, start=start + len(r"\IfFileExists"), source=str(source_path))
    then_arg = read_required_argument(text, start=file_arg.end, source=str(source_path))
    else_arg = read_required_argument(text, start=then_arg.end, source=str(source_path))
    content = _simplify_fragment(file_arg.content, options.conditionals, source=str(source_path))
    path_text = expand_path_text(content.strip(), env)
    target = Path(path_text).expanduser()
    if not target.is_absolute():
        target = source_path.parent / target
    branch = then_arg.content if target.exists() else else_arg.content
    return (
        _process_text(
            branch,
            source_path=source_path,
            env=env,
            options=options,
            stack=stack,
        ),
        else_arg.end,
    )


def _rewrite_single_path_command(
    text: str,
    start: int,
    *,
    command_name: str,
    env: dict[str, MacroDefinition],
    source: str,
    allow_optional: bool,
    conditionals: ConditionalSimplifier | None = None,
) -> tuple[str, int]:
    cursor = start + len("\\" + command_name)
    options_text, cursor = _read_optional_text(text, cursor, source=source) if allow_optional else ("", cursor)
    argument = read_required_argument(text, start=cursor, source=source)
    content = _simplify_fragment(argument.content, conditionals, source=source)
    options_text = _simplify_fragment(options_text, conditionals, source=source)
    path_text = expand_path_text(content.strip(), env)
    return f"\\{command_name}{options_text}" + "{" + path_text + "}", argument.end


def _rewrite_comma_path_command(
    text: str,
    start: int,
    *,
    command_name: str,
    env: dict[str, MacroDefinition],
    source: str,
    allow_optional: bool,
    conditionals: ConditionalSimplifier | None = None,
) -> tuple[str, int]:
    cursor = start + len("\\" + command_name)
    options_text, cursor = _read_optional_text(text, cursor, source=source) if allow_optional else ("", cursor)
    argument = read_required_argument(text, start=cursor, source=source)
    content = _simplify_fragment(argument.content, conditionals, source=source)
    options_text = _simplify_fragment(options_text, conditionals, source=source)
    parts = [
        expand_path_text(part.strip(), env)
        for part in content.split(",")
        if part.strip()
    ]
    return f"\\{command_name}{options_text}" + "{" + ",".join(parts) + "}", argument.end


def _simplify_fragment(text: str, conditionals: ConditionalSimplifier | None, *, source: str) -> str:
    return text if conditionals is None else conditionals.simplify(text, source=source)


def _parse_def(text: str, start: int, *, source: str) -> MacroDefinition | None:
    match = re.match(r"\\def\s*\\([A-Za-z@]+)", text[start:])
    if match is None:
        return None
    name = match.group(1)
    cursor = start + match.end()
    cursor = _skip_whitespace(text, cursor)
    if cursor >= len(text) or text[cursor] != "{":
        return None
    content = read_balanced(text, start=cursor, left="{", source=source)
    return MacroDefinition(name=name, nargs=0, content=content.content, start=start, end=content.end, kind="def")


def _parse_newcommand(text: str, start: int, *, source: str) -> MacroDefinition:
    match = re.match(r"\\(?:re)?newcommand\*?", text[start:])
    if match is None:
        raise LatexParseError("Expected newcommand", source=source, position=start, text=text)
    cursor = _skip_whitespace(text, start + match.end())
    if cursor < len(text) and text[cursor] == "{":
        name_arg = read_required_argument(text, start=cursor, source=source)
        name = _normalize_name(name_arg.content)
        cursor = name_arg.end
    elif cursor < len(text) and text[cursor] == "\\":
        name_match = re.match(r"\\([A-Za-z@]+)", text[cursor:])
        if name_match is None:
            raise LatexParseError("Expected macro name", source=source, position=cursor, text=text)
        name = name_match.group(1)
        cursor += name_match.end()
    else:
        raise LatexParseError("Expected macro name", source=source, position=cursor, text=text)

    nargs, optional_default, cursor = read_macro_parameters(text, start=cursor, source=source)
    content = read_required_argument(text, start=cursor, source=source)
    return MacroDefinition(
        name=name, nargs=nargs, content=content.content, start=start,
        end=content.end, kind="newcommand", optional_default=optional_default,
    )


def _expand_macro_call(
    text: str,
    macro: MacroDefinition,
    start: int,
    *,
    env: dict[str, MacroDefinition],
    source: str,
    conditionals: ConditionalSimplifier | None = None,
) -> tuple[str | None, int]:
    try:
        arguments, cursor = read_macro_arguments(
            text, start=start, nargs=macro.nargs,
            optional_default=macro.optional_default, source=source,
        )
    except LatexParseError:
        return None, start
    expanded_args = [
        expand_path_text(_simplify_fragment(argument, conditionals, source=source), env)
        for argument in arguments
    ]
    replacement = substitute_arguments(macro.content, expanded_args)
    replacement = _simplify_fragment(replacement, conditionals, source=source)
    replacement = expand_path_text(replacement, env)
    return protect_trailing_control_word(replacement), cursor


def _expand_zero_arg_macros(
    text: str,
    env: dict[str, MacroDefinition],
    *,
    stack: tuple[str, ...],
) -> str:
    output: list[str] = []
    cursor = 0
    for match in re.finditer(r"\\([A-Za-z@]+)(?![A-Za-z@])", text):
        name = match.group(1)
        macro = env.get(name)
        if macro is None or macro.nargs != 0:
            continue
        if name in stack:
            chain = " -> ".join((*stack, name))
            raise ProcessError(f"Detected recursive macro definition: {chain}")
        output.append(text[cursor : match.start()])
        output.append(_expand_zero_arg_macros(macro.content, env, stack=(*stack, name)))
        cursor = match.end()
    if not output:
        return text
    output.append(text[cursor:])
    return "".join(output)


def _should_expand_call(
    macro: MacroDefinition,
    options: ProcessOptions,
    env: dict[str, MacroDefinition],
) -> bool:
    return macro.name in options.explicit_macros or _is_path_helper(macro, env)


def _should_remove_definition(
    macro: MacroDefinition,
    options: ProcessOptions,
    env: dict[str, MacroDefinition],
) -> bool:
    if _is_path_helper(macro, env):
        return True
    return macro.name in options.explicit_macros and macro.nargs > 0


def _is_path_helper(
    macro: MacroDefinition,
    env: dict[str, MacroDefinition],
    *,
    stack: tuple[str, ...] = (),
) -> bool:
    if any(token in macro.content for token in PATH_COMMAND_TOKENS):
        return True
    if macro.name in stack:
        return False
    for match in re.finditer(r"\\([A-Za-z@]+)(?![A-Za-z@])", macro.content):
        dependency = env.get(match.group(1))
        if dependency is not None and _is_path_helper(dependency, env, stack=(*stack, macro.name)):
            return True
    return False


def _read_optional_text(text: str, start: int, *, source: str) -> tuple[str, int]:
    cursor = _skip_whitespace(text, start)
    if cursor < len(text) and text[cursor] == "[":
        optional = read_balanced(text, start=cursor, left="[", source=source)
        return text[cursor : optional.end], optional.end
    return "", cursor


def _normalize_search_paths(search_paths: tuple[str | Path, ...], *, base_dir: Path) -> tuple[Path, ...]:
    normalized: list[Path] = []
    for path in search_paths:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        normalized.append(candidate.resolve())
    return tuple(normalized)


def _normalize_name(name: str) -> str:
    return name.strip().removeprefix("\\")


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index
