# Self-Contained Draft Packaging Plan

## Summary

Build this repo into a modern Python package that turns a LaTeX entry file into a cleaned, flattened, self-contained submission directory. The first implementation should preserve the legacy script's core behavior, then replace project-specific hard-coding with a reusable CLI and YAML config.

The default workflow will:

- Read a root `.tex` file.
- Strip comments safely.
- Inline supported `\input{...}` files recursively.
- Expand configured path/value macros needed to resolve inputs and figures.
- Detect `\includegraphics` calls in document order.
- Copy referenced figure files into the output directory as `fig_1.ext`, `fig_2a.ext`, etc.
- Rewrite `\includegraphics{...}` paths to those copied filenames.
- Optionally replace external appendix references using `.aux` label data.

## Key Changes

- Create a `src/self_contained_draft/` package with focused modules:
  - `latex.py`: low-level parsing helpers, comment stripping, brace parsing, command argument parsing.
  - `macros.py`: parse and expand simple `\def` and `\newcommand` macros, especially path-like macros.
  - `flatten.py`: recursively resolve `\input` files relative to the current file and configured search roots.
  - `figures.py`: find `\includegraphics`, resolve file extensions, copy assets, and rewrite paths.
  - `refs.py`: parse `.aux` files and replace selected `\ref` / `\eqref` values.
  - `cli.py`: CLI entrypoint.
- Vendor the useful parts of the old `parsing.py` into the package instead of importing from `~/numerical`.
- Use a modern PyPI-ready structure:
  - `pyproject.toml`
  - `README.md`
  - `src/` layout
  - `tests/`
  - CLI script named `self-contained-draft`
- Add a small YAML config, for example:

```yaml
input: RentalMarketsFinal.tex
output_dir: FinalManuscript
output_tex: RentalMarketsAER.tex
search_paths:
  - .
expand_macros:
  - dira
  - dirc
  - empiricalDir
  - pfdir
  - irfdir
external_aux:
  - RentalMarketsAppendix.aux
figure_naming: document-order
```

- Keep CLI flags for common overrides:

```bash
self-contained-draft build paper.yml
self-contained-draft build paper.yml --input Draft.tex --output-dir submission
self-contained-draft inspect-figures paper.yml
```

## Implementation Steps

1. Package skeleton:
   - Add `pyproject.toml`, `src/self_contained_draft/`, and `tests/`.
   - Set Python support to `>=3.10`.
   - Use `PyYAML` for config parsing.
   - Prefer stdlib `argparse` unless a richer CLI is desired later.

2. Port and harden parsing:
   - Move `BmaMatch`, `bma_search`, `match_to_bma`, and brace expansion into package code.
   - Replace generic `Exception` / `assert` failures with typed errors containing file path and nearby context.
   - Make comment stripping preserve escaped `%` and avoid stripping inside already escaped command text.

3. Flatten LaTeX:
   - Recursively inline `\input{...}` and `\input ...` where feasible.
   - Resolve inputs relative to the file that contains the command, then configured `search_paths`.
   - Try both explicit paths and `.tex` fallback.
   - Detect input cycles and report a clear error.

4. Macro handling:
   - Parse simple `\def\name{...}` and `\newcommand{\name}[n]{...}`.
   - Expand only configured macros by default, avoiding aggressive expansion of semantic/math macros.
   - Support the existing legacy use case where path macros are expanded before input and figure resolution.
   - Preserve unexpanded macros that are not needed for file resolution.

5. Automated figures:
   - After flattening and configured macro expansion, scan `\includegraphics[...]{...}` in document order.
   - Resolve extensions using common LaTeX graphic extensions: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.eps`.
   - Copy each unique source file to the output directory.
   - Name top-level figures `fig_1`, `fig_2`, etc.; when multiple graphics occur within one figure environment, name them `fig_2a`, `fig_2b`, etc.
   - Reuse the same copied filename if the exact same source file appears multiple times.
   - Rewrite only the graphics path argument, leaving options like `page=`, `trim=`, and `clip` unchanged.
   - Emit a manifest such as `self_contained_manifest.json` mapping original paths to copied filenames.

6. References:
   - Port `.aux` parsing for external appendix labels.
   - Apply replacements only for configured aux files.
   - Replace `\ref{label}` with `A.1` and `\eqref{label}` with `(A.1)` as in the legacy script.
   - Leave unresolved labels unchanged and report them in a warning list.

7. Output behavior:
   - Create or reuse the configured output directory.
   - Write the cleaned flattened TeX file there.
   - Copy figure assets into the same directory by default.
   - Do not collect bibliography, class, or style files in v1 unless explicitly added later.

8. Tests and validation:
   - Unit tests for brace parsing, comment stripping, macro expansion, input resolution, aux parsing, and figure rewriting.
   - Fixture-based integration test with nested `.tex` files, path macros, subfigures, missing figures, repeated figures, and escaped comments.
   - Regression fixture based on the observed legacy behavior, without depending on private Dropbox paths.
   - Add `python -m pytest` as the primary verification command.

## Assumptions

- v1 uses document-order figure naming, not compiled LaTeX counters.
- v1 output includes the flattened TeX file plus copied/renamed figure assets, not a full compile-ready bundle with `.bib`, `.bst`, `.cls`, or `.sty` collection.
- Project-specific behavior belongs in a small YAML config, with CLI flags for overrides.
- Macro expansion should be conservative: expand configured file/path/value macros, not every math/text macro in the preamble.
- Missing inputs or figures should fail by default, with a future `--allow-missing` option if needed.
