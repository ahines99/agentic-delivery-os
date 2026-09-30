# ADR-023: Preserve semantics across Linear Markdown serialization

Status: accepted and exercised with PER-8.

Linear rewrites harmless Markdown presentation during issue creation. PER-8 preserved its
approved content but changed heading spacing, bullet delimiters and escapes. Product Ops held
the original mutation outcome and reconciled the exact existing issue instead of writing again.

Delivery uses the same public `linear_markdown.py` module, vendored byte-for-byte, with locked
markdown-it-py 4.2.0. Only live description read-back uses CommonMark token comparison. Token
type, tag, nesting, attributes, text, code content/language, hidden paragraphs and line breaks
remain significant. Source coordinates and presentation delimiters do not. Changed reference
definitions, metadata, NUL and oversized descriptions fail closed. Unsupported rich-text
transformations remain held. Signed payloads, approval digests and file bytes never change.

Tests cover formatting aliases and changed words, code, links, checkboxes, headings, HTML,
reference definitions and hard breaks. Both admission and execution freshness checks apply
this comparison; ticket ID/title/team and independent signed capability checks remain required.
Parser upgrades need explicit regression review. Syntax equivalence is not execution authority.
