"""External LaTeX reference replacement from ``.aux`` files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .latex import LatexParseError, read_required_argument


class ReferenceError(RuntimeError):
    """Raised when external reference data cannot be read or parsed."""


@dataclass(frozen=True)
class ReferenceReplacementResult:
    """Result of replacing external references in TeX text."""

    text: str
    replaced: tuple[str, ...]
    unresolved: tuple[str, ...]


NEWLABEL_PATTERN = re.compile(r"\\newlabel\b")
REF_PATTERN = re.compile(r"\\(?P<kind>eqref|ref)\s*\{(?P<label>[^{}]+)\}")


def parse_aux_labels(text: str, *, source: str | None = None) -> dict[str, str]:
    """Parse ``\\newlabel`` entries from an aux file into label -> value."""

    labels: dict[str, str] = {}
    for match in NEWLABEL_PATTERN.finditer(text):
        try:
            key_arg = read_required_argument(text, start=match.end(), source=source)
            value_outer = read_required_argument(text, start=key_arg.end, source=source)
            value_inner = read_required_argument(
                value_outer.content,
                start=0,
                source=source,
            )
        except LatexParseError as exc:
            raise ReferenceError(
                f"Could not parse aux label"
                + (f" in {source}" if source is not None else "")
            ) from exc

        labels[key_arg.content.strip()] = value_inner.content.strip()
    return labels


def parse_aux_file(path: str | Path) -> dict[str, str]:
    """Read and parse a LaTeX aux file."""

    aux_path = Path(path).expanduser().resolve()
    try:
        text = aux_path.read_text()
    except OSError as exc:
        raise ReferenceError(f"Could not read aux file {aux_path}: {exc}") from exc
    return parse_aux_labels(text, source=str(aux_path))


def parse_aux_files(paths: list[str | Path] | tuple[str | Path, ...]) -> dict[str, str]:
    """Read multiple aux files, with later files overriding earlier labels."""

    labels: dict[str, str] = {}
    for path in paths:
        labels.update(parse_aux_file(path))
    return labels


def replace_external_refs(
    text: str,
    labels: dict[str, str],
    *,
    track_unresolved: bool = True,
) -> ReferenceReplacementResult:
    """Replace configured external ``\\ref`` and ``\\eqref`` commands."""

    replaced: list[str] = []
    unresolved: list[str] = []

    def replace_match(match: re.Match[str]) -> str:
        label = match.group("label").strip()
        value = labels.get(label)
        if value is None:
            if track_unresolved:
                unresolved.append(label)
            return match.group(0)

        replaced.append(label)
        if match.group("kind") == "eqref":
            return f"({value})"
        return value

    replaced_text = REF_PATTERN.sub(replace_match, text)
    return ReferenceReplacementResult(
        text=replaced_text,
        replaced=tuple(dict.fromkeys(replaced)),
        unresolved=tuple(dict.fromkeys(unresolved)),
    )
