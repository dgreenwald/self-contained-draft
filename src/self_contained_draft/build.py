"""Build orchestration for self-contained LaTeX draft bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .figures import FigureAsset, rewrite_figures
from .processor import process_file
from .properties import PropertyInlineError, inline_property_macros
from .refs import parse_aux_files, replace_external_refs
from .support_files import SupportFile, copy_support_files


class BuildError(RuntimeError):
    """Raised when a draft build cannot be completed."""


@dataclass(frozen=True)
class BuildConfig:
    input: Path
    output_dir: Path
    output_tex: str
    search_paths: tuple[Path, ...] = ()
    expand_macros: tuple[str, ...] = ()
    external_aux: tuple[Path, ...] = ()
    figure_aux: Path | None = None
    strip_comments: bool = True
    allow_missing_inputs: bool = False
    allow_missing_figures: bool = False
    copy_support_files: bool = False
    inline_property_macros: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    output_tex: Path
    figure_assets: tuple[FigureAsset, ...]
    support_files: tuple[SupportFile, ...]
    replaced_refs: tuple[str, ...]
    unresolved_refs: tuple[str, ...]
    inlined_property_macros: tuple[str, ...] = ()
    inlined_property_replacements: int = 0
    removed_property_assignments: int = 0


def load_config(
    path: str | Path,
    *,
    input_override: str | Path | None = None,
    output_dir_override: str | Path | None = None,
    copy_support_files_override: bool | None = None,
) -> BuildConfig:
    """Load a YAML build config."""

    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except OSError as exc:
        raise BuildError(f"Could not read config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BuildError(f"Config {config_path} must contain a mapping")

    base_dir = config_path.parent
    input_value = input_override if input_override is not None else _required(raw, "input")
    output_dir_value = (
        output_dir_override if output_dir_override is not None else raw.get("output_dir", "submission")
    )
    copy_support = (
        copy_support_files_override
        if copy_support_files_override is not None
        else bool(raw.get("copy_support_files", False))
    )
    input_path = _resolve_config_path(input_value, base_dir=base_dir)
    output_dir = _resolve_config_path(output_dir_value, base_dir=base_dir)
    output_tex = str(raw.get("output_tex") or input_path.name)

    return BuildConfig(
        input=input_path,
        output_dir=output_dir,
        output_tex=output_tex,
        search_paths=tuple(
            _resolve_config_path(item, base_dir=base_dir)
            for item in _as_list(raw.get("search_paths", ()))
        ),
        expand_macros=tuple(str(item) for item in _as_list(raw.get("expand_macros", ()))),
        external_aux=tuple(
            _resolve_config_path(item, base_dir=base_dir)
            for item in _as_list(raw.get("external_aux", ()))
        ),
        figure_aux=(
            _resolve_config_path(raw["figure_aux"], base_dir=base_dir)
            if raw.get("figure_aux") is not None
            else None
        ),
        strip_comments=bool(raw.get("strip_comments", True)),
        allow_missing_inputs=bool(raw.get("allow_missing_inputs", False)),
        allow_missing_figures=bool(raw.get("allow_missing_figures", False)),
        copy_support_files=copy_support,
        inline_property_macros=tuple(
            str(item) for item in _as_list(raw.get("inline_property_macros", ()))
        ),
    )


def build_draft(config: BuildConfig) -> BuildResult:
    """Run the configured self-contained draft build."""

    text = process_file(
        config.input,
        search_paths=config.search_paths,
        strip_tex_comments=config.strip_comments,
        allow_missing_inputs=config.allow_missing_inputs,
        explicit_macros=config.expand_macros,
    )

    replaced_refs: tuple[str, ...] = ()
    unresolved_refs: tuple[str, ...] = ()
    if config.external_aux:
        labels = parse_aux_files(config.external_aux)
        ref_result = replace_external_refs(text, labels)
        text = ref_result.text
        replaced_refs = ref_result.replaced
        unresolved_refs = ref_result.unresolved

    property_result = None
    if config.inline_property_macros:
        try:
            property_result = inline_property_macros(text, config.inline_property_macros)
        except PropertyInlineError as exc:
            raise BuildError(str(exc)) from exc
        text = property_result.text

    support_files: tuple[SupportFile, ...] = ()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    if config.copy_support_files:
        support_result = copy_support_files(
            text,
            source_dir=config.input.parent,
            output_dir=config.output_dir,
            search_paths=config.search_paths,
            allow_missing=True,
        )
        text = support_result.text
        support_files = support_result.files

    figure_result = rewrite_figures(
        text,
        source_dir=config.input.parent,
        output_dir=config.output_dir,
        search_paths=config.search_paths,
        allow_missing_figures=config.allow_missing_figures,
        aux_file=config.figure_aux,
    )
    text = figure_result.text

    output_tex_path = config.output_dir / config.output_tex
    output_tex_path.write_text(text)
    return BuildResult(
        output_tex=output_tex_path,
        figure_assets=figure_result.assets,
        support_files=support_files,
        replaced_refs=replaced_refs,
        unresolved_refs=unresolved_refs,
        inlined_property_macros=property_result.macros if property_result is not None else (),
        inlined_property_replacements=(
            property_result.replacements if property_result is not None else 0
        ),
        removed_property_assignments=(
            property_result.removed_assignments if property_result is not None else 0
        ),
    )


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise BuildError(f"Config is missing required key: {key}")
    return raw[key]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _resolve_config_path(value: str | Path, *, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()
