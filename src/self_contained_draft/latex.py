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
    of backslashes. Newline characters are preserved.
    """

    output: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "%" and not _is_escaped(text, index):
            newline = text.find("\n", index)
            if newline == -1:
                break
            output.append("\n")
            index = newline + 1
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
