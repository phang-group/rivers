"""
ui_server.py — Local FastAPI Server
=====================================
Technology: FastAPI + uvicorn

Why FastAPI over Flask:
  FastAPI is async-first, which means serving the static frontend and handling
  page generation API calls don't block each other. It also auto-generates
  OpenAPI docs at /docs — useful for developers inspecting the tool.
  Flask would work, but FastAPI is cleaner for an API-first design and is now
  the standard choice for new Python services.

Why uvicorn:
  uvicorn is the reference ASGI server for FastAPI. It starts in <100ms,
  handles WebSockets natively, and is stable enough for production workloads.
  For a local tool, we run it in a single worker (the default) — no need
  for gunicorn or process management.

Why serve the UI from FastAPI instead of a separate dev server:
  This is a CLI tool. Developers shouldn't need to run two processes.
  FastAPI serves the static index.html + handles API calls in one command.
  Zero-config, single port, single process.

Server routes:
  GET  /              → Serves ui/index.html
  GET  /api/report    → Returns the full JSON report data
  POST /api/generate-pages → LLM Three: generate wireframes for selected features
  GET  /health        → Health check
"""

import json
import mimetypes
import sys
from pathlib import Path
from typing import Optional, List

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Path to the bundled UI files (inside the package)
UI_DIR = Path(__file__).parent / "ui"


def start_server(
    json_file: Path,
    port: int = 3000,
    api_key: Optional[str] = None,
) -> None:
    """
    Create and start the FastAPI server. Blocks until Ctrl+C.

    Args:
        json_file: Path to the river-report-*.json sidecar file
        port:      Port to listen on
        api_key:   Anthropic API key for the Page Generator feature
    """
    app = _create_app(json_file=json_file, api_key=api_key)

    uvicorn.run(
        app,
        host="127.0.0.1",  # Local only — never expose to network
        port=port,
        log_level="warning",  # Suppress INFO-level request logs in normal use
        access_log=False,
    )


def _create_app(json_file: Path, api_key: Optional[str]) -> FastAPI:
    """
    Build the FastAPI application with all routes configured.
    Accepts json_file and api_key via closure to avoid global state.
    """
    app = FastAPI(
        title="River's Engineer UI",
        description="Local API server for the River's Engineer visual interface",
        version="0.1.0",
        docs_url="/api/docs",   # Move docs off root to keep / clean
        redoc_url=None,
    )

    # ── Load report data ──────────────────────────────────────────────────────
    try:
        report_data = json.loads(json_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Could not read report file {json_file}: {e}")

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def serve_ui():
        """Serve the main UI."""
        index_path = UI_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse(
                content="<h1>UI not found</h1><p>Run with a development build.</p>",
                status_code=404
            )
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/report")
    async def get_report():
        """
        Return the full report data. This is what the UI calls on load.
        Returns the entire JSON sidecar including book text, metadata,
        and ui_hints for rendering the architecture diagram.
        """
        return JSONResponse(content=report_data)

    @app.get("/api/report/metadata")
    async def get_metadata():
        """Return just project metadata (fast initial load)."""
        return JSONResponse(content=report_data.get("project", {}))

    # ── Page Generator ────────────────────────────────────────────────────────

    class PageGenerateRequest(BaseModel):
        features: List[str]  # list of feature/layer names to generate wireframes for

    @app.post("/api/generate-pages")
    async def generate_pages(request: PageGenerateRequest):
        """
        LLM Three: Generate wireframe HTML mockups for selected features.
        Called by the UI when the developer clicks "Generate Pages".

        Why this is a separate API call (not done during analysis):
          Page generation is expensive in both tokens and time. Doing it on-demand
          means the core analysis stays fast. The developer can choose which
          features to visualize.
        """
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Anthropic API key required for page generation. "
                       "Pass --api-key or set ANTHROPIC_API_KEY."
            )

        if not request.features:
            raise HTTPException(status_code=400, detail="No features specified")

        # Import here to avoid circular imports and keep startup fast
        from .page_generator import generate_wireframes

        try:
            wireframes = await generate_wireframes(
                features=request.features,
                report_data=report_data,
                api_key=api_key,
            )
            return JSONResponse(content={"wireframes": wireframes})

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/branches")
    async def list_branches():
        """
        List available river-report-*.json files in the same directory
        as the current report — enables the branch selector in the UI.
        """
        current_dir = json_file.parent
        reports = []
        for report_path in sorted(current_dir.glob("river-report-*.json"), reverse=True):
            try:
                data = json.loads(report_path.read_text(encoding="utf-8"))
                reports.append({
                    "file": str(report_path),
                    "project": data.get("project", {}).get("name", "unknown"),
                    "branch": data.get("project", {}).get("branch"),
                    "generated_at": data.get("generated_at"),
                })
            except Exception:
                pass
        return JSONResponse(content={"reports": reports})

    @app.get("/api/switch-report")
    async def switch_report(file: str):
        """
        Switch to a different report file. Returns the new report data.
        The UI calls this when a user selects a different branch/report.
        """
        target = Path(file)
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Report not found: {file}")
        try:
            new_data = json.loads(target.read_text(encoding="utf-8"))
            return JSONResponse(content=new_data)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app
