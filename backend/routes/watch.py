from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/watch/start")
async def start_watch(request: Request):
    """Start filesystem watch mode."""
    watcher = request.app.state.watcher
    if watcher.is_running:
        return {"status": "already_running"}
    await watcher.start()
    return {"status": "started"}


@router.post("/watch/stop")
async def stop_watch(request: Request):
    """Stop filesystem watch mode."""
    watcher = request.app.state.watcher
    if not watcher.is_running:
        return {"status": "not_running"}
    await watcher.stop()
    return {"status": "stopped"}


@router.get("/watch/status")
async def watch_status(request: Request):
    """Current watch mode status."""
    watcher = request.app.state.watcher
    return {
        "running": watcher.is_running,
        "scan_in_progress": watcher.scan_in_progress,
    }
