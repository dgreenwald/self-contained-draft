"""Optional collection of local bibliography, class, and style files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil

from .latex import read_balanced, read_required_argument


class SupportFileError(RuntimeError):
    """Raised when requested support files cannot be copied."""


@dataclass(frozen=True)
class SupportFile:
    """A copied non-figure LaTeX support file."""

    kind: str
    original_path: str
    resolved_path: Path
    output_name: str


@dataclass(frozen=True)
class SupportFileResult:
    """Result of copying support files and rewriting paths."""

    text: str
    files: tuple[SupportFile, ...]


COMMAND_PATTERNS = {
    "documentclass": re.compile(r"\\documentclass\b"),
    "usepackage": re.compile(r"\\usepackage\b"),
    "bibliography": re.compile(r"\\bibliography\b"),
    "bibliographystyle": re.compile(r"\\bibliographystyle\b"),
    "addbibresource": re.compile(r"\\addbibresource\b"),
}


def copy_support_files(
    text: str,
    *,
    source_dir: str | Path,
    output_dir: str | Path,
    search_paths: tuple[str | Path, ...] = (),
    allow_missing: bool = False,
) -> SupportFileResult:
    """Copy local bibliography/class/style files and rewrite path arguments."""

    source_root = Path(source_dir).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    normalized_search_paths = _normalize_search_paths(search_paths, base_dir=source_root)

    replacements: list[tuple[int, int, str]] = []
    copied: dict[Path, SupportFile] = {}
    files: list[SupportFile] = []

    for command in _find_support_commands(text):
        rewritten_parts: list[str] = []
        changed = False
        for item in command.items:
            resolved = resolve_support_path(
                item,
                kind=command.kind,
                current_dir=source_root,
                search_paths=normalized_search_paths,
            )
            if resolved is None:
                if allow_missing:
                    rewritten_parts.append(item)
                    continue
                raise SupportFileError(
                    f"Could not resolve {command.kind} support file {item!r} from {source_root}"
                )

            support_file = copied.get(resolved)
            if support_file is None:
                support_file = SupportFile(
                    kind=command.kind,
                    original_path=item,
                    resolved_path=resolved,
                    output_name=resolved.name,
                )
                copied[resolved] = support_file
                files.append(support_file)
                shutil.copy2(resolved, destination / resolved.name)

            rewritten_parts.append(_latex_reference_for_output(command.kind, support_file.output_name))
            changed = True

        if changed:
            replacements.append((command.arg_start, command.arg_end, ",".join(rewritten_parts)))

    return SupportFileResult(text=_apply_replacements(text, replacements), files=tuple(files))


def resolve_support_path(
    path_text: str,
    *,
    kind: str,
    current_dir: Path,
    search_paths: tuple[Path, ...] = (),
) -> Path | None:
    """Resolve a support-file path for a given LaTeX command kind."""

    raw_path = Path(path_text).expanduser()
    roots = (Path("/"),) if raw_path.is_absolute() else (current_dir, *search_paths)
    extensions = _extensions_for_kind(kind)
    for root in roots:
        for candidate in _with_fallbacks(raw_path, extensions):
            full_candidate = candidate if candidate.is_absolute() else root / candidate
            if full_candidate.exists() and full_candidate.is_file():
                return full_candidate.resolve()
    return None


@dataclass(frozen=True)
class _SupportCommand:
    kind: str
    items: tuple[str, ...]
    arg_start: int
    arg_end: int


def _find_support_commands(text: str) -> tuple[_SupportCommand, ...]:
    commands: list[_SupportCommand] = []
    for kind, pattern in COMMAND_PATTERNS.items():
        for match in pattern.finditer(text):
            cursor = _skip_optional_argument(text, match.end())
            argument = read_required_argument(text, start=cursor)
            items = tuple(item.strip() for item in argument.content.split(",") if item.strip())
            commands.append(
                _SupportCommand(
                    kind=kind,
                    items=items,
                    arg_start=argument.start + 1,
                    arg_end=argument.end - 1,
                )
            )
    return tuple(sorted(commands, key=lambda item: item.arg_start))


def _skip_optional_argument(text: str, start: int) -> int:
    cursor = _skip_whitespace(text, start)
    if cursor < len(text) and text[cursor] == "[":
        optional = read_balanced(text, start=cursor, left="[")
        return _skip_whitespace(text, optional.end)
    return cursor


def _extensions_for_kind(kind: str) -> tuple[str, ...]:
    if kind == "documentclass":
        return (".cls",)
    if kind == "usepackage":
        return (".sty",)
    if kind == "bibliographystyle":
        return (".bst",)
    return (".bib",)


def _with_fallbacks(path: Path, extensions: tuple[str, ...]) -> tuple[Path, ...]:
    if path.suffix:
        return (path,)
    return tuple(path.with_suffix(extension) for extension in extensions)


def _latex_reference_for_output(kind: str, output_name: str) -> str:
    output_path = Path(output_name)
    if kind in {"bibliography", "bibliographystyle", "documentclass", "usepackage"}:
        return output_path.stem
    return output_name


def _apply_replacements(text: str, replacements: list[tuple[int, int, str]]) -> str:
    if not replacements:
        return text
    output: list[str] = []
    cursor = 0
    for start, end, replacement in sorted(replacements, key=lambda item: item[0]):
        output.append(text[cursor:start])
        output.append(replacement)
        cursor = end
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


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index
