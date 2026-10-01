"""Bounded CommonMark presentation comparison for Linear read-back only.

Never canonicalizes signed payloads, approval digests, or execution contents.
Unsupported constructs fail closed unless the original bytes match exactly.
"""

from __future__ import annotations

import html
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


def _visible_text(tokens: list[Any]) -> list[Any]:
    """Compare inline text by the characters a reader sees.

    Linear decodes HTML entities it receives (for example ``&#x27;`` and ``&lt;``) and can store
    the decoded characters as raw inline HTML. Text and inline-HTML runs are therefore joined and
    entity-decoded before comparison; every other token, link and format must still match.
    """
    result: list[Any] = []
    for token in tokens:
        kind, children = token[0], token[7]
        if kind in {"text", "html_inline"}:
            text = html.unescape(token[6])
            if result and result[-1][0] == "text":
                result[-1] = (*result[-1][:6], result[-1][6] + text, None)
            else:
                result.append(("text", "", 0, None, False, "", text, None))
            continue
        if children is not None:
            token = (*token[:7], _visible_text(children))
        result.append(token)
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
            parsed.append(_visible_text(_tokens(tokens)))
        return parsed[0] == parsed[1]
    except (ValueError, RecursionError):
        return False
