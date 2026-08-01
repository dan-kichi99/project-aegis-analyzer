from unittest.mock import MagicMock, patch

import pytest

from app.client.base_client import BaseAIClient
from app.client.openai_client import OpenAIClient


@patch("app.client.openai_client.OpenAI")
def test_openai_client_inherits_base_ai_client(mock_openai_class):
    client = OpenAIClient(
        api_key="test-key",
        model="gpt-4o",
    )

    assert isinstance(client, BaseAIClient)
    mock_openai_class.assert_called_once_with(api_key="test-key")


@patch("app.client.openai_client.OpenAI")
def test_openai_client_passes_prompt_and_model_to_sdk(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "FLAG{test_openai_flag}"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    client = OpenAIClient(api_key="test-api-key-123", model="gpt-4o-mini")
    res = client.generate("Analyze RSA ciphertext")

    # 1. SDK に正しくモデルとプロンプトが渡されていること
    mock_client.chat.completions.create.assert_called_once_with(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Analyze RSA ciphertext"}],
    )

    # 2. 正しい文字列が返却されること
    assert res == "FLAG{test_openai_flag}"


def test_openai_client_requires_api_key():
    with pytest.raises(ValueError, match="API key must be provided."):
        OpenAIClient(api_key="")


@patch("app.client.openai_client.OpenAI")
def test_openai_client_raises_runtime_error_on_empty_choices(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices = []
    mock_client.chat.completions.create.return_value = mock_response

    client = OpenAIClient(api_key="test-key", model="gpt-4o")
    with pytest.raises(RuntimeError, match="OpenAI API returned an empty response."):
        client.generate("Test prompt")


@patch("app.client.openai_client.OpenAI")
def test_openai_client_raises_runtime_error_on_none_content(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    client = OpenAIClient(api_key="test-key", model="gpt-4o")
    with pytest.raises(
        RuntimeError, match="OpenAI API returned a choice with no content."
    ):
        client.generate("Test prompt")
