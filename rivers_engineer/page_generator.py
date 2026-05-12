"""
page_generator.py — LLM Three: The Visualizer
================================================
Technology: Anthropic SDK (async), asyncio

Why async here (but not in archaeologist/critic):
  Page generation is called from a FastAPI endpoint, which runs in an async
  event loop. Using the async Anthropic client means we don't block the
  server's event loop while waiting for the LLM response — other API calls
  can still be served. The analyze pipeline (archaeologist + critic) runs
  synchronously in the CLI, so blocking is acceptable there.

Why generate wireframes per feature (not the whole app at once):
  1. Token efficiency: one full-app wireframe would hit context limits
  2. Quality: focused prompts produce better wireframes per screen
  3. UX: the UI can stream wireframes in as they're generated, one at a time

Design decision — HTML wireframes instead of React/SVG:
  The wireframes are rendered inside iframes in the UI. Self-contained HTML
  is the most portable format: no runtime needed, no module resolution,
  works offline, can be saved and shared.
"""

import asyncio
from typing import Dict, List, Any, Optional

import anthropic

from .prompts import visualizer_system, visualizer_user


DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS_PER_WIREFRAME = 2000


async def generate_wireframes(
    features: List[str],
    report_data: Dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> Dict[str, str]:
    """
    Generate wireframe HTML for each requested feature.

    Runs all wireframe generations concurrently using asyncio.gather —
    generating 5 wireframes takes ~the time of 1 instead of 5x.

    Args:
        features:    List of feature/layer names to generate wireframes for
        report_data: The full report JSON (for context about the project)
        api_key:     Anthropic API key
        model:       Claude model string

    Returns:
        Dict mapping feature name → wireframe HTML string
    """
    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Build a context summary to give the LLM project-specific details
    project = report_data.get("project", {})
    archaeology = report_data.get("book", {}).get("archaeology", "")
    layers = report_data.get("ui_hints", {}).get("layers", [])

    # Map layer names for context lookup
    layer_names = [layer.get("name", "") for layer in layers]

    # Generate all wireframes concurrently
    tasks = [
        _generate_single_wireframe(
            client=client,
            model=model,
            feature_name=feature,
            project=project,
            layers=layer_names,
            archaeology_excerpt=_extract_relevant_section(archaeology, feature),
        )
        for feature in features
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build output dict, replacing errors with a fallback HTML
    wireframes = {}
    for feature, result in zip(features, results):
        if isinstance(result, Exception):
            wireframes[feature] = _error_wireframe(feature, str(result))
        else:
            wireframes[feature] = result

    return wireframes


async def _generate_single_wireframe(
    client: anthropic.AsyncAnthropic,
    model: str,
    feature_name: str,
    project: Dict[str, Any],
    layers: List[str],
    archaeology_excerpt: str,
) -> str:
    """
    Generate a single wireframe for one feature/screen.
    Returns raw HTML string.
    """
    # Determine connected layers (what this feature interacts with)
    connected_to = _infer_connections(feature_name, layers)

    # Build the feature description from project context
    feature_description = _build_feature_description(
        feature_name=feature_name,
        project=project,
        archaeology_excerpt=archaeology_excerpt,
    )

    system_prompt = visualizer_system()
    user_prompt = visualizer_user(
        feature_name=feature_name,
        feature_description=feature_description,
        connected_to=connected_to,
    )

    message = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS_PER_WIREFRAME,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if the LLM wrapped its HTML
    if raw.startswith("```"):
        lines = raw.split("\n")
        # Remove first line (```html or ```) and last line (```)
        inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        raw = "\n".join(inner_lines)

    return raw


def _extract_relevant_section(archaeology: str, feature_name: str) -> str:
    """
    Pull the most relevant paragraph from the archaeology text for a given feature.
    Simple heuristic: find the chapter that mentions the feature name,
    return the first 500 chars of that chapter.
    """
    feature_lower = feature_name.lower()
    chapters = archaeology.split("## Chapter")

    for chapter in chapters:
        if feature_lower in chapter.lower():
            # Return first 500 chars of this chapter
            return chapter[:500].strip()

    # Fallback: return first 500 chars of overall text
    return archaeology[:500].strip()


def _infer_connections(feature_name: str, all_layers: List[str]) -> List[str]:
    """
    Infer which other layers a given feature connects to,
    based on naming conventions.
    """
    feature_lower = feature_name.lower()
    connections = []

    layer_adjacency = {
        "entry point": ["core logic", "middleware", "router"],
        "core logic": ["data layer", "entry point", "output layer"],
        "data layer": ["core logic", "database", "cache"],
        "output layer": ["core logic", "client", "api"],
    }

    for key, neighbors in layer_adjacency.items():
        if key in feature_lower:
            for neighbor in neighbors:
                for layer in all_layers:
                    if neighbor in layer.lower():
                        connections.append(layer)
            break

    # If no specific match, connect to adjacent layers
    if not connections and all_layers:
        try:
            idx = next(
                i for i, l in enumerate(all_layers)
                if feature_name.lower() in l.lower()
            )
            if idx > 0:
                connections.append(all_layers[idx - 1])
            if idx < len(all_layers) - 1:
                connections.append(all_layers[idx + 1])
        except StopIteration:
            pass

    return connections[:3]  # Cap at 3 connections


def _build_feature_description(
    feature_name: str,
    project: Dict[str, Any],
    archaeology_excerpt: str,
) -> str:
    """
    Build a rich description of the feature for the wireframe prompt.
    """
    project_name = project.get("name", "this project")
    frameworks = ", ".join(project.get("frameworks", [])[:2]) or "unknown stack"
    lang = project.get("primary_language", "unknown language")

    return (
        f"In {project_name} (built with {lang}, {frameworks}), "
        f"this is the '{feature_name}' layer. "
        f"Context from the architectural analysis: {archaeology_excerpt}"
    )


def _error_wireframe(feature_name: str, error: str) -> str:
    """
    Return a fallback wireframe HTML when generation fails.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: monospace; padding: 20px; background: #fff8f8; color: #333; }}
  .error {{ border: 2px dashed #e74c3c; padding: 20px; border-radius: 4px; }}
  h3 {{ color: #e74c3c; margin: 0 0 10px 0; }}
  p {{ margin: 0; font-size: 12px; color: #666; }}
</style>
</head>
<body>
<div class="error">
  <h3>⚠ Could not generate wireframe</h3>
  <p><strong>Feature:</strong> {feature_name}</p>
  <p><strong>Error:</strong> {error}</p>
</div>
</body>
</html>"""
