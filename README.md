# self-contained-draft

Create self-contained LaTeX draft bundles for submission.

self-contained-draft flattens a root `.tex` file, recursively resolves
`\input{...}` trees, copies/relabels figures, and optionally copies local
bibliography/class/style files and inlines generated numeric values.

## Installation

From a local checkout:

```bash
pip install -e .
```

Requires Python 3.10 or newer. PyYAML is installed as a runtime dependency.

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
  - topct

# Optional aux files used to replace external \ref and \eqref calls.
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

# Optional fixed values for \ifNAME ... \else ... \fi blocks.
conditional_flags:
  MyFlag: true
```

Build the self-contained draft:

```bash
self-contained-draft build paper.yml
```

The build writes the flattened TeX file to `output_dir`, copies referenced
figures into that directory, and rewrites figure paths to local filenames such
as `fig_1.pdf` or `fig_A1.pdf`. TeX references omit the extension, for example
`\includegraphics{fig_1}`. It also writes `self_contained_manifest.json`, a JSON
list with `original_path`, `resolved_path`, and `output_name` for each unique
copied figure. Repeated uses of the same source reuse its first output name.

The command prepares source files; it does not compile a PDF or run bibliography
tools. Existing output files with matching names are overwritten, and unrelated
files in the output directory are retained.

### Path Resolution

Relative config paths (including CLI overrides) are resolved against the YAML
file's directory. `output_tex` is a filename within `output_dir`.

Nested `\input{...}` paths are searched relative to the including file, then
through `search_paths`; extensionless inputs also try `.tex`. Figures and
support files are searched relative to the root TeX file's directory, then
through `search_paths`, even when referenced from an included file. For graphics
without an extension, the search tries `.pdf`, `.png`, `.jpg`, `.jpeg`, and `.eps`
in that order within each directory.

## What The Build Does

- Recursively flattens `\input{...}` files, resolving nested inputs relative to
  the file that includes them.
- Resolves simple macros in path contexts automatically, including paths used by
  `\input`, `\includegraphics`, `\bibliography`, `\bibliographystyle`,
  `\addbibresource`, `\documentclass`, and `\usepackage`.
- Expands explicitly configured macros from `expand_macros`.
- Automatically expands helper macros that produce path commands, including
  helpers that call other path helpers, using definitions active at the call.
- Evaluates `\IfFileExists{path}{then}{else}` and processes the selected branch.
  The existence check uses the including file's directory; it does not consult
  `search_paths` or the TeX installation.
- Selects branches of configured `\ifNAME ... \else ... \fi` blocks, including
  inside retained macro definitions, before processing their contents.
- Strips LaTeX comments while preserving TeX line-continuation behavior.
- Copies figures and rewrites `\includegraphics` paths to local output names.
- Uses `figure_aux` when provided so appendix figures can be named with their
  document labels, e.g. `fig_A1.pdf`. Without a matching aux label, names follow
  encounter order, with panel suffixes such as `fig_1a.pdf` and `fig_1b.pdf` for
  multiple graphics within a `figure` or `figure*` environment.
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
- `external_aux`: aux files used to replace matching `\ref{...}` and
  `\eqref{...}` values. Defaults to none.
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
- `conditional_flags`: mapping of flag names to fixed boolean values. Defaults
  to `{}` (no named conditional selection).

## Conditional Branch Selection

Set a flag in YAML:

```yaml
conditional_flags:
  MyFlag: true
  ShowAppendix: false
```

The build turns `\ifMyFlag yes\else no\fi` into `yes`. Setting `MyFlag: false`
produces `no`. An omitted `\else` means the false branch is empty. Branch text
keeps its meaningful whitespace; ignored spaces after conditional control words
are consumed, and paragraph breaks and control-word boundaries are preserved.

Keys are case-sensitive bare names using ASCII letters or `@`, without a leading
backslash or `if` prefix. Values must be YAML booleans, not quoted strings or
numbers. Names that would override built-in TeX conditionals are rejected.

Override YAML values, or supply flags without a YAML mapping, with repeatable
CLI options:

```bash
self-contained-draft build paper.yml --flag MyFlag=false --flag ShowAppendix=true
```

CLI values must be lowercase `true` or `false`. They override YAML values, and
the last occurrence of a repeated flag wins. These are fixed build values:
source assignments such as `\MyFlagfalse` do not change branch selection.
Declarations (`\newif\ifMyFlag`) and assignments remain in the output.

Selection applies to root and included files, macro bodies (even when the macro
is retained), and expanded helpers. Discarded branches contribute no inputs,
figures, support files, macro definitions, or property values. Files referenced
only by discarded branches need not exist. Unconfigured conditionals remain for
TeX to evaluate, while configured tests inside them are simplified.

Nested blocks are supported when their openers are configured flags, standard
TeX/e-TeX conditionals, or custom flags declared with `\newif` in encountered
source. Nested `\ifcase`/`\or` structures are preserved without evaluation.
Comments are ignored when matching delimiters, even with `strip_comments: false`.
Missing `\fi`, duplicate `\else`, and unknown `\if...` commands nested in a
configured block produce contextual errors rather than guessed boundaries.

Each block must balance within its source file, macro body, or expanded fragment.
Cross-file delimiters, arbitrary conditional aliases, and dynamically constructed
conditional commands are unsupported. Prefixing a configured test with
`\unless`, `\noexpand`, or `\string` is also rejected. This feature selects
literal named tests; it does not implement general TeX execution.

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
definition or a lookup key cannot be found, the build fails with a clear error.
Matching `\prop_new:N` initializers, including the supported
`\prop_if_exist:NF` guard, are also removed; lookup helper definitions remain.
This supports the one-argument `\cs_new:Npn` wrapper shown above, with literal
keys and values. It does not evaluate arbitrary expl3 code or numeric expressions.

## References And Support Files

`external_aux` replaces every matching `\ref` with its aux value and `\eqref`
with that value in parentheses. Later aux files override duplicate labels from
earlier files. References absent from those aux files remain unchanged and are
reported by the CLI as unresolved, including ordinary internal references.
Commands such as `\autoref`, `\cref`, and `\pageref` are not replaced.

Support-file copying collects locally resolvable files referenced by
`\bibliography`, `\bibliographystyle`, `\addbibresource`, `\documentclass`, and
`\usepackage`. It preserves their basenames and rewrites the corresponding
paths. Missing support files remain unchanged, so installed TeX packages need
not be present locally. Dependencies inside copied support files are not scanned
recursively; files from different directories must have distinct basenames to
avoid overwriting one another.

## Parser Scope

The build uses a lightweight parser. Use braced `\input{...}` commands;
`\include` is not flattened. Supported macro definitions include zero-argument
`\def` and `\newcommand`/`\renewcommand` (including starred forms) with required
arguments and an optional first argument using `[nargs][default]`. Omitted
options use the default; explicit `[]` supplies an empty first argument. Closing
brackets inside braces or escaped as `\]` do not end an option. General TeX
execution or scoping is not implemented. Ordinary content macros stay intact unless explicitly
selected for expansion.

For example, with `expand_macros: [plotExtremaNum]`, this definition:

```tex
\newcommand{\plotExtremaNum}[2][]{%
\num[round-mode=places,round-precision=2,#1]{\plotExtremaExpanded{#2}}%
}
```

expands `\plotExtremaNum[round-precision=4]{key}` to
`\num[round-mode=places,round-precision=2,round-precision=4]{\plotExtremaExpanded{key}}`.
Omitting the option substitutes an empty `#1`, retaining the template's trailing
comma. Numeric formatting stays in LaTeX; inner commands need their own expansion
configuration if they should also be replaced.

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

Use `self-contained-draft --version` to print the package version.
`inspect-figures` appears in CLI help but is not implemented yet.

## Development

Install development dependencies and run the full test suite:

```bash
pip install -e ".[dev]"
python -m pytest
```

Tests include a bundle acceptance test using fixture assets; they do not require
a TeX installation or compile PDFs.

For PDF equivalence checks, install `diff-pdf` and `poppler` from conda-forge:

```bash
conda install -c conda-forge diff-pdf poppler
```

Useful checks:

```bash
diff-pdf original.pdf submission/manuscript.pdf
pdftotext -layout submission/manuscript.pdf manuscript.txt
```
