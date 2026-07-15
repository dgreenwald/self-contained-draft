"""Figure discovery, copying, and path rewriting for LaTeX drafts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import shutil

from .latex import LatexParseError, read_balanced, read_required_argument
from .refs import parse_aux_file


class FigureError(RuntimeError):
    """Raised when figure assets cannot be resolved or copied."""


GRAPHICS_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")
INCLUDEGRAPHICS_PATTERN = re.compile(r"\\includegraphics\b")
FIGURE_BEGIN_PATTERN = re.compile(r"\\begin\s*\{\s*figure\*?\s*\}")
FIGURE_END_PATTERN = re.compile(r"\\end\s*\{\s*figure\*?\s*\}")
LABEL_PATTERN = re.compile(r"\\label\s*\{([^{}]+)\}")


@dataclass(frozen=True)
class IncludeGraphics:
    """A parsed ``\\includegraphics`` command occurrence."""

    start: int
    end: int
    path_start: int
    path_end: int
    path_text: str
    options: str | None
    figure_index: int | None
    panel_index: int | None
    label: str | None


@dataclass(frozen=True)
class FigureAsset:
    """A resolved figure asset and its output filename."""

    original_path: str
    resolved_path: Path
    output_name: str


@dataclass(frozen=True)
class FigureRewriteResult:
    """Result of copying figure assets and rewriting graphics paths."""

    text: str
    assets: tuple[FigureAsset, ...]

    def manifest(self) -> list[dict[str, str]]:
        return [
            {
                "original_path": asset.original_path,
                "resolved_path": str(asset.resolved_path),
                "output_name": asset.output_name,
            }
            for asset in self.assets
        ]


def rewrite_figures(
    text: str,
    *,
    source_dir: str | Path,
    output_dir: str | Path,
    search_paths: tuple[str | Path, ...] = (),
    copy_assets: bool = True,
    write_manifest: bool = True,
    allow_missing_figures: bool = False,
    aux_file: str | Path | None = None,
) -> FigureRewriteResult:
    """Copy referenced figures to ``output_dir`` and rewrite graphics paths."""

    source_root = Path(source_dir).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    normalized_search_paths = _normalize_search_paths(search_paths, base_dir=source_root)
    includes = find_includegraphics(text)
    figure_numbers = parse_aux_file(aux_file) if aux_file is not None else None
    output_names = assign_output_names(includes, figure_numbers=figure_numbers)

    destination.mkdir(parents=True, exist_ok=True)
    copied_by_source: dict[Path, FigureAsset] = {}
    assets_by_include: dict[int, FigureAsset] = {}
    manifest_assets: list[FigureAsset] = []

    for include in includes:
        resolved = resolve_graphics_path(
            include.path_text,
            current_dir=source_root,
            search_paths=normalized_search_paths,
        )
        if resolved is None:
            if allow_missing_figures:
                continue
            raise FigureError(
                f"Could not resolve \\includegraphics{{{include.path_text}}} from {source_root}"
            )

        existing = copied_by_source.get(resolved)
        if existing is not None:
            assets_by_include[include.start] = existing
            continue

        output_name = output_names[include.start] + resolved.suffix
        asset = FigureAsset(
            original_path=include.path_text,
            resolved_path=resolved,
            output_name=output_name,
        )
        copied_by_source[resolved] = asset
        assets_by_include[include.start] = asset
        manifest_assets.append(asset)

        if copy_assets:
            shutil.copy2(resolved, destination / output_name)

    rewritten = rewrite_includegraphics_paths(text, includes, assets_by_include)

    result = FigureRewriteResult(text=rewritten, assets=tuple(manifest_assets))
    if write_manifest:
        (destination / "self_contained_manifest.json").write_text(
            json.dumps(result.manifest(), indent=2) + "\n"
        )
    return result


def find_includegraphics(text: str, *, source: str | None = None) -> tuple[IncludeGraphics, ...]:
    """Find ``\\includegraphics`` commands and assign figure/panel positions."""

    figure_spans = _find_figure_spans(text)
    raw_includes: list[tuple[int, int, str | None, int, int, str]] = []
    for match in INCLUDEGRAPHICS_PATTERN.finditer(text):
        options, cursor = _read_optional_options(text, match.end(), source=source)
        argument = read_required_argument(text, start=cursor, source=source)
        raw_includes.append(
            (
                match.start(),
                argument.end,
                options,
                argument.start,
                argument.end,
                argument.content.strip(),
            )
        )

    panel_counts: dict[int, int] = {}
    figure_counter = 0
    span_to_index: dict[tuple[int, int], int] = {}
    includes: list[IncludeGraphics] = []
    raw_spans = [
        _containing_span(start, figure_spans)
        for start, _, _, _, _, _ in raw_includes
    ]

    for index, (start, end, options, path_start, path_end, path_text) in enumerate(raw_includes):
        span = raw_spans[index]
        next_start = _next_include_start_in_span(index, raw_includes, raw_spans)
        if span is None:
            figure_counter += 1
            figure_index = figure_counter
            panel_index = None
        else:
            if span not in span_to_index:
                figure_counter += 1
                span_to_index[span] = figure_counter
            figure_index = span_to_index[span]
            panel_counts[figure_index] = panel_counts.get(figure_index, 0) + 1
            panel_index = panel_counts[figure_index]

        includes.append(
            IncludeGraphics(
                start=start,
                end=end,
                path_start=path_start,
                path_end=path_end,
                path_text=path_text,
                options=options,
                figure_index=figure_index,
                panel_index=panel_index,
                label=_label_for_include(text, start=start, end=end, span=span, next_start=next_start),
            )
        )

    panel_totals: dict[int, int] = {}
    for include in includes:
        if include.panel_index is not None and include.figure_index is not None:
            panel_totals[include.figure_index] = panel_totals.get(include.figure_index, 0) + 1

    normalized: list[IncludeGraphics] = []
    for include in includes:
        panel_index = include.panel_index
        if (
            include.figure_index is not None
            and panel_index == 1
            and panel_totals.get(include.figure_index, 0) == 1
        ):
            panel_index = None
        normalized.append(
            IncludeGraphics(
                start=include.start,
                end=include.end,
                path_start=include.path_start,
                path_end=include.path_end,
                path_text=include.path_text,
                options=include.options,
                figure_index=include.figure_index,
                panel_index=panel_index,
                label=include.label,
            )
        )
    return tuple(normalized)


def assign_output_names(
    includes: tuple[IncludeGraphics, ...],
    *,
    figure_numbers: dict[str, str] | None = None,
) -> dict[int, str]:
    """Assign document-order names such as ``fig_1`` and ``fig_2a``."""

    names: dict[int, str] = {}
    for include in includes:
        if figure_numbers is not None and include.label is not None:
            number = figure_numbers.get(include.label)
            if number is not None:
                names[include.start] = f"fig_{_sanitize_figure_number(number)}"
                continue
        if include.figure_index is None:
            raise FigureError("Cannot assign a figure name without a figure index")
        suffix = ""
        if include.panel_index is not None:
            suffix = _panel_suffix(include.panel_index)
        names[include.start] = f"fig_{include.figure_index}{suffix}"
    return names


def resolve_graphics_path(
    path_text: str,
    *,
    current_dir: Path,
    search_paths: tuple[Path, ...] = (),
) -> Path | None:
    """Resolve a graphics path, trying common LaTeX graphics extensions."""

    raw_path = Path(path_text).expanduser()
    roots = (Path("/"),) if raw_path.is_absolute() else (current_dir, *search_paths)
    for root in roots:
        for candidate in _with_graphics_fallbacks(raw_path):
            full_candidate = candidate if candidate.is_absolute() else root / candidate
            if full_candidate.exists() and full_candidate.is_file():
                return full_candidate.resolve()
    return None


def rewrite_includegraphics_paths(
    text: str,
    includes: tuple[IncludeGraphics, ...],
    assets_by_include: dict[int, FigureAsset],
) -> str:
    """Rewrite graphics path arguments for includes that have resolved assets."""

    output: list[str] = []
    cursor = 0
    for include in includes:
        asset = assets_by_include.get(include.start)
        if asset is None:
            continue
        output.append(text[cursor : include.path_start + 1])
        output.append(Path(asset.output_name).stem)
        output.append(text[include.path_end - 1 : include.path_end])
        cursor = include.path_end
    if not output:
        return text
    output.append(text[cursor:])
    return "".join(output)


def _read_optional_options(
    text: str,
    start: int,
    *,
    source: str | None,
) -> tuple[str | None, int]:
    cursor = _skip_whitespace(text, start)
    if cursor >= len(text) or text[cursor] != "[":
        return None, cursor
    options = read_balanced(text, start=cursor, left="[", source=source)
    return options.content, options.end


def _find_figure_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while True:
        begin = FIGURE_BEGIN_PATTERN.search(text, cursor)
        if begin is None:
            break
        end = FIGURE_END_PATTERN.search(text, begin.end())
        if end is None:
            raise LatexParseError(
                "Unclosed figure environment",
                position=begin.start(),
                text=text,
            )
        spans.append((begin.start(), end.end()))
        cursor = end.end()
    return tuple(spans)


def _containing_span(position: int, spans: tuple[tuple[int, int], ...]) -> tuple[int, int] | None:
    for start, end in spans:
        if start <= position < end:
            return start, end
    return None


def _next_include_start_in_span(
    index: int,
    raw_includes: list[tuple[int, int, str | None, int, int, str]],
    raw_spans: list[tuple[int, int] | None],
) -> int | None:
    span = raw_spans[index]
    for next_index in range(index + 1, len(raw_includes)):
        if raw_spans[next_index] == span:
            return raw_includes[next_index][0]
        if span is None or raw_includes[next_index][0] > span[1]:
            return None
    return None


def _label_for_include(
    text: str,
    *,
    start: int,
    end: int,
    span: tuple[int, int] | None,
    next_start: int | None,
) -> str | None:
    if span is None:
        search_end = next_start if next_start is not None else len(text)
        match = LABEL_PATTERN.search(text, end, search_end)
        return match.group(1) if match is not None else None

    search_end = next_start if next_start is not None else span[1]
    labels_after_include = [
        match.group(1)
        for match in LABEL_PATTERN.finditer(text, end, search_end)
    ]
    if labels_after_include:
        return labels_after_include[0]

    includes_in_span = len(INCLUDEGRAPHICS_PATTERN.findall(text[span[0] : span[1]]))
    if includes_in_span == 1:
        labels_in_span = [
            match.group(1)
            for match in LABEL_PATTERN.finditer(text, span[0], span[1])
        ]
        if labels_in_span:
            return labels_in_span[-1]
    return None


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


def _with_graphics_fallbacks(path: Path) -> tuple[Path, ...]:
    if path.suffix:
        return (path,)
    return tuple(path.with_suffix(extension) for extension in GRAPHICS_EXTENSIONS)


def _panel_suffix(index: int) -> str:
    if index < 1:
        raise FigureError("Panel indexes must be positive")
    letters: list[str] = []
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("a") + remainder))
    return "".join(reversed(letters))


def _sanitize_figure_number(number: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", number)


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index
