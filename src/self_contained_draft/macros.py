"""Conservative parsing and expansion of simple LaTeX macros."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .latex import (
    LatexParseError,
    protect_trailing_control_word,
    read_balanced,
    read_required_argument,
    substitute_arguments,
)


class MacroExpansionError(RuntimeError):
    """Raised when configured macro expansion fails."""


@dataclass(frozen=True)
class MacroDefinition:
    """A simple parsed LaTeX macro definition."""

    name: str
    nargs: int
    content: str
    start: int
    end: int
    kind: str


NEWCOMMAND_PATTERN = re.compile(r"\\(?:re)?newcommand\*?(?![A-Za-z@])")
DEF_PATTERN = re.compile(r"\\def\s*\\([A-Za-z@]+)")
MACRO_NAME_PATTERN = re.compile(r"[A-Za-z@]+")


def parse_macros(text: str, *, source: str | None = None) -> dict[str, MacroDefinition]:
    """Parse simple ``\\def`` and ``\\newcommand`` definitions from text."""

    definitions: dict[str, MacroDefinition] = {}
    for definition in parse_macro_definitions(text, source=source):
        definitions[definition.name] = definition
    return definitions


def parse_macro_definitions(text: str, *, source: str | None = None) -> tuple[MacroDefinition, ...]:
    """Parse all simple macro definitions from text in source order."""

    return tuple(
        sorted(
            (*_parse_defs(text, source=source), *_parse_newcommands(text, source=source)),
            key=lambda item: item.start,
        )
    )


def expand_configured_macros(
    text: str,
    macros: dict[str, MacroDefinition],
    macro_names: list[str] | tuple[str, ...] | set[str],
    *,
    source: str | None = None,
    max_passes: int = 20,
) -> str:
    """Expand only configured macro names in text.

    Macro definitions themselves are left untouched. Replacement content is
    resolved through zero-argument macro dependencies so configured path macros
    can depend on other path macros without requiring broad document expansion.
    """

    names = frozenset(_normalize_macro_name(name) for name in macro_names)
    if not names:
        return text

    expanded = text
    for _ in range(max_passes):
        current_definitions = parse_macro_definitions(expanded, source=source)
        definition_spans = tuple((macro.start, macro.end) for macro in current_definitions)
        next_text, replacements = _expand_one_pass(
            expanded,
            names,
            current_definitions,
            definition_spans=definition_spans,
            source=source,
        )
        expanded = next_text
        if replacements == 0:
            return expanded

    raise MacroExpansionError(
        f"Macro expansion did not converge after {max_passes} passes"
        + (f" in {source}" if source is not None else "")
    )


def remove_macro_definitions(
    text: str,
    macros: dict[str, MacroDefinition] | tuple[MacroDefinition, ...],
    macro_names: list[str] | tuple[str, ...] | set[str],
    *,
    min_args: int = 0,
) -> str:
    """Remove definitions for configured macros from text."""

    names = {_normalize_macro_name(name) for name in macro_names}
    definitions = macros.values() if isinstance(macros, dict) else macros
    spans = [
        (macro.start, macro.end)
        for macro in definitions
        if macro.name in names and macro.nargs >= min_args
    ]
    if not spans:
        return text

    output: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        output.append(text[cursor:start])
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _parse_defs(text: str, *, source: str | None) -> list[MacroDefinition]:
    definitions: list[MacroDefinition] = []
    for match in DEF_PATTERN.finditer(text):
        content_start = _skip_whitespace(text, match.end())
        if content_start >= len(text) or text[content_start] != "{":
            continue
        content = read_balanced(text, start=content_start, left="{", source=source)
        definitions.append(
            MacroDefinition(
                name=match.group(1),
                nargs=0,
                content=content.content,
                start=match.start(),
                end=content.end,
                kind="def",
            )
        )
    return definitions


def _parse_newcommands(text: str, *, source: str | None) -> list[MacroDefinition]:
    definitions: list[MacroDefinition] = []
    for match in NEWCOMMAND_PATTERN.finditer(text):
        name, cursor = _read_newcommand_name(text, match.end(), source=source)
        nargs, cursor = _read_optional_nargs(text, cursor, source=source)
        content_start = _skip_whitespace(text, cursor)
        content = read_balanced(text, start=content_start, left="{", source=source)
        definitions.append(
            MacroDefinition(
                name=name,
                nargs=nargs,
                content=content.content,
                start=match.start(),
                end=content.end,
                kind="newcommand",
            )
        )
    return definitions


def _read_newcommand_name(
    text: str,
    start: int,
    *,
    source: str | None,
) -> tuple[str, int]:
    cursor = _skip_whitespace(text, start)
    if cursor >= len(text):
        raise LatexParseError(
            "Missing macro name in \\newcommand",
            source=source,
            position=start,
            text=text,
        )

    if text[cursor] == "{":
        name_arg = read_required_argument(text, start=cursor, source=source)
        name = name_arg.content.strip()
        if not name.startswith("\\"):
            raise LatexParseError(
                "Expected macro name beginning with backslash",
                source=source,
                position=cursor,
                text=text,
            )
        return _normalize_macro_name(name), name_arg.end

    if text[cursor] != "\\":
        raise LatexParseError(
            "Expected macro name beginning with backslash",
            source=source,
            position=cursor,
            text=text,
        )

    name_match = MACRO_NAME_PATTERN.match(text, cursor + 1)
    if name_match is None:
        raise LatexParseError(
            "Expected alphabetic macro name",
            source=source,
            position=cursor,
            text=text,
        )
    return name_match.group(0), name_match.end()


def _read_optional_nargs(
    text: str,
    start: int,
    *,
    source: str | None,
) -> tuple[int, int]:
    cursor = _skip_whitespace(text, start)
    if cursor >= len(text) or text[cursor] != "[":
        return 0, cursor

    nargs_arg = read_balanced(text, start=cursor, left="[", source=source)
    raw_nargs = nargs_arg.content.strip()
    if raw_nargs == "":
        return 0, nargs_arg.end
    try:
        nargs = int(raw_nargs)
    except ValueError as exc:
        raise LatexParseError(
            "Expected integer argument count in \\newcommand",
            source=source,
            position=cursor,
            text=text,
        ) from exc
    if nargs < 0 or nargs > 9:
        raise LatexParseError(
            "Only macros with 0 to 9 arguments are supported",
            source=source,
            position=cursor,
            text=text,
        )
    return nargs, nargs_arg.end


def _expand_one_pass(
    text: str,
    selected_names: frozenset[str],
    definitions: tuple[MacroDefinition, ...],
    *,
    definition_spans: tuple[tuple[int, int], ...],
    source: str | None,
) -> tuple[str, int]:
    output: list[str] = []
    cursor = 0
    replacements = 0

    for match in re.finditer(r"\\([A-Za-z@]+)(?![A-Za-z@])", text):
        if match.start() < cursor:
            continue
        name = match.group(1)
        if name not in selected_names or _inside_spans(match.start(), definition_spans):
            continue

        macro = _active_definition(name, definitions, match.start())
        if macro is None:
            continue
        try:
            arguments, end = _read_macro_arguments(
                text,
                macro,
                start=match.end(),
                source=source,
            )
        except LatexParseError:
            continue
        output.append(text[cursor : match.start()])
        active_macros = _active_definitions_by_name(definitions, match.start())
        replacement = substitute_arguments(
            _resolve_zero_arg_dependencies(macro.content, active_macros, stack=(macro.name,)),
            arguments,
        )
        output.append(protect_trailing_control_word(replacement))
        cursor = end
        replacements += 1

    if replacements == 0:
        return text, 0
    output.append(text[cursor:])
    return "".join(output), replacements


def _active_definition(
    name: str,
    definitions: tuple[MacroDefinition, ...],
    position: int,
) -> MacroDefinition | None:
    active: MacroDefinition | None = None
    for definition in definitions:
        if definition.start >= position:
            break
        if definition.name == name:
            active = definition
    return active


def _active_definitions_by_name(
    definitions: tuple[MacroDefinition, ...],
    position: int,
) -> dict[str, MacroDefinition]:
    active: dict[str, MacroDefinition] = {}
    for definition in definitions:
        if definition.start >= position:
            break
        active[definition.name] = definition
    return active


def _read_macro_arguments(
    text: str,
    macro: MacroDefinition,
    *,
    start: int,
    source: str | None,
) -> tuple[list[str], int]:
    if macro.nargs == 0:
        return [], start

    arguments: list[str] = []
    cursor = start
    for _ in range(macro.nargs):
        argument = read_required_argument(text, start=cursor, source=source)
        arguments.append(argument.content)
        cursor = argument.end
    return arguments, cursor


def _resolve_zero_arg_dependencies(
    content: str,
    macros: dict[str, MacroDefinition],
    *,
    stack: tuple[str, ...],
) -> str:
    output: list[str] = []
    cursor = 0
    for match in re.finditer(r"\\([A-Za-z@]+)(?![A-Za-z@])", content):
        name = match.group(1)
        dependency = macros.get(name)
        if dependency is None or dependency.nargs != 0:
            continue
        if name in stack:
            chain = " -> ".join((*stack, name))
            raise MacroExpansionError(f"Detected recursive macro definition: {chain}")
        output.append(content[cursor : match.start()])
        output.append(
            _resolve_zero_arg_dependencies(
                dependency.content,
                macros,
                stack=(*stack, name),
            )
        )
        cursor = match.end()

    if not output:
        return content
    output.append(content[cursor:])
    return "".join(output)


def _normalize_macro_name(name: str) -> str:
    return name.strip().removeprefix("\\")


def _inside_spans(position: int, spans: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= position < end for start, end in spans)


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index
