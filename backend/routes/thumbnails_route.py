from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from backend.database import count_images, list_images
from backend.thumbnails import prune_orphaned_thumbnails

router = APIRouter()


@router.post("/thumbnails/prune")
async def prune_thumbnails(request: Request):
    """Delete orphaned thumbnails that don't match any known image."""
    db = request.app.state.db
    settings = request.app.state.settings
    data_dir = Path(settings.data_dir)

    # Get all valid image IDs
    total = await count_images(db)
    all_images = await list_images(db, offset=0, limit=total + 1)
    valid_ids = {img["id"] for img in all_images}

    pruned = await prune_orphaned_thumbnails(data_dir, valid_ids)
    return {"pruned": pruned}


@router.post("/thumbnails/clear")
async def clear_thumbnails(request: Request):
    """Delete ALL cached thumbnails. They will regenerate lazily."""
    settings = request.app.state.settings
    thumbs_dir = Path(settings.data_dir) / "thumbnails"

    count = 0
    if thumbs_dir.exists():
        for f in thumbs_dir.glob("*.jpg"):
            f.unlink()
            count += 1

    return {"cleared": count}
