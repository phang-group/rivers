"""
critic.py — LLM Two: The Critic
=================================
Technology: Anthropic SDK (claude-sonnet-4-6)

Why The Critic is a separate LLM call:
  The Critic receives the Archaeologist's output as data, not as its own prior
  context. This is deliberate: the Critic should evaluate the findings without
  being anchored to the same framing the Archaeologist used. It can contradict,
  challenge, or reframe anything it receives.

Why the Critic gets fewer tokens (6000 vs 8000):
  Chapter 5 + Reverse Path is more focused than Chapters 1-4. Conciseness is
  a feature of good critique — padding it doesn't add value.

Design note on LLM temperature:
  Both LLMs use the default temperature (1.0 for claude-sonnet). We don't lower
  temperature to 0 because architectural analysis benefits from a degree of
  creative synthesis. We don't raise it because we need consistent, structured output.
"""

import time
from typing import Dict, Any

import anthropic

from .prompts import critic_system, critic_user

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 6000


def critique(
    archaeology: str,
    analysis: Dict[str, Any],
    api_key: str = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Send the Archaeologist's analysis to LLM Two (The Critic) and return
    Chapter 5 + The Full Reverse Path.

    Args:
        archaeology:  The Archaeologist's full response string (Chapters 1-4)
        analysis:     The structured analysis dict (for raw dependency access)
        api_key:      Anthropic API key
        model:        Claude model string

    Returns:
        The Critic's full markdown response (Chapter 5 + Reverse Path)
    """
    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = critic_system()
    user_prompt = critic_user(archaeology, analysis)

    response = _call_with_retry(
        client=client,
        model=model,
        system=system_prompt,
        user=user_prompt,
        max_tokens=MAX_TOKENS,
        label="The Critic",
    )

    return response


def _call_with_retry(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    label: str,
    max_retries: int = 3,
) -> str:
    """
    Identical retry logic to archaeologist.py.

    Note: This is intentionally duplicated rather than shared via a utils module.
    Reason: Each LLM call may eventually need different retry parameters,
    error handling, or logging. Premature abstraction here would couple
    two independent concerns.
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[
                    {"role": "user", "content": user}
                ],
            )
            return message.content[0].text

        except anthropic.RateLimitError as e:
            last_error = e
            wait_time = (2 ** attempt) * 10
            if attempt < max_retries - 1:
                time.sleep(wait_time)

        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503):
                last_error = e
                wait_time = (2 ** attempt) * 5
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
            else:
                raise

        except anthropic.APIConnectionError as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(5)

    raise RuntimeError(
        f"{label} failed after {max_retries} attempts. Last error: {last_error}"
    )
