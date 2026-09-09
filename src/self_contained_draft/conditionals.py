"""Opt-in simplification of literal, named TeX conditionals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re

from .latex import (
    ControlSequence,
    LatexParseError,
    control_word_suffix,
    iter_control_sequences,
    join_tex_fragments,
    skip_tex_tokens,
    strip_comments,
)


class ConditionalError(LatexParseError):
    """A configured conditional cannot be selected safely."""


PRIMITIVE_CONDITIONALS = frozenset({
    "if", "ifcat", "ifnum", "ifdim", "ifodd", "ifvmode", "ifhmode", "ifmmode",
    "ifinner", "ifvoid", "ifhbox", "ifvbox", "ifx", "ifeof", "iftrue", "iffalse",
    "ifcase", "ifdefined", "ifcsname", "iffontchar", "ifincsname", "ifabsnum",
    "ifabsdim",
})


def validate_flags(value: object) -> dict[str, bool]:
    """Validate the shared YAML/Python flag interface without coercing values."""

    if not isinstance(value, Mapping):
        raise ConditionalError("conditional_flags must be a mapping of names to booleans")
    flags: dict[str, bool] = {}
    for name, enabled in value.items():
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z@]+", name) is None:
            raise ConditionalError(f"Invalid conditional flag name: {name!r}; use a bare name such as MyFlag")
        if name.startswith("if"):
            raise ConditionalError(f"Invalid conditional flag name: {name!r}; omit the 'if' prefix")
        if "if" + name in PRIMITIVE_CONDITIONALS:
            raise ConditionalError(f"Conditional flag {name!r} would override a TeX primitive")
        if type(enabled) is not bool:
            raise ConditionalError(f"conditional_flags[{name!r}] must be a boolean")
        flags[name] = enabled
    return flags


@dataclass
class ConditionalSimplifier:
    flags: dict[str, bool]
    declared: set[str] = field(default_factory=set)

    def configured(self, name: str) -> bool:
        return name.startswith("if") and name[2:] in self.flags

    def operand_end(self, text: str, token: ControlSequence, *, source: str | None = None) -> int:
        """Protect primitive operands and reject prefixes that change selection."""
        if token.name in {"unless", "noexpand", "string"}:
            operand = next(iter(iter_control_sequences(text, start=token.end)), None)
            if (
                operand is not None and self.configured(operand.name)
                and not strip_comments(text[token.end:operand.start]).strip()
            ):
                raise ConditionalError(
                    f"Unsupported \\{token.name} before configured \\{operand.name}",
                    source=source, position=token.start, text=text,
                )
        count = {"if": 2, "ifcat": 2, "ifx": 2, "ifdefined": 1}.get(token.name, 0)
        return skip_tex_tokens(text, token.end, count)

    def declaration_end(self, text: str, token: ControlSequence) -> int:
        """Record a literal newif declaration and skip its operand."""
        operand = next(iter(iter_control_sequences(text, start=token.end)), None)
        if operand is not None and operand.name.startswith("if"):
            if not strip_comments(text[token.end:operand.start]).strip():
                self.declared.add(operand.name)
                return operand.end
        return token.end

    def select(
        self, text: str, opening: ControlSequence, *, source: str | None = None,
    ) -> tuple[str, int]:
        """Read one balanced block and return its selected, unsimplified branch."""

        stack: list[tuple[str, bool]] = [(opening.name, False)]
        alternative: ControlSequence | None = None
        skip_until = opening.end
        known = PRIMITIVE_CONDITIONALS | self.declared | {"if" + name for name in self.flags}
        for token in iter_control_sequences(text, start=opening.end):
            if token.start < skip_until:
                continue
            if token.name == "newif":
                # Declarations in discarded content must not change shared state.
                operand = next(iter(iter_control_sequences(text, start=token.end)), None)
                if (
                    operand is not None and operand.name.startswith("if")
                    and not strip_comments(text[token.end:operand.start]).strip()
                ):
                    known = known | {operand.name}
                    skip_until = operand.end
                continue
            if token.name in known:
                stack.append((token.name, False))
                skip_until = self.operand_end(text, token, source=source)
            elif token.name.startswith("if"):
                raise ConditionalError(
                    f"Unsupported conditional nesting: \\{token.name}",
                    source=source, position=token.start, text=text,
                )
            elif token.name == "else":
                name, seen_else = stack[-1]
                if seen_else:
                    raise ConditionalError(
                        "Duplicate \\else", source=source, position=token.start, text=text,
                    )
                stack[-1] = (name, True)
                if len(stack) == 1:
                    alternative = token
            elif token.name == "or":
                if stack[-1][0] != "ifcase" or stack[-1][1]:
                    raise ConditionalError(
                        "Unexpected \\or", source=source, position=token.start, text=text,
                    )
            elif token.name == "fi":
                stack.pop()
                if stack:
                    continue
                after_comments, end = control_word_suffix(text, token.end)
                if self.flags[opening.name[2:]]:
                    comments, begin = control_word_suffix(text, opening.end)
                    branch = comments + text[begin:(alternative or token).start]
                elif alternative is not None:
                    comments, begin = control_word_suffix(text, alternative.end)
                    branch = comments + text[begin:token.start]
                else:
                    branch = ""
                return join_tex_fragments(branch, after_comments), end
        raise ConditionalError(
            f"Missing \\fi for \\{opening.name}",
            source=source, position=opening.start, text=text,
        )

    def simplify(self, text: str, *, source: str | None = None) -> str:
        """Simplify a fragment, preserving ordinary unconfigured structures."""

        output = ""
        cursor = 0
        skip_until = 0
        for token in iter_control_sequences(text):
            if token.start < max(cursor, skip_until):
                continue
            if token.name == "newif":
                skip_until = self.declaration_end(text, token)
            elif self.configured(token.name):
                branch, end = self.select(text, token, source=source)
                output = join_tex_fragments(output, text[cursor:token.start])
                output = join_tex_fragments(output, self.simplify(branch, source=source))
                cursor = end
            else:
                skip_until = self.operand_end(text, token, source=source)
        return join_tex_fragments(output, text[cursor:])
