"""Recursive LaTeX ``\\input`` flattening."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .latex import LatexParseError, read_required_argument, strip_comments as strip_tex_comments


class FlattenError(RuntimeError):
    """Raised when a LaTeX input tree cannot be flattened."""


@dataclass(frozen=True)
class FlattenOptions:
    """Options controlling recursive input flattening."""

    search_paths: tuple[Path, ...] = ()
    strip_comments: bool = True
    allow_missing_inputs: bool = False


@dataclass(frozen=True)
class InputCommand:
    """A parsed ``\\input`` command occurrence."""

    start: int
    end: int
    raw: str
    path_text: str


INPUT_PATTERN = re.compile(r"\\input\b")


def flatten_file(
    path: str | Path,
    *,
    search_paths: tuple[str | Path, ...] = (),
    strip_comments: bool = True,
    allow_missing_inputs: bool = False,
) -> str:
    """Flatten a LaTeX root file by recursively inlining ``\\input`` files."""

    root = Path(path).expanduser().resolve()
    options = FlattenOptions(
        search_paths=_normalize_search_paths(search_paths, base_dir=root.parent),
        strip_comments=strip_comments,
        allow_missing_inputs=allow_missing_inputs,
    )
    return _flatten_file(root, options=options, stack=())


def flatten_text(
    text: str,
    *,
    source_path: str | Path,
    search_paths: tuple[str | Path, ...] = (),
    strip_comments: bool = True,
    allow_missing_inputs: bool = False,
) -> str:
    """Flatten ``\\input`` commands in text using ``source_path`` as context."""

    source = Path(source_path).expanduser().resolve()
    options = FlattenOptions(
        search_paths=_normalize_search_paths(search_paths, base_dir=source.parent),
        strip_comments=strip_comments,
        allow_missing_inputs=allow_missing_inputs,
    )
    return _flatten_text(text, source_path=source, options=options, stack=(source,))


def parse_input_command(text: str, start: int, *, source: str | None = None) -> InputCommand:
    """Parse an ``\\input`` command at ``start``."""

    match = INPUT_PATTERN.match(text, start)
    if match is None:
        raise LatexParseError(
            "Expected \\input command",
            source=source,
            position=start,
            text=text,
        )

    argument_start = _skip_whitespace(text, match.end())
    if argument_start >= len(text):
        raise LatexParseError(
            "Missing \\input argument",
            source=source,
            position=match.end(),
            text=text,
        )

    if text[argument_start] == "{":
        argument = read_required_argument(text, start=argument_start, source=source)
        return InputCommand(
            start=start,
            end=argument.end,
            raw=text[start : argument.end],
            path_text=argument.content.strip(),
        )

    argument_end = argument_start
    while argument_end < len(text) and not text[argument_end].isspace():
        argument_end += 1

    if argument_end == argument_start:
        raise LatexParseError(
            "Missing \\input argument",
            source=source,
            position=argument_start,
            text=text,
        )

    return InputCommand(
        start=start,
        end=argument_end,
        raw=text[start:argument_end],
        path_text=text[argument_start:argument_end].strip(),
    )


def resolve_input_path(
    path_text: str,
    *,
    current_dir: Path,
    search_paths: tuple[Path, ...] = (),
) -> Path | None:
    """Resolve a LaTeX input path, trying explicit and ``.tex`` variants."""

    raw_path = Path(path_text).expanduser()
    roots: tuple[Path, ...]
    if raw_path.is_absolute():
        roots = (Path("/"),)
        relative_candidates = (raw_path,)
    else:
        roots = (current_dir, *search_paths)
        relative_candidates = (raw_path,)

    for root in roots:
        for candidate in _with_tex_fallbacks(relative_candidates[0]):
            full_candidate = candidate if candidate.is_absolute() else root / candidate
            if full_candidate.exists() and full_candidate.is_file():
                return full_candidate.resolve()
    return None


def _flatten_file(path: Path, *, options: FlattenOptions, stack: tuple[Path, ...]) -> str:
    resolved = path.resolve()
    if resolved in stack:
        chain = " -> ".join(str(item) for item in (*stack, resolved))
        raise FlattenError(f"Detected recursive \\input cycle: {chain}")
    try:
        text = resolved.read_text()
    except OSError as exc:
        raise FlattenError(f"Could not read input file {resolved}: {exc}") from exc
    return _flatten_text(text, source_path=resolved, options=options, stack=(*stack, resolved))


def _flatten_text(
    text: str,
    *,
    source_path: Path,
    options: FlattenOptions,
    stack: tuple[Path, ...],
) -> str:
    if options.strip_comments:
        text = strip_tex_comments(text)

    output: list[str] = []
    cursor = 0
    for match in INPUT_PATTERN.finditer(text):
        command = parse_input_command(text, match.start(), source=str(source_path))
        output.append(text[cursor : command.start])

        input_path = resolve_input_path(
            command.path_text,
            current_dir=source_path.parent,
            search_paths=options.search_paths,
        )
        if input_path is None:
            if options.allow_missing_inputs:
                output.append(command.raw)
            else:
                raise FlattenError(
                    f"Could not resolve \\input{{{command.path_text}}} from {source_path}"
                )
        else:
            output.append(_flatten_file(input_path, options=options, stack=stack))

        cursor = command.end

    output.append(text[cursor:])
    return "".join(output)


def _normalize_search_paths(
    search_paths: tuple[str | Path, ...],
    *,
    base_dir: Path,
) -> tuple[Path, ...]:
    normalized: list[Path] = []
    for path in search_paths:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        normalized.append(candidate.resolve())
    return tuple(normalized)


def _with_tex_fallbacks(path: Path) -> tuple[Path, ...]:
    if path.suffix:
        return (path,)
    return (path, path.with_suffix(".tex"))


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index
