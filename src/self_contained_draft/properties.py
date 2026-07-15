"""Inlining for LaTeX expl3 property lookup helper macros."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .latex import LatexParseError, protect_trailing_control_word, read_required_argument


class PropertyInlineError(RuntimeError):
    """Raised when configured property lookups cannot be inlined."""


@dataclass(frozen=True)
class PropertyInlineResult:
    text: str
    macros: tuple[str, ...]
    replacements: int
    removed_assignments: int


@dataclass(frozen=True)
class _Assignment:
    start: int
    end: int
    prop: str
    key: str
    value: str


@dataclass(frozen=True)
class _Modification:
    start: int
    end: int
    replacement: str


_PROPERTY_NAME = r"\\[A-Za-z_:]+"
_CS_NEW_PATTERN = re.compile(r"\\cs_new:Npn\s*\\(?P<macro>[A-Za-z@]+)\s*#1")
_PROP_ITEM_PATTERN = re.compile(
    rf"^\s*\\prop_item:Nn\s+(?P<prop>{_PROPERTY_NAME})\s*\{{\s*#1\s*\}}\s*$"
)
_PROP_GPUT_PATTERN = re.compile(rf"\\prop_gput:Nnn\s+(?P<prop>{_PROPERTY_NAME})")


def inline_property_macros(
    text: str,
    macro_names: tuple[str, ...],
) -> PropertyInlineResult:
    """Inline configured one-argument property lookup macros.

    The supported lookup shape is the common expl3 wrapper:
    ``\\cs_new:Npn \\name #1 { \\prop_item:Nn \\g_some_prop {#1} }``.
    """

    normalized_names = tuple(_normalize_macro_name(name) for name in macro_names)
    if not normalized_names:
        return PropertyInlineResult(text=text, macros=(), replacements=0, removed_assignments=0)

    macro_properties = _find_lookup_properties(text, set(normalized_names))
    missing_macros = [name for name in normalized_names if name not in macro_properties]
    if missing_macros:
        formatted = ", ".join(f"\\{name}" for name in missing_macros)
        raise PropertyInlineError(f"Could not find property lookup definition(s): {formatted}")

    assignments = _find_assignments(text)
    values_by_prop: dict[str, dict[str, str]] = {}
    for assignment in assignments:
        values_by_prop.setdefault(assignment.prop, {})[assignment.key] = assignment.value

    modifications: list[_Modification] = []
    replacement_count = 0
    for macro, prop in macro_properties.items():
        prop_values = values_by_prop.get(prop, {})
        macro_modifications, count = _find_call_replacements(text, macro, prop, prop_values)
        modifications.extend(macro_modifications)
        replacement_count += count

    target_props = set(macro_properties.values())
    assignment_removals = [
        _Modification(*_expand_to_line(text, assignment.start, assignment.end), replacement="")
        for assignment in assignments
        if assignment.prop in target_props
    ]
    modifications.extend(assignment_removals)
    modifications.extend(_find_property_initializer_removals(text, target_props))

    return PropertyInlineResult(
        text=_apply_modifications(text, modifications),
        macros=normalized_names,
        replacements=replacement_count,
        removed_assignments=len(assignment_removals),
    )


def _normalize_macro_name(name: str) -> str:
    stripped = str(name).strip()
    if stripped.startswith("\\"):
        stripped = stripped[1:]
    if not stripped:
        raise PropertyInlineError("Property lookup macro names cannot be empty")
    if not re.fullmatch(r"[A-Za-z@]+", stripped):
        raise PropertyInlineError(f"Invalid property lookup macro name: {name!r}")
    return stripped


def _find_lookup_properties(text: str, macro_names: set[str]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for match in _CS_NEW_PATTERN.finditer(text):
        macro = match.group("macro")
        if macro not in macro_names or macro in properties:
            continue
        try:
            body = read_required_argument(text, start=match.end()).content
        except LatexParseError:
            continue
        body_match = _PROP_ITEM_PATTERN.match(body)
        if body_match is not None:
            properties[macro] = body_match.group("prop")
    return properties


def _find_assignments(text: str) -> list[_Assignment]:
    assignments: list[_Assignment] = []
    cursor = 0
    while True:
        match = _PROP_GPUT_PATTERN.search(text, cursor)
        if match is None:
            return assignments
        try:
            key = read_required_argument(text, start=match.end())
            value = read_required_argument(text, start=key.end)
        except LatexParseError:
            cursor = match.end()
            continue
        assignments.append(
            _Assignment(
                start=match.start(),
                end=value.end,
                prop=match.group("prop"),
                key=key.content,
                value=value.content,
            )
        )
        cursor = value.end


def _find_call_replacements(
    text: str,
    macro: str,
    prop: str,
    values: dict[str, str],
) -> tuple[list[_Modification], int]:
    pattern = re.compile(rf"\\{re.escape(macro)}(?![A-Za-z@])")
    modifications: list[_Modification] = []
    cursor = 0
    count = 0
    while True:
        match = pattern.search(text, cursor)
        if match is None:
            return modifications, count
        if _is_expl3_definition_operand(text, match.start()):
            cursor = match.end()
            continue
        try:
            argument = read_required_argument(text, start=match.end())
        except LatexParseError:
            cursor = match.end()
            continue
        key = argument.content.strip()
        if key not in values:
            raise PropertyInlineError(
                f"Could not inline \\{macro}{{{key}}}: key not found in {prop}"
            )
        modifications.append(
            _Modification(match.start(), argument.end, protect_trailing_control_word(values[key]))
        )
        count += 1
        cursor = argument.end


def _is_expl3_definition_operand(text: str, start: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start]
    return re.search(r"\\(?:cs_if_exist:NF|cs_new:Npn)\s*$", prefix) is not None


def _find_property_initializer_removals(
    text: str,
    target_props: set[str],
) -> list[_Modification]:
    removals: list[_Modification] = []
    for prop in sorted(target_props, key=len, reverse=True):
        escaped = re.escape(prop)
        patterns = [
            re.compile(rf"\\prop_new:N\s+{escaped}"),
            re.compile(rf"\\prop_if_exist:NF\s+{escaped}\s*\{{\s*\\prop_new:N\s+{escaped}\s*\}}"),
        ]
        for pattern in patterns:
            for match in pattern.finditer(text):
                removals.append(_Modification(*_expand_to_line(text, match.start(), match.end()), replacement=""))
    return removals


def _expand_to_line(text: str, start: int, end: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, start) + 1
    next_newline = text.find("\n", end)
    line_end = len(text) if next_newline == -1 else next_newline + 1
    if text[line_start:start].strip() == "" and text[end:line_end].strip() == "":
        return line_start, line_end
    return start, end


def _apply_modifications(text: str, modifications: list[_Modification]) -> str:
    if not modifications:
        return text
    ordered = sorted(modifications, key=lambda item: (item.start, item.end))
    pieces: list[str] = []
    cursor = 0
    for modification in ordered:
        if modification.start < cursor:
            if modification.end <= cursor:
                continue
            raise PropertyInlineError("Overlapping property inlining edits")
        pieces.append(text[cursor : modification.start])
        pieces.append(modification.replacement)
        cursor = modification.end
    pieces.append(text[cursor:])
    return "".join(pieces)
