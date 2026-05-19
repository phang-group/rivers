"""
page_generator.py — LLM Three: The Visualizer
================================================
Generates HTML wireframes for each architectural layer.

Provider-agnostic via provider.py.
Default: DeepSeek. Override with RIVER_PROVIDER env var.

Why async here (but not in archaeologist/critic):
  Page generation is called from a FastAPI endpoint in an async event loop.
  Using the async path means we don't block the server while waiting for LLM
  responses — other API calls can still be served.

Why wireframes per feature (not whole app at once):
  1. Token efficiency: one full-app wireframe would hit context limits
  2. Quality: focused prompts produce better per-screen wireframes
  3. UX: the UI can stream wireframes in as they arrive
"""

import asyncio
from typing import Dict, List, Any, Optional

from .provider import AIProvider
from .prompts import visualizer_system, visualizer_user


MAX_TOKENS_PER_WIREFRAME = 2000


async def generate_wireframes(
    features: List[str],
    report_data: Dict[str, Any],
    api_key: str,
    model: str = None,
) -> Dict[str, str]:
    """
    Generate wireframe HTML for each requested feature concurrently.

    Args:
        features:    List of feature/layer names
        report_data: Full report JSON (for project context)
        api_key:     API key
        model:       Model override

    Returns:
        Dict mapping feature name -> wireframe HTML string
    """
    provider = AIProvider(api_key=api_key)

    project = report_data.get("project", {})
    archaeology = report_data.get("book", {}).get("archaeology", "")
    layers = report_data.get("ui_hints", {}).get("layers", [])
    layer_names = [layer.get("name", "") for layer in layers]

    tasks = [
        _generate_single_wireframe(
            provider=provider,
            feature_name=feature,
            project=project,
            layers=layer_names,
            archaeology_excerpt=_extract_relevant_section(archaeology, feature),
        )
        for feature in features
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    wireframes = {}
    for feature, result in zip(features, results):
        if isinstance(result, Exception):
            wireframes[feature] = _error_wireframe(feature, str(result))
        else:
            wireframes[feature] = result

    return wireframes


async def _generate_single_wireframe(
    provider: AIProvider,
    feature_name: str,
    project: Dict[str, Any],
    layers: List[str],
    archaeology_excerpt: str,
) -> str:
    connected_to = _infer_connections(feature_name, layers)
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

    raw = await provider.agenerate(
        system=system_prompt,
        user=user_prompt,
        max_tokens=MAX_TOKENS_PER_WIREFRAME,
    )
    raw = raw.strip()

    # Strip markdown code fences if the LLM wrapped its HTML
    if raw.startswith("```"):
        lines = raw.split("\n")
        inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        raw = "\n".join(inner_lines)

    return raw


def _extract_relevant_section(archaeology: str, feature_name: str) -> str:
    feature_lower = feature_name.lower()
    chapters = archaeology.split("## Chapter")
    for chapter in chapters:
        if feature_lower in chapter.lower():
            return chapter[:500].strip()
    return archaeology[:500].strip()


def _infer_connections(feature_name: str, all_layers: List[str]) -> List[str]:
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

    if not connections and all_layers:
        try:
            idx = next(i for i, l in enumerate(all_layers) if feature_name.lower() in l.lower())
            if idx > 0:
                connections.append(all_layers[idx - 1])
            if idx < len(all_layers) - 1:
                connections.append(all_layers[idx + 1])
        except StopIteration:
            pass

    return connections[:3]


def _build_feature_description(
    feature_name: str,
    project: Dict[str, Any],
    archaeology_excerpt: str,
) -> str:
    project_name = project.get("name", "this project")
    frameworks = ", ".join(project.get("frameworks", [])[:2]) or "unknown stack"
    lang = project.get("primary_language", "unknown language")
    return (
        f"In {project_name} (built with {lang}, {frameworks}), "
        f"this is the '{feature_name}' layer. "
        f"Context from the architectural analysis: {archaeology_excerpt}"
    )


def _error_wireframe(feature_name: str, error: str) -> str:
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
  <h3>Could not generate wireframe</h3>
  <p><strong>Feature:</strong> {feature_name}</p>
  <p><strong>Error:</strong> {error}</p>
</div>
</body>
</html>"""
