"""Tests for the provider-agnostic LLM client.

Unit tests mock the OpenAI client and make no network calls. One live smoke test
runs only when GROQ_API_KEY is present.
"""

import os
from types import SimpleNamespace
from unittest import mock

import httpx
import openai
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


def _resp_with_usage(content, prompt=1, completion=2, total=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
        ),
    )


def test_complete_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    req = httpx.Request("POST", "http://test")
    calls = {"n": 0}

    def side_effect(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise openai.APITimeoutError(request=req)
        return _resp_with_usage("ok")

    with mock.patch("pandavas.llm.openai.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.side_effect = side_effect
        client = LLMClient(provider="groq", backoff_base_s=0)  # no real sleep
        out = client.complete([{"role": "user", "content": "x"}], model="m")

    assert out == "ok"
    assert calls["n"] == 3  # two transient failures, then success
    assert client.usage["total_tokens"] == 3
    assert client.usage["calls"] == 1


def test_complete_reraises_after_exhausting_retries(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    req = httpx.Request("POST", "http://test")

    def always_timeout(**kwargs):
        raise openai.APITimeoutError(request=req)

    with mock.patch("pandavas.llm.openai.OpenAI") as MockOpenAI:
        create = MockOpenAI.return_value.chat.completions.create
        create.side_effect = always_timeout
        client = LLMClient(provider="groq", max_retries=2, backoff_base_s=0)
        with pytest.raises(openai.APITimeoutError):
            client.complete([{"role": "user", "content": "x"}], model="m")

    assert create.call_count == 3  # max_retries + 1


def test_usage_accumulates_across_calls(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with mock.patch("pandavas.llm.openai.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = (
            _resp_with_usage("hi", prompt=10, completion=5, total=15)
        )
        client = LLMClient(provider="groq")
        client.complete([{"role": "user", "content": "x"}], model="m")
        client.complete([{"role": "user", "content": "y"}], model="m")

    assert client.usage["calls"] == 2
    assert client.usage["total_tokens"] == 30
    assert client.usage["prompt_tokens"] == 20


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="no GROQ_API_KEY")
def test_live_groq_smoke():
    client = LLMClient(provider="groq")
    out = client.complete(
        [{"role": "user", "content": "reply with the single word: ok"}],
        model=SMOKE_MODEL,
        max_tokens=5,
    )
    assert isinstance(out, str) and out.strip()
