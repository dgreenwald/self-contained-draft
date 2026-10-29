"""LaTeX input flattening and expl3 token-list file-read inlining."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .latex import (
    append_tex_replacement,
    iter_control_sequences,
    LatexParseError,
    mask_comments,
    read_balanced,
    read_control_sequence_argument,
    read_required_argument,
    strip_comments as strip_tex_comments,
)
from .macros import parse_macro_definitions


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
FILE_GET_PATTERN = re.compile(r"\\file_get:nnN(?![A-Za-z@_:])")
FILE_COMMAND_PATTERN = re.compile(r"\\(?:input\b|file_get:nnN(?![A-Za-z@_:]))")


@dataclass(frozen=True)
class FileGetCommand:
    """A file read whose contents are assigned to an expl3 token list."""

    start: int
    end: int
    path_text: str
    setup: str
    variable: str


def parse_file_get_command(
    text: str, start: int, *, source: str | None = None,
) -> FileGetCommand:
    """Read the two braced arguments and control sequence of file_get:nnN."""

    match = FILE_GET_PATTERN.match(text, start)
    if match is None:
        raise LatexParseError("Expected \\file_get:nnN", source=source,
                              position=start, text=text)
    masked = mask_comments(text) if "%" in text else text
    filename = read_required_argument(masked, start=match.end(), source=source)
    setup = read_required_argument(masked, start=filename.end, source=source)
    cursor = _skip_whitespace(masked, setup.end)
    if masked[cursor:cursor + 1] == "{":
        operand = read_required_argument(masked, start=cursor, source=source)
        variable = read_control_sequence_argument(operand.content, source=source, expl3=True)
        if operand.content[variable.end:].strip():
            raise LatexParseError("Expected a single token-list variable", source=source,
                                  position=cursor, text=text)
        end = operand.end
    else:
        variable = read_control_sequence_argument(masked, start=cursor, source=source, expl3=True)
        end = variable.end
    return FileGetCommand(
        start, end,
        strip_tex_comments(text[filename.start + 1:filename.end - 1]).strip(),
        strip_tex_comments(text[setup.start + 1:setup.end - 1]),
        "\\" + variable.name,
    )


def inline_file_get(
    command: FileGetCommand,
    *,
    source_path: Path,
    search_paths: tuple[Path, ...] = (),
    strip_comments: bool = True,
    allow_missing_inputs: bool = False,
) -> str:
    """Replace an empty-setup file read with a local token-list assignment.

    File contents are stored, not executed: do not flatten inputs or apply
    macro definitions encountered inside the loaded token list.
    """

    if command.setup.strip():
        raise FlattenError(f"Nonempty \\file_get:nnN setup is unsupported in {source_path}")
    input_path = resolve_input_path(
        command.path_text, current_dir=source_path.parent, search_paths=search_paths,
    )
    if input_path is None:
        if allow_missing_inputs:
            return rf"\file_get:nnN{{{command.path_text}}}{{}}{{{command.variable}}}"
        raise FlattenError(
            f"Could not resolve \\file_get:nnN{{{command.path_text}}} from {source_path}"
        )
    try:
        content = input_path.read_text()
    except OSError as exc:
        raise FlattenError(f"Could not read input file {input_path}: {exc}") from exc
    # TeX adds an endline to the last physical line, even without a final LF.
    # This also prevents an EOF comment from swallowing the enclosing brace.
    if content and not content.endswith("\n"):
        content += "\n"
    if strip_comments:
        content = strip_tex_comments(content)
    wrapped = "{" + mask_comments(content) + "}"
    try:
        argument = read_balanced(wrapped, source=str(input_path))
        if argument.end != len(wrapped):
            raise LatexParseError("Unbalanced file contents", source=str(input_path))
    except LatexParseError as exc:
        raise FlattenError(f"Cannot inline unbalanced file contents from {input_path}") from exc
    return rf"\tl_set:Nn {command.variable}" + "{" + content + "}"


def flatten_file(
    path: str | Path,
    *,
    search_paths: tuple[str | Path, ...] = (),
    strip_comments: bool = True,
    allow_missing_inputs: bool = False,
) -> str:
    """Flatten input files and inline empty-setup ``\\file_get:nnN`` reads."""

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
    """Flatten file reads in text using ``source_path`` as context."""

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

    definition_spans = tuple(
        (definition.start, definition.end)
        for definition in parse_macro_definitions(text, source=str(source_path))
    )
    output: list[str] = []
    cursor = 0
    for token in iter_control_sequences(text):
        if token.start < cursor:
            continue
        match = FILE_COMMAND_PATTERN.match(text, token.start)
        if match is None:
            continue
        if _inside_spans(match.start(), definition_spans):
            continue
        if FILE_GET_PATTERN.match(text, match.start()) is not None:
            command = parse_file_get_command(text, match.start(), source=str(source_path))
            output.append(text[cursor:command.start])
            append_tex_replacement(
                output,
                inline_file_get(
                    command, source_path=source_path, search_paths=options.search_paths,
                    strip_comments=options.strip_comments,
                    allow_missing_inputs=options.allow_missing_inputs,
                ),
                following=text[command.end:],
            )
            cursor = command.end
            continue
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
            append_tex_replacement(
                output, _flatten_file(input_path, options=options, stack=stack),
                following=text[command.end:],
            )

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


def _inside_spans(position: int, spans: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= position < end for start, end in spans)
