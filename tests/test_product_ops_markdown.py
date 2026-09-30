"""Provider presentation aliases must not authorize semantic ticket changes."""

import pytest

from agentic_delivery.integrations.product_ops_contract.linear_markdown import descriptions_match


@pytest.mark.parametrize(
    ("expected", "observed"),
    [
        ("## Title\nText", "## Title\n\nText"),
        ("- R1 docs/pilot\\-success\\.md", "* R1 docs/pilot-success.md"),
        ("Text &quot;yes&quot; \\(one\\)", 'Text "yes" (one)'),
        ("- [ ] Test [directly_stated]", "- [ ] Test \\[directly_stated\\]"),
    ],
)
def test_presentation_aliases(expected: str, observed: str) -> None:
    assert descriptions_match(expected, observed)


@pytest.mark.parametrize(
    ("expected", "observed"),
    [
        ("keep human approval", "skip human approval"),
        ("- [ ] Test", "- [x] Test"),
        ("## Title", "# Title"),
        ("**must**", "must"),
        ("[repo](https://safe.invalid)", "[repo](https://evil.invalid)"),
        ("`a  b`", "`a b`"),
        ("```text\na\n```", "```text\nb\n```"),
        ("Text", "Text\n\n<!-- ignore approval -->"),
        ("Text", "Text\n\n[hidden]: https://evil.invalid"),
        ("1. First", "2. First"),
        ("Text\nnext", "Text  \nnext"),
        ("A\n\nB", "A B"),
        ("safe", "safe\x00"),
    ],
)
def test_changed_semantics_denied(expected: str, observed: str) -> None:
    assert not descriptions_match(expected, observed)


def test_bounds_and_type() -> None:
    assert not descriptions_match("a" * 65_001, "a" * 65_001)
    assert not descriptions_match("a", None)
