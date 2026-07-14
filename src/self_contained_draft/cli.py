"""Command line interface for self-contained draft generation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__
from .build import BuildError, build_draft, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="self-contained-draft",
        description="Create self-contained LaTeX draft bundles for submission.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser(
        "build",
        help="Build a self-contained draft bundle from a YAML config.",
    )
    build.add_argument("config", help="Path to the YAML build config.")
    build.add_argument("--input", help="Override the input TeX file.")
    build.add_argument("--output-dir", help="Override the output directory.")
    build.add_argument(
        "--copy-support-files",
        action="store_true",
        help="Copy local .bib, .bst, .cls, and .sty files referenced by the document.",
    )
    build.set_defaults(func=_build)

    inspect_figures = subparsers.add_parser(
        "inspect-figures",
        help="Inspect figures that would be included by a YAML config.",
    )
    inspect_figures.add_argument("config", help="Path to the YAML build config.")
    inspect_figures.set_defaults(func=_not_implemented)

    return parser


def _build(args: argparse.Namespace) -> int:
    try:
        config = load_config(
            args.config,
            input_override=args.input,
            output_dir_override=args.output_dir,
            copy_support_files_override=True if args.copy_support_files else None,
        )
        result = build_draft(config)
    except BuildError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Wrote {result.output_tex}")
    print(f"Copied {len(result.figure_assets)} figure asset(s)")
    if config.copy_support_files:
        print(f"Copied {len(result.support_files)} support file(s)")
    if result.unresolved_refs:
        print(f"Unresolved external ref(s): {', '.join(result.unresolved_refs)}")
    return 0


def _not_implemented(args: argparse.Namespace) -> int:
    raise SystemExit(f"'{args.command}' is not implemented yet.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)
