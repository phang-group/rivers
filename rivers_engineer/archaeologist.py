"""
archaeologist.py — LLM One: The Archaeologist
===============================================
Technology: Anthropic SDK (claude-sonnet-4-6)

Why two separate LLM calls instead of one:
  A single LLM asked to both "describe the system" and "critique it" will
  produce hedged, conflicted output. Separating the roles means:
    - The Archaeologist can be thorough and descriptive without second-guessing
    - The Critic can be aggressive without needing to also explain everything
  This mirrors good human review processes: one person documents, another audits.

Why claude-sonnet-4-6:
  Sonnet provides the right balance of analytical depth and speed for this use
  case. Opus would give richer output but costs 5x more and is slower — for a
  CLI tool developers run regularly, latency and cost matter.

Why streaming is NOT used here:
  We want the complete response before passing it to the Critic. Streaming would
  require buffering the entire response anyway before the next step. We use
  max_tokens=8000 to allow rich, complete chapters.
"""

import time
from typing import Dict, Any

import anthropic

from .prompts import archaeologist_system, archaeologist_user

# Model: use the latest Sonnet. Adjust here to swap to Opus for richer analysis.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Max tokens for the Archaeologist's response.
# 8000 tokens allows roughly 6,000 words — enough for 4 detailed chapters.
MAX_TOKENS = 8000


def excavate(
    analysis: Dict[str, Any],
    depth: str = "full",
    api_key: str = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Send the analyzed codebase context to LLM One (The Archaeologist) and
    return the complete architectural story (Chapters 1–4).

    Args:
        analysis:  The structured analysis dict from analyzer.analyze()
        depth:     "full" (send file contents) or "summary" (structure only)
        api_key:   Anthropic API key
        model:     Claude model string

    Returns:
        The Archaeologist's full markdown response (Chapters 1–4 + Tech Map)
    """
    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = archaeologist_system()
    user_prompt = archaeologist_user(analysis, depth=depth)

    response = _call_with_retry(
        client=client,
        model=model,
        system=system_prompt,
        user=user_prompt,
        max_tokens=MAX_TOKENS,
        label="The Archaeologist",
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
    Call the Claude API with exponential backoff retry on rate limit errors.

    Why retry logic here:
      The Archaeologist is the first of two LLM calls. If the API is rate-limited
      (429) or has a transient error (529), we retry rather than fail the whole
      analysis. The backoff gives the API time to recover.
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
            wait_time = (2 ** attempt) * 10  # 10s, 20s, 40s
            if attempt < max_retries - 1:
                time.sleep(wait_time)

        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503):  # overloaded / service unavailable
                last_error = e
                wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
            else:
                raise  # Don't retry on other errors (400, 401, etc.)

        except anthropic.APIConnectionError as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(5)

    raise RuntimeError(
        f"{label} failed after {max_retries} attempts. Last error: {last_error}"
    )
