from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.database import get_image, update_image

logger = logging.getLogger(__name__)

router = APIRouter()


class QueueBatchRequest(BaseModel):
    ids: list[int] = []
    action: str  # "add", "remove", or "clear"


@router.post("/images/{image_id}/queue")
async def api_toggle_queue(request: Request, image_id: int):
    """Toggle an image's queue status."""
    db = request.app.state.db
    image = await get_image(db, image_id)
    if not image:
        raise HTTPException(404, "Image not found")

    new_value = 0 if image.get("in_queue") else 1
    await update_image(db, image_id, in_queue=new_value)
    return {"image_id": image_id, "in_queue": bool(new_value)}


@router.post("/images/queue-batch")
async def api_queue_batch(request: Request, body: QueueBatchRequest):
    """Batch queue operations: add, remove, or clear."""
    db = request.app.state.db
    action = body.action.lower()

    if action == "clear":
        cursor = await db.execute("UPDATE images SET in_queue = 0 WHERE in_queue = 1")
        await db.commit()
        return {"updated": cursor.rowcount}

    if action not in ("add", "remove"):
        raise HTTPException(400, "Action must be 'add', 'remove', or 'clear'")

    if not body.ids:
        return {"updated": 0}

    value = 1 if action == "add" else 0
    placeholders = ",".join("?" * len(body.ids))
    cursor = await db.execute(
        f"UPDATE images SET in_queue = ? WHERE id IN ({placeholders})",
        [value] + body.ids,
    )
    await db.commit()
    return {"updated": cursor.rowcount}
