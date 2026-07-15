# Repository Guidelines

This repository builds self-contained LaTeX submission bundles from papers that
may reference inputs, figures, bibliography files, and generated numeric values
across many directories.

## Project Structure
- `src/self_contained_draft/` contains the package and CLI.
  - `build.py` orchestrates config loading and the build pipeline.
  - `processor.py` performs path-aware recursive input flattening and macro expansion.
  - `figures.py`, `support_files.py`, `refs.py`, and `properties.py` handle figure copying/naming, support-file copying, aux-reference replacement, and expl3 property inlining.
  - `latex.py` contains shared lightweight LaTeX parsing helpers. Prefer extending these helpers over ad hoc string parsing.
- `tests/` contains focused pytest coverage by module plus an acceptance test.

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
  `allow_missing_inputs`, `allow_missing_figures`, and `inline_property_macros`.
- `figure_aux` is used to preserve document figure numbering, including appendix
  numbers such as `A.1`.
- `inline_property_macros` is opt-in. It replaces configured expl3 property
  lookup calls, such as `\steady{key}` or `\param{key}`, with raw values and
  removes the matching `\prop_gput:Nnn` property assignments.

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

## Testing Expectations
- Add regression tests for parser or LaTeX-token changes. Small whitespace
  changes can become visible PDF differences.
- Run at least the relevant focused tests after changes; run full `pytest`
  before considering a change complete.
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
