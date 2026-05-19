"""
archaeologist.py — LLM One: The Archaeologist
===============================================
The Archaeologist reads the codebase and produces Chapters 1-4 of The Book.

Provider-agnostic via provider.py.
Default: DeepSeek. Override with RIVER_PROVIDER env var.

Why two separate LLM calls instead of one:
  A single LLM asked to both "describe the system" and "critique it" produces
  hedged, conflicted output. Separating roles means the Archaeologist can be
  thorough without second-guessing, and the Critic can be aggressive without
  needing to also explain everything.
"""

from typing import Dict, Any

from .provider import AIProvider
from .prompts import archaeologist_system, archaeologist_user

MAX_TOKENS = 8000


def excavate(
    analysis: Dict[str, Any],
    depth: str = "full",
    api_key: str = None,
    model: str = None,
) -> str:
    """
    Send analyzed codebase context to The Archaeologist.
    Returns complete architectural story (Chapters 1-4 + Tech Map).

    Args:
        analysis:  Structured analysis dict from analyzer.analyze()
        depth:     "full" (file contents) or "summary" (structure only)
        api_key:   API key — passed to provider, falls back to env vars
        model:     Model override — falls back to RIVER_MODEL or provider default
    """
    provider = AIProvider(api_key=api_key)

    system_prompt = archaeologist_system()
    user_prompt = archaeologist_user(analysis, depth=depth)

    return provider.generate(
        system=system_prompt,
        user=user_prompt,
        max_tokens=MAX_TOKENS,
        label="The Archaeologist",
    )
