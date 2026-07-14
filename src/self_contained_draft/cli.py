"""Command line interface for self-contained draft generation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__


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
    build.set_defaults(func=_not_implemented)

    inspect_figures = subparsers.add_parser(
        "inspect-figures",
        help="Inspect figures that would be included by a YAML config.",
    )
    inspect_figures.add_argument("config", help="Path to the YAML build config.")
    inspect_figures.set_defaults(func=_not_implemented)

    return parser


def _not_implemented(args: argparse.Namespace) -> int:
    raise SystemExit(
        f"'{args.command}' is not implemented yet. "
        "The package skeleton is in place; implementation starts in the next step."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)
