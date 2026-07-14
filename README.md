# self-contained-draft

Create self-contained LaTeX draft bundles for submission.

This package is being migrated from a project-specific script into a reusable
CLI and Python package. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
for the staged implementation plan.

## Development

Install the package in editable mode from a development environment:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
python -m pytest
```

## Basic Usage

Create a YAML config:

```yaml
input: paper.tex
output_dir: submission
output_tex: paper_final.tex
expand_macros:
  - figdir
external_aux:
  - appendix.aux
copy_support_files: false
```

Build the self-contained draft:

```bash
self-contained-draft build paper.yml
```

By default, the build writes the flattened TeX file, copies referenced figures,
and rewrites figure paths. Set `copy_support_files: true` or pass
`--copy-support-files` to also copy local `.bib`, `.bst`, `.cls`, and `.sty`
files referenced by the document.
