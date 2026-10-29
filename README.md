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

# Copy local .bib, .bst, .cls, and .sty files and class/style dependencies.
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

Nested `\input{...}` and `\file_get:nnN` paths are searched relative to the
including file, then through `search_paths`; extensionless reads also try `.tex`. Figures and
support files are searched relative to the root TeX file's directory, then
through `search_paths`, even when referenced from an included file. For graphics
without an extension, the search tries `.pdf`, `.png`, `.jpg`, `.jpeg`, and `.eps`
in that order within each directory.

## What The Build Does

- Recursively flattens `\input{...}` files, resolving nested inputs relative to
  the file that includes them.
- Inlines empty-setup `\file_get:nnN` reads as token-list assignments.
- Resolves simple macros in path contexts automatically, including paths used by
  `\input`, `\file_get:nnN`, `\includegraphics`, `\bibliography`, `\bibliographystyle`,
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
- Copies local support files and class/style dependencies when `copy_support_files: true`.
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
- `external_aux`: aux files used to replace matching `\ref{...}`,
  `\eqref{...}`, and `\subref{...}` values. Defaults to none.
- `figure_aux`: aux file used to map figure labels to document figure numbers.
- `strip_comments`: whether to strip comments. Defaults to `true`.
- `allow_missing_inputs`: preserve unresolved inputs instead of failing.
  Defaults to `false`.
- `allow_missing_figures`: preserve unresolved figures instead of failing.
  Defaults to `false`.
- `copy_support_files`: copy local `.bib`, `.bst`, `.cls`, and `.sty` files,
  recursively collecting local class/style dependencies. Defaults to `false`.
- `extra_files`: explicit files to copy, including when `copy_support_files` is
  `false`. Defaults to `[]`. Accepts relative paths or `{source, destination}`
  mappings; see below.
- `inline_property_macros`: expl3 property lookup macros to replace with raw
  values. Defaults to off.
- `conditional_flags`: mapping of flag names to fixed boolean values. Defaults
  to `{}` (no named conditional selection).

## Local Template Dependencies

With `copy_support_files: true`, the builder scans copied `.cls` and `.sty`
files for `\RequirePackage`, `\LoadClass`, literal braced `\input`, and
`\includegraphics` references. It also scans text files reached through
`\input`, including dependencies in macro bodies. Comments are ignored;
package lists, optional arguments, starred graphics commands, and common
image extension fallbacks are supported.

Dependencies resolve against the referring file's directory, then the root
manuscript directory, then `search_paths`. Only local files are collected:
installed TeX packages remain external, and unresolved references stay unchanged.
The builder does not execute template conditionals or expand computed paths.

Classes, styles, and bibliography files are copied to the bundle root. Inputs
and assets retain safe relative paths, such as `thumbnails/cas-email.jpeg`.
Absolute paths and paths containing `..` are relocated to their basenames.
References in copied text files are rewritten relative to the bundle root;
these bundles are intended to compile from that directory. Template assets
keep their names and do not enter the manuscript figure-numbering manifest.
Dependency cycles fail with the reference chain. Conflicting destinations,
including collisions with generated figures, the manuscript, or its manifest,
fail before collected files are copied.

For dependencies the parser cannot discover, list individual files explicitly:

```yaml
extra_files:
  - thumbnails/custom-logo.jpeg
  - source: ../shared/template-data.dat
    destination: data/template-data.dat
```

Sources resolve relative to the YAML directory. A string entry preserves that
relative path in the bundle. Absolute sources or sources outside the YAML
directory require a mapping with an explicit bundle-relative destination.
Destinations cannot be absolute or contain `..`. Missing files, directories,
and destination collisions are errors; globs are not expanded. Explicit files
are copied without dependency traversal and do not require
`copy_support_files: true`.

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
The corresponding declarations (`\newif\ifMyFlag`) and setters
(`\MyFlagtrue`, `\MyFlagfalse`) are removed from the output, including
`\global` prefixes on those setters. Unconfigured flags keep their declarations
and setters. Comments are retained when `strip_comments: false`.

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
conditional commands are unsupported. Prefixing a configured test or setter with
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

`external_aux` replaces matching `\ref` with its aux value and `\eqref`
with that value in parentheses. For `\subref{label}`, it looks up `sub@label`
and inserts the panel letter (such as `a`) without parentheses. Later aux files
override duplicate labels from
earlier files. References to literal `\label{...}` definitions in the flattened
manuscript remain as LaTeX commands and are excluded from unresolved warnings,
even if an external aux file contains the same label. Other references absent
from those aux files remain unchanged and are reported by the CLI as unresolved.
Missing panel entries are reported using the original reference label, even
when the ordinary figure label exists in the aux data. Local subfigure labels
remain LaTeX commands. Commands such as `\autoref`, `\cref`, and `\pageref`
are not replaced.

For a wrapper defined as `\newcommand{\psubref}[1]{(\subref{#1})}`, configure
`expand_macros: [psubref]` alongside `external_aux`. Macro expansion runs first,
so `Appendix Figure~\ref{fig:example}\psubref{fig:panel}` becomes
`Appendix Figure~B.12(a)` when the aux contains `fig:example` with value `B.12`
and `sub@fig:panel` with value `a`.

Support-file copying collects locally resolvable files referenced by
`\bibliography`, `\bibliographystyle`, `\addbibresource`, `\documentclass`, and
`\usepackage`. It preserves their basenames and rewrites the corresponding
paths. Missing support files remain unchanged, so installed TeX packages need
not be present locally. Class/style dependencies are collected recursively as
described under Local Template Dependencies; conflicting destinations fail
instead of overwriting one another.

## Token-list File Reads

The builder and standalone flattening utilities inline the empty-setup form
of `\file_get:nnN`, preserving its assignment semantics. For example, if
`data/value.dat` contains `0.282`, this call:

```tex
\file_get:nnN {data/value.dat} {} \l_value_tl
```

becomes a local assignment equivalent to:

```tex
\tl_set:Nn \l_value_tl {0.282}
```

The generated assignment preserves file line endings, including the final TeX
endline. Later uses of the variable remain TeX commands. Stored contents are not
executed by the builder: embedded `\input` calls and macro definitions remain
inside the token list. This is intended for data reads under the same category
codes as the surrounding source, such as numeric files in `\ExplSyntaxOn`.

The build resolves filename macros and path helpers using active definitions,
just as for `\input`. Missing files fail unless `allow_missing_inputs: true`,
which preserves the read. The `strip_comments` option also applies to loaded
contents. The destination must be a literal control sequence (optionally braced),
and contents must have balanced braces. Nonempty setup code is rejected; other
variants such as `\file_get:VnN` and `\file_get:nnNTF` remain unchanged.

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
