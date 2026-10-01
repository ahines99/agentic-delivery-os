"""File-backed service credentials, without secret-bearing errors."""

import pytest

from agentic_delivery.config import secret


def test_multiline_key_is_loaded_from_file_without_terminal_newline(tmp_path, monkeypatch):
    key = "-----BEGIN OWNED TEST KEY-----\nowned-test-key-bytes\n-----END OWNED TEST KEY-----"
    path = tmp_path / "key.pem"
    path.write_text(key + "\n", encoding="utf-8")
    monkeypatch.delenv("OWNED_KEY", raising=False)
    monkeypatch.setenv("OWNED_KEY_FILE", str(path))
    assert secret("OWNED_KEY") == key


def test_explicit_environment_value_takes_precedence_over_file(monkeypatch):
    monkeypatch.setenv("OWNED_KEY", "owned-current-credential")
    monkeypatch.setenv("OWNED_KEY_FILE", "absent-key.pem")
    assert secret("OWNED_KEY") == "owned-current-credential"


@pytest.mark.parametrize("content", [None, b"\xffprivate-marker", b"short"])
def test_missing_invalid_or_short_secret_file_has_no_value_or_path_in_error(
    tmp_path, monkeypatch, content
):
    path = tmp_path / "private-marker.pem"
    if content is not None:
        path.write_bytes(content)
    monkeypatch.delenv("OWNED_KEY", raising=False)
    monkeypatch.setenv("OWNED_KEY_FILE", str(path))
    with pytest.raises(ValueError) as error:
        secret("OWNED_KEY")
    assert "OWNED_KEY" in str(error.value)
    assert "private-marker" not in str(error.value)
    assert str(error.value) != "short"


def test_explicit_empty_secret_is_not_replaced_by_a_file(tmp_path, monkeypatch):
    path = tmp_path / "key.pem"
    path.write_text("owned-otherwise-valid-key", encoding="utf-8")
    monkeypatch.setenv("OWNED_KEY", "")
    monkeypatch.setenv("OWNED_KEY_FILE", str(path))
    with pytest.raises(ValueError):
        secret("OWNED_KEY")
