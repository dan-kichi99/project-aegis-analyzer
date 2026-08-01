import pytest

from app.config import Config


def test_config_loads_api_key_and_model_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")

    config = Config()

    assert config.openai_api_key == "test-secret-key"
    assert config.openai_model == "gpt-4o"


def test_config_default_model_when_not_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    config = Config()

    assert config.openai_api_key == "test-secret-key"
    assert config.openai_model == "gpt-4o-mini"


def test_config_raises_value_error_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY is not configured."):
        Config()


def test_config_raises_value_error_when_api_key_empty(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "   ")

    with pytest.raises(ValueError, match="OPENAI_API_KEY is not configured."):
        Config()
