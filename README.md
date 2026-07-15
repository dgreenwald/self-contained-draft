# self-contained-draft

Create self-contained LaTeX draft bundles for submission.

self-contained-draft flattens a root `.tex` file, recursively resolves
`\input{...}` trees, copies/relabels figures, and optionally copies local
bibliography/class/style files and inlines generated numeric values.

## Installation

From a local checkout:

```bash
pip install -e ".[dev]"
```

This installs the CLI:

```bash
self-contained-draft --help
```

## Basic Usage

Create a YAML config:

```yaml
input: paper.tex
output_dir: submission
output_tex: manuscript.tex

# Optional search roots for inputs, figures, and support files.
search_paths:
  - ../figures
  - ../tables

# Optional explicit non-path macros to expand.
expand_macros:
  - figdir

# Optional aux files used to replace external \ref calls.
external_aux:
  - appendix.aux

# Optional aux file used to name figures according to document numbering.
figure_aux: paper.aux

# Copy local .bib, .bst, .cls, and .sty files.
copy_support_files: true

# Optional expl3 property lookup macros to inline as raw values.
inline_property_macros:
  - steady
  - param
```

Build the self-contained draft:

```bash
self-contained-draft build paper.yml
```

The build writes the flattened TeX file to `output_dir`, copies referenced
figures into that directory, and rewrites figure paths to local filenames such
as `fig_1.pdf` or `fig_A1.pdf`.

## What The Build Does

- Recursively flattens `\input{...}` files, resolving nested inputs relative to
  the file that includes them.
- Resolves simple macros in path contexts automatically, including paths used by
  `\input`, `\includegraphics`, `\bibliography`, `\bibliographystyle`,
  `\addbibresource`, `\documentclass`, and `\usepackage`.
- Expands explicitly configured macros from `expand_macros`.
- Strips LaTeX comments while preserving TeX line-continuation behavior.
- Copies figures and rewrites `\includegraphics` paths to local output names.
- Uses `figure_aux` when provided so appendix figures can be named with their
  document labels, e.g. `fig_A1.pdf`.
- Replaces external references from `external_aux` files.
- Copies local support files when `copy_support_files: true`.
- Optionally inlines expl3 property lookups from `inline_property_macros`.

## Configuration Reference

Required:

- `input`: root TeX file.

Optional:

- `output_dir`: output directory. Defaults to `submission`.
- `output_tex`: output TeX filename. Defaults to the input filename.
- `search_paths`: additional directories for resolving inputs, figures, and
  support files.
- `expand_macros`: macro names to expand outside path contexts.
- `external_aux`: aux files used to replace external `\ref{...}` values.
- `figure_aux`: aux file used to map figure labels to document figure numbers.
- `strip_comments`: whether to strip comments. Defaults to `true`.
- `allow_missing_inputs`: preserve unresolved inputs instead of failing.
  Defaults to `false`.
- `allow_missing_figures`: preserve unresolved figures instead of failing.
  Defaults to `false`.
- `copy_support_files`: copy local `.bib`, `.bst`, `.cls`, and `.sty` files.
  Defaults to `false`.
- `inline_property_macros`: expl3 property lookup macros to replace with raw
  values. Defaults to off.

## Property Lookup Inlining

Generated numeric tables often use expl3 properties:

```tex
\prop_gput:Nnn \g_equilibrium_steady_prop {baseline_frac_ltv_all} {0.877}
\cs_new:Npn \steady #1 { \prop_item:Nn \g_equilibrium_steady_prop {#1} }
```

With:

```yaml
inline_property_macros:
  - steady
```

the build replaces:

```tex
\topct{\steady{baseline_frac_ltv_all}}
```

with:

```tex
\topct{0.877}
```

and removes the matching `\prop_gput:Nnn` assignments. If a configured lookup
cannot be resolved, the build fails with a clear error.

## CLI Options

The build command accepts a config path plus a few overrides:

```bash
self-contained-draft build paper.yml \
  --input path/to/root.tex \
  --output-dir submission \
  --copy-support-files
```

`--copy-support-files` forces support-file copying on even if the YAML config
sets `copy_support_files: false`.

## Development

Run tests:

```bash
python -m pytest
```

For PDF equivalence checks, install `diff-pdf` and `poppler` from conda-forge:

```bash
conda install -c conda-forge diff-pdf poppler
```

Useful checks:

```bash
diff-pdf original.pdf submission/manuscript.pdf
pdftotext -layout submission/manuscript.pdf manuscript.txt
```
