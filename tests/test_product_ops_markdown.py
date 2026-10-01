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


@pytest.mark.parametrize(
    ("expected", "observed"),
    [
        ("Don&#x27;t change the owner&#x27;s filter.", "Don't change the owner's filter."),
        (
            "Return &lt;table&gt; when x &lt; 3 &amp; y &gt; 1.",
            "Return <table> when x < 3 & y > 1.",
        ),
        (
            "Repository: agentic-delivery-engineer\nHandoff: sha256:" + "d" * 64 + "\n\n"
            "- R1 Keep the user&#x27;s &lt;select&gt; value",
            "Repository: agentic-delivery-engineer\nHandoff: sha256:" + "d" * 64 + "\n\n"
            "- R1 Keep the user's <select> value",
        ),
    ],
)
def test_linear_entity_decoding_still_matches(expected: str, observed: str) -> None:
    # Linear stores decoded entities (PER-16); visible text is unchanged.
    assert descriptions_match(expected, observed)


@pytest.mark.parametrize(
    ("expected", "observed"),
    [
        ("Don&#x27;t change the filter.", "Do change the filter."),
        ("Return &lt;table&gt;", "Return <div>"),
        ("Keep x &lt; 3", "Keep x > 3"),
    ],
)
def test_entity_decoding_does_not_hide_changed_text(expected: str, observed: str) -> None:
    assert not descriptions_match(expected, observed)
