"""Tests for the provider-agnostic LLM client.

Unit tests mock the OpenAI client and make no network calls. One live smoke test
runs only when GROQ_API_KEY is present.
"""

import os
from types import SimpleNamespace
from unittest import mock

import pytest

from pandavas.llm import LLMClient

# A real, currently-available small Groq model id, used only by the live smoke
# test. Update if Groq deprecates it.
SMOKE_MODEL = "llama-3.1-8b-instant"


def _fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_groq_picks_base_url_and_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with mock.patch("pandavas.llm.openai.OpenAI") as MockOpenAI:
        LLMClient(provider="groq")
    MockOpenAI.assert_called_once_with(
        api_key="test-key", base_url="https://api.groq.com/openai/v1"
    )


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError):
        LLMClient(provider="not-a-provider")


def test_missing_key_raises_runtime_error_naming_env_var(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc:
        LLMClient(provider="groq")
    assert "GROQ_API_KEY" in str(exc.value)


def test_complete_passes_model_temperature_and_returns_content(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with mock.patch("pandavas.llm.openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _fake_response("hi there")
        client = LLMClient(provider="groq")
        out = client.complete(
            [{"role": "user", "content": "x"}], model="some-model", temperature=0.0
        )

    assert out == "hi there"
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "some-model"
    assert kwargs["temperature"] == 0.0
    assert "response_format" not in kwargs


def test_complete_json_mode_sets_response_format(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with mock.patch("pandavas.llm.openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _fake_response("{}")
        client = LLMClient(provider="groq")
        client.complete(
            [{"role": "user", "content": "x"}], model="some-model", json_mode=True
        )

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="no GROQ_API_KEY")
def test_live_groq_smoke():
    client = LLMClient(provider="groq")
    out = client.complete(
        [{"role": "user", "content": "reply with the single word: ok"}],
        model=SMOKE_MODEL,
        max_tokens=5,
    )
    assert isinstance(out, str) and out.strip()
