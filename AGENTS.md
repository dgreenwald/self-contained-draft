# Repository Guidelines

This repository builds self-contained LaTeX submission bundles from papers that
may reference inputs, figures, bibliography files, and generated numeric values
across many directories.

## Project Structure
- `src/self_contained_draft/` contains the package and CLI.
  - `build.py` orchestrates config loading and the build pipeline.
  - `cli.py` defines `build` and its overrides; `inspect-figures` is a placeholder.
  - `processor.py` performs path-aware recursive input flattening and macro expansion.
  - `flatten.py` and `macros.py` provide standalone flattening and macro utilities;
    the build uses `processor.py`, so utility changes may also need integration changes.
  - `figures.py`, `support_files.py`, `refs.py`, and `properties.py` handle figure copying/naming, support-file copying, aux-reference replacement, and expl3 property inlining.
  - `latex.py` contains shared lightweight LaTeX parsing helpers. Prefer extending these helpers over ad hoc string parsing.
- `tests/` contains focused pytest coverage by module plus an acceptance test.
  Path-aware processor regressions currently live in `tests/test_build.py`.

## Environment And Commands
- Python requirement is `>=3.10`; runtime dependency is `PyYAML`.
- Install for development with:
  ```bash
  pip install -e ".[dev]"
  ```
- Run the full test suite with:
  ```bash
  pytest
  ```
  or:
  ```bash
  python -m pytest
  ```
- Build from a YAML config with:
  ```bash
  self-contained-draft build path/to/config.yml
  ```

## Configuration Notes
- Common YAML keys include `input`, `output_dir`, `output_tex`, `search_paths`,
  `expand_macros`, `external_aux`, `figure_aux`, `copy_support_files`,
  `strip_comments`, `allow_missing_inputs`, `allow_missing_figures`, and
  `inline_property_macros`. Keep README defaults aligned with `load_config`.
- Relative config paths, including CLI overrides, resolve against the YAML
  directory. Nested inputs resolve against their including file; figures and
  support files resolve against the root TeX directory, then `search_paths`.
- `figure_aux` is used to preserve document figure numbering, including appendix
  numbers such as `A.1`, in copied figure filenames. Unmatched labels fall back
  to encounter order. Builds write `self_contained_manifest.json` for unique figures.
- `external_aux` replaces matching `\ref` and `\eqref` calls; unmatched calls
  remain and are reported, including internal references.
- Support-file copying is opt-in and skips missing files in the build pipeline.
  It copies directly referenced local files, without traversing their dependencies.
- `inline_property_macros` is opt-in. It replaces configured expl3 property
  lookup calls, such as `\steady{key}` or `\param{key}`, with raw values and
  removes the matching `\prop_gput:Nnn` property assignments and supported
  property initializers. Lookup helper definitions remain.

## LaTeX Parsing Rules
- Keep parsing conservative. This is not a complete TeX parser.
- Use balanced-brace helpers from `latex.py` for command arguments.
- Preserve TeX token behavior when literalizing macro expansions:
  - A replacement ending in a control word such as `\unskip` needs a token
    separator like `{}` before following source spaces.
  - `%` line continuations must remove the newline and following indentation;
    otherwise macro bodies such as `\newcommand{\topct}[1]{% ... }` can gain a
    real leading space in the compiled PDF.
- Do not broadly expand ordinary content macros. The processor should expand
  macros automatically only when needed for paths, and otherwise only when
  explicitly configured.
- Preserve definitions active at each call, including nested-input redefinitions
  and transitive path helpers. `\IfFileExists` selects a branch using a local
  existence check relative to the including file, without search-path lookup.
- Distinguish standalone utility support from CLI support: the build requires
  braced inputs and does not flatten `\include` or implement general TeX scoping.

## Testing Expectations
- Add regression tests for parser or LaTeX-token changes. Small whitespace
  changes can become visible PDF differences.
- Run at least the relevant focused tests after changes; run full `pytest`
  before considering a change complete.
- The automated acceptance test uses fixture assets and does not compile TeX.
  The build itself only prepares sources; PDF validation is a separate step.
- For manuscript-level checks, compare PDFs with `diff-pdf` and use
  `pdftotext -layout` to inspect whether differences are text/layout or only
  metadata/toolchain noise.

## Coding Style
- Follow existing dataclass-heavy, small-helper style.
- Keep public behavior opt-in when it is project-specific, especially for
  generated values and nonstandard LaTeX idioms.
- Prefer clear errors over silent fallbacks when configured behavior cannot be
  completed safely.
- Avoid unrelated refactors; this repo is intentionally small and focused.
