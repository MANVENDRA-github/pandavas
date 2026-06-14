"""Provider-agnostic LLM client for pandavas (P1 infrastructure).

A thin wrapper over the OpenAI SDK pointed at any OpenAI-compatible endpoint
(Groq, OpenRouter, Gemini's OpenAI-compatible API, or OpenAI itself). The caller
always supplies the model id explicitly — never defaulted, never "latest" — per
the reproducibility rule in docs/SPEC.md §8.

Out of scope here: retries, streaming, caching, and logging beyond exceptions.
"""

from __future__ import annotations

import os
from typing import Optional

import openai
from dotenv import load_dotenv

# Pick up .env at import so keys/provider are available without explicit setup.
load_dotenv()

# provider -> (base_url, api_key_env). base_url None means the SDK default (OpenAI).
PROVIDERS: dict[str, tuple[Optional[str], str]] = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "GEMINI_API_KEY",
    ),
    "openai": (None, "OPENAI_API_KEY"),
}

DEFAULT_PROVIDER = "groq"


class LLMClient:
    """OpenAI-compatible chat client selected by provider name."""

    def __init__(self, provider: Optional[str] = None):
        """Resolve provider, base URL, and API key, then build the SDK client.

        Args:
            provider: One of PROVIDERS. Defaults to env PANDAVAS_LLM_PROVIDER,
                else "groq".

        Raises:
            ValueError: If the provider is not recognised.
            RuntimeError: If the provider's API key env var is not set.
        """
        provider = provider or os.getenv("PANDAVAS_LLM_PROVIDER") or DEFAULT_PROVIDER
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown LLM provider {provider!r}; "
                f"valid values: {', '.join(sorted(PROVIDERS))}."
            )

        base_url, api_key_env = PROVIDERS[provider]
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing API key for provider {provider!r}: "
                f"set the {api_key_env} environment variable."
            )

        client_kwargs = {"api_key": api_key}
        if base_url is not None:
            client_kwargs["base_url"] = base_url

        self.provider = provider
        self.client = openai.OpenAI(**client_kwargs)

    def complete(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """Run a chat completion and return the first choice's text content.

        Args:
            messages: Chat messages in OpenAI format.
            model: Exact model id (required; never defaulted).
            temperature: Sampling temperature (default 0.0).
            max_tokens: Optional output token cap.
            json_mode: If True, request a JSON object response_format.

        Returns:
            The text content of the first choice.
        """
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
