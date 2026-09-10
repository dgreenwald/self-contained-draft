"""Small LaTeX parsing helpers used by the draft flattener.

These helpers intentionally cover the lightweight parsing needed for file
resolution and cleanup. They are not a complete TeX parser.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Iterable
from typing import NamedTuple


class LatexParseError(ValueError):
    """Raised when lightweight LaTeX parsing fails."""

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        position: int | None = None,
        text: str | None = None,
    ) -> None:
        details = message
        if source is not None:
            details += f" in {source}"
        if position is not None:
            details += f" at offset {position}"
        if text is not None and position is not None:
            snippet = _snippet(text, position)
            if snippet:
                details += f": {snippet!r}"
        super().__init__(details)
        self.source = source
        self.position = position


class BmaMatch(NamedTuple):
    before: str
    middle: str
    after: str
    match: re.Match[str] | None
    matched: bool


@dataclass(frozen=True)
class DelimitedMatch:
    """Text captured from a delimited LaTeX argument or environment body."""

    content: str
    delimiter: str
    after: str
    start: int
    end: int


@dataclass(frozen=True)
class ControlSequence:
    name: str
    start: int
    end: int


_CONTROL_SEQUENCE_PATTERN = re.compile(r"[A-Za-z@]+|[\s\S]")


def iter_control_sequences(text: str, *, start: int = 0) -> Iterable[ControlSequence]:
    """Scan control words/symbols, ignoring comments and escaped backslashes."""

    cursor = start
    while cursor < len(text):
        if text[cursor] == "%":
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
        elif text[cursor] == "\\":
            match = _CONTROL_SEQUENCE_PATTERN.match(text, cursor + 1)
            if match is None:
                return
            end = match.end()
            yield ControlSequence(match.group(), cursor, end)
            cursor = end
        else:
            cursor += 1


def control_word_suffix(text: str, start: int) -> tuple[str, int]:
    """Consume ignored space after a control word, retaining comments/blank lines.

    One physical endline acts as ignored delimiter space. A subsequent blank
    line must remain, since it produces a paragraph token. Comment endlines do
    not count toward this limit.
    """

    cursor = start
    saw_endline = False
    comments: list[str] = []
    while cursor < len(text):
        char = text[cursor]
        if char in " \t":
            cursor += 1
        elif char == "\n" and not saw_endline:
            saw_endline = True
            cursor += 1
        elif char == "%":
            newline = text.find("\n", cursor)
            end = len(text) if newline < 0 else newline + 1
            comments.append(text[cursor:end])
            cursor = end
        else:
            break
    # Keep both endlines when the next one represents a blank line; otherwise
    # literalizing the fragment would turn a paragraph into an ordinary space.
    if saw_endline and cursor < len(text) and text[cursor] == "\n":
        comments.append("\n")
    return "".join(comments), cursor


def skip_tex_tokens(text: str, start: int, count: int) -> int:
    """Skip literal token operands (no expansion), such as those of ``\\ifx``."""

    cursor = start
    for _ in range(count):
        while cursor < len(text):
            if text[cursor].isspace():
                cursor += 1
            elif text[cursor] == "%":
                newline = text.find("\n", cursor)
                cursor = len(text) if newline < 0 else newline + 1
            else:
                break
        if cursor == len(text):
            return cursor
        if text[cursor] == "\\":
            match = _CONTROL_SEQUENCE_PATTERN.match(text, cursor + 1)
            cursor = match.end() if match is not None else len(text)
        else:
            cursor += 1
    return cursor


def join_tex_fragments(left: str, right: str) -> str:
    """Join fragments without merging an exposed control word with new tokens."""

    return protect_trailing_control_word(left, following=right) + right


def append_tex_replacement(output: list[str], replacement: str, *, following: str) -> None:
    """Preserve token boundaries on both sides of an inserted replacement."""

    combined = join_tex_fragments("".join(output), replacement)
    # Input files retain their source whitespace semantics at the right edge.
    # Only letters require a new separator there; macro expansion handles its
    # own trailing whitespace protection.
    if re.match(r"[A-Za-z@]", following):
        combined = protect_trailing_control_word(combined, following=following)
    output[:] = [combined]


BRACKET_PAIRS = {
    "(": ")",
    "[": "]",
    "{": "}",
}


def match_to_bma(match: re.Match[str] | None, text: str) -> BmaMatch:
    """Split text into before/match/after components for a regex match."""

    if match is None:
        return BmaMatch(text, "", "", None, False)
    return BmaMatch(
        text[: match.start()],
        text[match.start() : match.end()],
        text[match.end() :],
        match,
        True,
    )


def bma_search(
    pattern: str | re.Pattern[str],
    text: str,
    *args: object,
    **kwargs: object,
) -> BmaMatch:
    """Search text and return the result split into before/match/after pieces."""

    match = re.search(pattern, text, *args, **kwargs)
    return match_to_bma(match, text)


def strip_comments(text: str) -> str:
    """Remove LaTeX comments while preserving escaped percent signs.

    A percent sign starts a comment only when it is preceded by an even number
    of backslashes. The comment consumes the rest of the physical line,
    including the newline, matching TeX's line-continuation behavior.
    """

    output: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "%" and not _is_escaped(text, index):
            newline = text.find("\n", index)
            if newline == -1:
                break
            index = newline + 1
            while index < len(text) and text[index] in " \t":
                index += 1
            if (index < len(text) and re.match(r"[A-Za-z@]", text[index])
                    and _ends_in_control_word("".join(output))):
                # A comment also terminates a control word. Preserve that token
                # boundary when removing its newline and following indentation.
                output.append(" ")
            continue
        output.append(char)
        index += 1
    return "".join(output)


def read_balanced(
    text: str,
    *,
    start: int = 0,
    left: str = "{",
    source: str | None = None,
) -> DelimitedMatch:
    """Read a balanced bracketed segment starting at ``start``.

    Returns the content inside the outer brackets, the closing delimiter, and
    the remaining text after the closing delimiter.
    """

    if left not in BRACKET_PAIRS:
        raise LatexParseError(f"Unsupported opening delimiter {left!r}", source=source)

    right = BRACKET_PAIRS[left]
    if start >= len(text) or text[start] != left:
        raise LatexParseError(
            f"Expected {left!r}",
            source=source,
            position=start,
            text=text,
        )

    depth = 1
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == left and not _is_escaped(text, index):
            depth += 1
        elif char == right and not _is_escaped(text, index):
            depth -= 1
            if depth == 0:
                return DelimitedMatch(
                    content=text[start + 1 : index],
                    delimiter=right,
                    after=text[index + 1 :],
                    start=start,
                    end=index + 1,
                )
        index += 1

    raise LatexParseError(
        f"Unclosed {left!r}",
        source=source,
        position=start,
        text=text,
    )


def read_required_argument(
    text: str,
    *,
    start: int = 0,
    source: str | None = None,
) -> DelimitedMatch:
    """Read the next required ``{...}`` argument after optional whitespace."""

    start = _skip_whitespace(text, start)
    return read_balanced(text, start=start, left="{", source=source)


def read_optional_argument(
    text: str, *, start: int = 0, source: str | None = None,
) -> DelimitedMatch | None:
    """Read an optional argument; braced or escaped closing brackets are literal."""

    start = _skip_whitespace(text, start)
    if text[start:start + 1] != "[":
        return None
    cursor = start + 1
    depth = 0
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "%":
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            if depth == 0:
                raise LatexParseError("Unexpected '}' in optional argument", source=source, position=cursor, text=text)
            depth -= 1
        elif char == "]" and depth == 0:
            return DelimitedMatch(text[start + 1:cursor], "]", text[cursor + 1:], start, cursor + 1)
        cursor += 1
    raise LatexParseError("Unclosed optional argument", source=source, position=start, text=text)


def read_macro_parameters(
    text: str, *, start: int, source: str | None = None,
) -> tuple[int, str | None, int]:
    """Read newcommand's optional argument count and optional first-argument default."""

    count = read_optional_argument(text, start=start, source=source)
    if count is None:
        return 0, None, start
    try:
        nargs = int(count.content.strip() or "0")
    except ValueError as exc:
        raise LatexParseError("Expected integer argument count", source=source, position=count.start, text=text) from exc
    if not 0 <= nargs <= 9:
        raise LatexParseError("Only macros with 0 to 9 arguments are supported", source=source, position=count.start, text=text)
    default = read_optional_argument(text, start=count.end, source=source)
    if default is None:
        return nargs, None, count.end
    if nargs == 0:
        raise LatexParseError("An optional default requires at least one argument", source=source, position=default.start, text=text)
    return nargs, default.content, default.end


def read_macro_arguments(
    text: str, *, start: int, nargs: int, optional_default: str | None = None,
    source: str | None = None,
) -> tuple[list[str], int]:
    """Read a macro call's optional first argument and braced required arguments."""

    arguments: list[str] = []
    cursor = start
    if optional_default is not None:
        optional = read_optional_argument(text, start=cursor, source=source)
        arguments.append(optional_default if optional is None else optional.content)
        if optional is not None:
            cursor = optional.end
    for _ in range(nargs - len(arguments)):
        argument = read_required_argument(text, start=cursor, source=source)
        arguments.append(argument.content)
        cursor = argument.end
    return arguments, cursor


def read_required_arguments(
    text: str,
    count: int,
    *,
    start: int = 0,
    source: str | None = None,
) -> tuple[list[str], str]:
    """Read ``count`` required arguments and return their contents and tail."""

    arguments: list[str] = []
    index = start
    for _ in range(count):
        match = read_required_argument(text, start=index, source=source)
        arguments.append(match.content)
        index = match.end
    return arguments, text[index:]


def expand_to_target(
    text: str,
    *,
    target: str | None = None,
    left_bracket: str = "(",
    target_depth: int | None = 1,
    source: str | None = None,
) -> tuple[str, str, str]:
    """Return text before a target token at the requested bracket depth.

    This preserves the legacy helper's public shape: ``before, middle, after``.
    By default, ``target`` is the matching closing bracket for ``left_bracket``.
    The scan starts inside one already-opened bracket, so the initial depth is
    one.
    """

    if left_bracket not in BRACKET_PAIRS:
        raise LatexParseError(
            f"Unsupported opening delimiter {left_bracket!r}",
            source=source,
        )

    right_bracket = BRACKET_PAIRS[left_bracket]
    if target is None:
        target = right_bracket

    depth = 1
    pieces: list[str] = []
    for index, char in enumerate(text):
        at_target = char == target and (target_depth is None or depth == target_depth)
        if at_target and not _is_escaped(text, index):
            return "".join(pieces), char, text[index + 1 :]

        if char == left_bracket and not _is_escaped(text, index):
            depth += 1
        elif char == right_bracket and not _is_escaped(text, index):
            depth -= 1
        pieces.append(char)

    raise LatexParseError(
        f"Could not find target {target!r}",
        source=source,
        position=len(text),
        text=text,
    )


def substitute_arguments(template: str, arguments: Iterable[str]) -> str:
    """Replace LaTeX command placeholders ``#1``, ``#2``, ... in a template."""

    result = template
    for index, argument in enumerate(arguments, start=1):
        result = result.replace(f"#{index}", argument)
    return result


def protect_trailing_control_word(text: str, *, following: str | None = None) -> str:
    """Preserve following source spaces after literalized macro expansion.

    TeX skips spaces after a control word while tokenizing source. When a macro
    expansion ending in a control word is written back as literal text, appending
    an empty group recreates the token boundary that existed in the original
    macro expansion.
    """

    if following is not None and (not following or re.match(r"[A-Za-z@\s]", following) is None):
        return text
    if _ends_in_control_word(text):
        return text + "{}"
    return text


def _ends_in_control_word(text: str) -> bool:
    match = re.search(r"(\\+)[A-Za-z@]+$", text)
    return match is not None and len(match.group(1)) % 2 == 1


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _is_escaped(text: str, index: int) -> bool:
    slash_count = 0
    probe = index - 1
    while probe >= 0 and text[probe] == "\\":
        slash_count += 1
        probe -= 1
    return slash_count % 2 == 1


def _snippet(text: str, position: int, *, radius: int = 40) -> str:
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    return text[start:end].replace("\n", "\\n")
