"""Bounded CommonMark presentation comparison for Linear read-back only.

Never canonicalizes signed payloads, approval digests, or execution contents.
Unsupported constructs fail closed unless the original bytes match exactly.
"""

from __future__ import annotations

from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

MAX_BYTES = 65_000


def _tokens(tokens: list[Token]) -> list[Any]:
    result: list[Any] = []
    for token in tokens:
        if token.meta:
            raise ValueError("unsupported Markdown metadata")
        # Inline containers duplicate source spelling in content. Their children
        # retain decoded text, link targets, formatting, and hard/soft breaks.
        value = (
            token.type,
            token.tag,
            token.nesting,
            token.attrs,
            token.hidden,
            token.info,
            "" if token.children is not None else token.content,
            _tokens(token.children) if token.children is not None else None,
        )
        result.append(value)
    return result


def descriptions_match(expected: str, observed: object) -> bool:
    """Allow presentation aliases while preserving parsed content and structure."""
    if not isinstance(observed, str):
        return False
    if any(
        len(value.encode("utf-8")) > MAX_BYTES or "\x00" in value for value in (expected, observed)
    ):
        return False
    if expected == observed:
        return True
    parser = MarkdownIt("commonmark", {"maxNesting": 20})
    try:
        parsed = []
        for value in (expected, observed):
            environment: dict[str, Any] = {}
            tokens = parser.parse(value, environment)
            # Reference definitions can disappear from the token stream. Do not
            # accept a changed body containing them, including unused definitions.
            if environment:
                return False
            parsed.append(_tokens(tokens))
        return parsed[0] == parsed[1]
    except (ValueError, RecursionError):
        return False
