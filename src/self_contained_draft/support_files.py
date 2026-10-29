"""Optional collection of local bibliography, class, and style files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from .figures import GRAPHICS_EXTENSIONS
from .latex import (
    iter_control_sequences,
    mask_comments,
    read_optional_argument,
    read_required_argument,
    strip_comments,
)


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


@dataclass(frozen=True)
class ExtraFile:
    """An explicit source file and its bundle-relative destination."""

    source: Path
    destination: str


ROOT_COMMANDS = {
    "documentclass", "usepackage", "bibliography", "bibliographystyle", "addbibresource",
}
DEPENDENCY_COMMANDS = ROOT_COMMANDS | {"RequirePackage", "LoadClass", "input", "includegraphics"}


def validate_output_path(name: str, *, output_dir: Path) -> str:
    """Validate and normalize a bundle-relative file destination."""

    path = Path(name)
    if not name or path.is_absolute() or ".." in path.parts or path == Path("."):
        raise SupportFileError(f"Invalid bundle destination: {name!r}")
    target = output_dir / path
    if not target.resolve().is_relative_to(output_dir.resolve()):
        raise SupportFileError(f"Bundle destination escapes output directory: {name!r}")
    if target.is_dir() or any(parent.is_file() for parent in target.parents):
        raise SupportFileError(f"File/directory collision at bundle destination {name!r}")
    return path.as_posix()


def reserve_output_path(
    name: str, owner: object, *, outputs: dict[str, object], output_dir: Path,
) -> str:
    """Reserve a destination, rejecting file and directory collisions."""

    name = validate_output_path(name, output_dir=output_dir)
    for existing, previous in outputs.items():
        if existing == name:
            if previous == owner:
                return name
            raise SupportFileError(f"Filename collision at {name!r}: {previous} and {owner}")
        if Path(existing) in Path(name).parents or Path(name) in Path(existing).parents:
            raise SupportFileError(f"File/directory collision: {existing!r} and {name!r}")
    outputs[name] = owner
    return name


def copy_support_files(
    text: str,
    *,
    source_dir: str | Path,
    output_dir: str | Path,
    search_paths: tuple[str | Path, ...] = (),
    allow_missing: bool = False,
    extra_files: tuple[ExtraFile, ...] = (),
    collect_references: bool = True,
    reserved_outputs: tuple[str, ...] = (),
) -> SupportFileResult:
    """Collect local support dependencies, validate destinations, then copy."""

    source_root = Path(source_dir).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    search = _normalize_search_paths(search_paths, base_dir=source_root)
    outputs: dict[str, object] = {}
    for index, name in enumerate(reserved_outputs):
        reserve_output_path(name, f"generated output {index}: {name}",
                            outputs=outputs, output_dir=destination)
    files: dict[str, SupportFile] = {}
    rewritten: dict[Path, str] = {}
    active: list[Path] = []

    def collect(resolved: Path, item: str, kind: str, name: str, *, scan: bool) -> None:
        name = reserve_output_path(name, resolved, outputs=outputs, output_dir=destination)
        if resolved in active:
            chain = " -> ".join(str(path) for path in [*active, resolved])
            raise SupportFileError(f"Support dependency cycle: {chain}")
        files.setdefault(name, SupportFile(kind, item, resolved, name))
        if scan and resolved not in rewritten:
            active.append(resolved)
            rewritten[resolved] = rewrite(resolved.read_text(), resolved.parent, dependencies=True)
            active.pop()

    def rewrite(content: str, current_dir: Path, *, dependencies: bool) -> str:
        replacements: list[tuple[int, int, str]] = []
        for command in _find_support_commands(content, dependencies=dependencies):
            parts: list[str] = []
            changed = False
            for item in command.items:
                if not _literal_path(item):
                    parts.append(item)
                    continue
                resolved = resolve_support_path(
                    item, kind=command.kind, current_dir=current_dir,
                    search_paths=(source_root, *search),
                )
                if resolved is None:
                    if dependencies or allow_missing:
                        parts.append(item)
                        continue
                    raise SupportFileError(
                        f"Could not resolve {command.kind} support file {item!r} from {current_dir}"
                    )
                name = resolved.name
                if dependencies and command.kind in {"input", "includegraphics"}:
                    relative = Path(item)
                    if not relative.is_absolute() and ".." not in relative.parts:
                        name = relative.as_posix()
                        if not relative.suffix:
                            name += resolved.suffix
                collect(
                    resolved, item, command.kind, name,
                    scan=command.kind == "input" or resolved.suffix in {".cls", ".sty"},
                )
                parts.append(_latex_reference_for_output(command.kind, name))
                changed = True
            if changed:
                replacements.append((command.arg_start, command.arg_end, ",".join(parts)))
        return _apply_replacements(content, replacements)

    result_text = rewrite(text, source_root, dependencies=False) if collect_references else text
    for extra in extra_files:
        resolved = extra.source.expanduser().resolve()
        if not resolved.is_file():
            raise SupportFileError(f"Could not resolve extra file {str(extra.source)!r}")
        name = validate_output_path(extra.destination, output_dir=destination)
        collect(resolved, str(extra.source), "extra", name, scan=False)

    # Discovery and destination validation must finish before any file is copied.
    for name, file in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if file.resolved_path in rewritten:
            target.write_text(rewritten[file.resolved_path])
        elif file.resolved_path != target.resolve():
            shutil.copy2(file.resolved_path, target)
    return SupportFileResult(text=result_text, files=tuple(files.values()))


def _literal_path(item: str) -> bool:
    return bool(item) and not any(char in item for char in "\\{}#%~")


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


def _find_support_commands(text: str, *, dependencies: bool = False) -> tuple[_SupportCommand, ...]:
    commands: list[_SupportCommand] = []
    parse_text = mask_comments(text)
    for token in iter_control_sequences(parse_text):
        kind = token.name
        if kind not in (DEPENDENCY_COMMANDS if dependencies else ROOT_COMMANDS):
            continue
        cursor = token.end
        if kind == "includegraphics" and parse_text[cursor:cursor + 1] == "*":
            cursor += 1
        cursor = _skip_whitespace(parse_text, cursor)
        optional = read_optional_argument(parse_text, start=cursor)
        if optional is not None:
            cursor = _skip_whitespace(parse_text, optional.end)
        if parse_text[cursor:cursor + 1] != "{":
            continue
        argument = read_required_argument(parse_text, start=cursor)
        raw = strip_comments(text[argument.start + 1:argument.end - 1]).strip()
        items = (raw,)
        if kind not in {"input", "includegraphics", "addbibresource"}:
            items = tuple(item.strip() for item in raw.split(","))
        commands.append(_SupportCommand(kind, items, argument.start + 1, argument.end - 1))
    return tuple(commands)


def _extensions_for_kind(kind: str) -> tuple[str, ...]:
    if kind in {"documentclass", "LoadClass"}:
        return (".cls",)
    if kind in {"usepackage", "RequirePackage"}:
        return (".sty",)
    if kind == "bibliographystyle":
        return (".bst",)
    if kind == "input":
        return ("", ".tex")
    if kind == "includegraphics":
        return GRAPHICS_EXTENSIONS
    return (".bib",)


def _with_fallbacks(path: Path, extensions: tuple[str, ...]) -> tuple[Path, ...]:
    if path.suffix:
        return (path,)
    return tuple(path.with_suffix(extension) for extension in extensions)


def _latex_reference_for_output(kind: str, output_name: str) -> str:
    output_path = Path(output_name)
    if kind in {
        "bibliography", "bibliographystyle", "documentclass", "usepackage",
        "RequirePackage", "LoadClass",
    }:
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
