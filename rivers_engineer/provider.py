"""
provider.py — PHANG AI Provider Abstraction
=============================================
Minimal provider-agnostic interface for Rivers Engineer.

Supports:
  RIVER_PROVIDER=deepseek   (default — cost-efficient, fast)
  RIVER_PROVIDER=anthropic  (high-end workflows, Opus/Sonnet)
  RIVER_PROVIDER=openai     (OpenAI-compatible endpoints)
  RIVER_PROVIDER=ollama     (local inference via Ollama)

Config via environment:
  RIVER_PROVIDER   — provider name (default: deepseek)
  RIVER_API_KEY    — API key for the provider
  RIVER_API_BASE   — override base URL (useful for Ollama, proxies)
  RIVER_MODEL      — override model name

Legacy support:
  ANTHROPIC_API_KEY — still accepted when RIVER_PROVIDER=anthropic

Design rule: minimal abstraction only.
One method: generate(system, user, max_tokens) -> str
One async method: agenerate(system, user, max_tokens) -> str
No plugin system. No registry. No abstract base classes.
Add providers by adding elif branches.
"""

import os
import time
from typing import Optional


# Provider defaults
_PROVIDER_DEFAULTS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "anthropic": {
        "base_url": None,  # SDK default
        "model": "claude-sonnet-4-6",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3",
    },
}


def get_provider_config(api_key: Optional[str] = None) -> dict:
    """
    Resolve provider config from environment + explicit key.
    Priority: explicit api_key arg > RIVER_API_KEY > ANTHROPIC_API_KEY (legacy)
    """
    provider = os.environ.get("RIVER_PROVIDER", "deepseek").lower()
    defaults = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["deepseek"])

    resolved_key = (
        api_key
        or os.environ.get("RIVER_API_KEY")
        or (os.environ.get("ANTHROPIC_API_KEY") if provider == "anthropic" else None)
    )
    resolved_model = os.environ.get("RIVER_MODEL") or defaults["model"]
    resolved_base = os.environ.get("RIVER_API_BASE") or defaults["base_url"]

    return {
        "provider": provider,
        "api_key": resolved_key,
        "model": resolved_model,
        "base_url": resolved_base,
    }


class AIProvider:
    """
    Minimal AI provider wrapper. Sync + async generate.
    All retry logic lives here so callers stay clean.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._cfg = get_provider_config(api_key)
        self._provider = self._cfg["provider"]

    @property
    def model(self) -> str:
        return self._cfg["model"]

    @property
    def provider(self) -> str:
        return self._cfg["provider"]

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 8000,
        label: str = "LLM",
        max_retries: int = 3,
    ) -> str:
        """Synchronous generate with retry."""
        if not self._cfg["api_key"]:
            raise ValueError(
                f"No API key found for provider '{self._provider}'.\n"
                f"Set RIVER_API_KEY or RIVER_PROVIDER + matching key env var."
            )

        if self._provider == "anthropic":
            return self._anthropic_generate(system, user, max_tokens, label, max_retries)
        else:
            return self._openai_compat_generate(system, user, max_tokens, label, max_retries)

    async def agenerate(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
    ) -> str:
        """Async generate (for FastAPI page_generator endpoint)."""
        if not self._cfg["api_key"]:
            raise ValueError(
                f"No API key found for provider '{self._provider}'."
            )

        if self._provider == "anthropic":
            return await self._anthropic_agenerate(system, user, max_tokens)
        else:
            return await self._openai_compat_agenerate(system, user, max_tokens)

    # ── Anthropic (native SDK) ────────────────────────────────────────────────

    def _anthropic_generate(self, system, user, max_tokens, label, max_retries):
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=self._cfg["api_key"])
        last_error = None
        for attempt in range(max_retries):
            try:
                msg = client.messages.create(
                    model=self._cfg["model"],
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return msg.content[0].text
            except _anthropic.RateLimitError as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep((2 ** attempt) * 10)
            except _anthropic.APIStatusError as e:
                if e.status_code in (529, 503):
                    last_error = e
                    if attempt < max_retries - 1:
                        time.sleep((2 ** attempt) * 5)
                else:
                    raise
            except _anthropic.APIConnectionError as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(5)
        raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_error}")

    async def _anthropic_agenerate(self, system, user, max_tokens):
        import anthropic as _anthropic
        client = _anthropic.AsyncAnthropic(api_key=self._cfg["api_key"])
        msg = await client.messages.create(
            model=self._cfg["model"],
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    # ── OpenAI-compatible (DeepSeek, OpenAI, Ollama) ─────────────────────────

    def _openai_compat_generate(self, system, user, max_tokens, label, max_retries):
        from openai import OpenAI, RateLimitError, APIConnectionError, APIStatusError
        client = OpenAI(
            api_key=self._cfg["api_key"],
            base_url=self._cfg["base_url"],
        )
        last_error = None
        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self._cfg["model"],
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return resp.choices[0].message.content
            except RateLimitError as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep((2 ** attempt) * 10)
            except APIStatusError as e:
                if e.status_code in (529, 503):
                    last_error = e
                    if attempt < max_retries - 1:
                        time.sleep((2 ** attempt) * 5)
                else:
                    raise
            except APIConnectionError as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(5)
        raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_error}")

    async def _openai_compat_agenerate(self, system, user, max_tokens):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=self._cfg["api_key"],
            base_url=self._cfg["base_url"],
        )
        resp = await client.chat.completions.create(
            model=self._cfg["model"],
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content
