"""
critic.py — LLM Two: The Critic
=================================
The Critic receives the Archaeologist's output and produces Chapter 5 + Reverse Path.

Provider-agnostic via provider.py.
Default: DeepSeek. Override with RIVER_PROVIDER env var.

Why the Critic is a separate LLM call:
  The Critic receives the Archaeologist's output as data, not prior context.
  This is deliberate: it evaluates findings without being anchored to the same
  framing. It can contradict, challenge, or reframe anything it receives.
"""

from typing import Dict, Any

from .provider import AIProvider
from .prompts import critic_system, critic_user

MAX_TOKENS = 6000


def critique(
    archaeology: str,
    analysis: Dict[str, Any],
    api_key: str = None,
    model: str = None,
) -> str:
    """
    Send the Archaeologist's analysis to The Critic.
    Returns Chapter 5 + The Full Reverse Path.

    Args:
        archaeology:  The Archaeologist's full response (Chapters 1-4)
        analysis:     Structured analysis dict (for raw dependency access)
        api_key:      API key — falls back to env vars
        model:        Model override — falls back to RIVER_MODEL or provider default
    """
    provider = AIProvider(api_key=api_key)

    system_prompt = critic_system()
    user_prompt = critic_user(archaeology, analysis)

    return provider.generate(
        system=system_prompt,
        user=user_prompt,
        max_tokens=MAX_TOKENS,
        label="The Critic",
    )
