from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class PullRequest(BaseModel):
    name: str


@router.get("/health")
async def health_check(request: Request):
    """App status + Ollama connection check."""
    ollama = request.app.state.ollama
    connected = await ollama.check_connection()

    models = []
    if connected:
        models = await ollama.list_models()

    model_names = [m.get("name", "?") for m in models]
    settings = request.app.state.settings

    return {
        "status": "ok",
        "ollama": {
            "connected": connected,
            "host": settings.ollama_host,
            "models": model_names,
            "vision_model": settings.vision_model,
            "llm_model": settings.llm_model or None,
        },
    }


@router.get("/models")
async def list_models(request: Request):
    """List available Ollama models, categorised by capability."""
    ollama = request.app.state.ollama
    return await ollama.list_models_by_capability()


@router.post("/models/pull")
async def pull_model(request: Request, body: PullRequest):
    """Stream model pull progress from Ollama (NDJSON)."""
    ollama = request.app.state.ollama
    model_name = body.name.strip()
    if not model_name:
        raise HTTPException(400, "Model name is required")
    return StreamingResponse(
        ollama.pull_model_stream(model_name),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
