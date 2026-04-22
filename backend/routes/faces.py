from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from backend.database import get_image
from backend.face_db import (
    confirm_face,
    delete_image_faces,
    get_face,
    get_image_faces,
    insert_image_face,
    set_reference,
    unidentify_face,
)
from backend.faces import load_known_encodings, mark_cache_dirty, match_face

logger = logging.getLogger(__name__)

router = APIRouter()


class IdentifyBody(BaseModel):
    person_id: int


class SetReferenceBody(BaseModel):
    is_reference: bool = True


@router.get("/images/{image_id}/faces")
async def api_image_faces(request: Request, image_id: int):
    db = request.app.state.db
    image = await get_image(db, image_id)
    if not image:
        raise HTTPException(404, "Image not found")
    faces = await get_image_faces(db, image_id)
    return {"faces": faces, "image_id": image_id}


@router.post("/images/{image_id}/detect-faces")
async def api_detect_faces(request: Request, image_id: int):
    """Re-run face detection on a single image."""
    db = request.app.state.db
    face_client = getattr(request.app.state, "face_client", None)
    settings = request.app.state.settings

    if not face_client:
        raise HTTPException(400, "Face recognition is not enabled")

    image = await get_image(db, image_id)
    if not image:
        raise HTTPException(404, "Image not found")

    photos_dir = Path(settings.photos_dir)
    file_path = photos_dir / image["file_path"]
    if not file_path.exists():
        raise HTTPException(404, "Image file not found on disk")

    # Clear existing faces for this image
    await delete_image_faces(db, image_id)

    # Run detection
    detections = await face_client.detect(file_path)

    # Match against known persons
    known = await load_known_encodings(db)
    saved_faces = []
    for det in detections:
        pid, pname, dist = match_face(
            det.encoding, known, settings.face_match_tolerance,
        )
        face_id = await insert_image_face(
            db, image_id,
            person_id=pid,
            encoding=det.encoding,
            bbox=det.bbox,
            match_distance=dist,
        )
        saved_faces.append({
            "id": face_id,
            "person_id": pid,
            "person_name": pname,
            "match_distance": dist,
            "bbox_x": det.bbox[0],
            "bbox_y": det.bbox[1],
            "bbox_w": det.bbox[2],
            "bbox_h": det.bbox[3],
        })

    return {"faces": saved_faces, "count": len(saved_faces)}


@router.post("/faces/{face_id}/identify")
async def api_identify_face(request: Request, face_id: int, body: IdentifyBody):
    """Assign or correct the person for a detected face."""
    db = request.app.state.db
    face = await get_face(db, face_id)
    if not face:
        raise HTTPException(404, "Face not found")
    await confirm_face(db, face_id, body.person_id)
    return {"success": True}


@router.post("/faces/{face_id}/set-reference")
async def api_set_reference(request: Request, face_id: int, body: SetReferenceBody):
    """Mark/unmark a face as a reference encoding for its person."""
    db = request.app.state.db
    face = await get_face(db, face_id)
    if not face:
        raise HTTPException(404, "Face not found")
    if body.is_reference and not face["person_id"]:
        raise HTTPException(400, "Face must be assigned to a person before marking as reference")
    await set_reference(db, face_id, body.is_reference)
    return {"success": True}


@router.post("/faces/{face_id}/unidentify")
async def api_unidentify_face(request: Request, face_id: int):
    """Remove person assignment from a face."""
    db = request.app.state.db
    face = await get_face(db, face_id)
    if not face:
        raise HTTPException(404, "Face not found")
    await unidentify_face(db, face_id)
    return {"success": True}


@router.get("/faces/{face_id}/crop")
async def api_face_crop(request: Request, face_id: int):
    """Serve a cropped face thumbnail from the original image."""
    db = request.app.state.db
    settings = request.app.state.settings

    face = await get_face(db, face_id)
    if not face:
        raise HTTPException(404, "Face not found")

    image = await get_image(db, face["image_id"])
    if not image:
        raise HTTPException(404, "Image not found")

    photos_dir = Path(settings.photos_dir)
    file_path = photos_dir / image["file_path"]
    if not file_path.exists():
        raise HTTPException(404, "Image file not found")

    # Crop the face region with some padding
    try:
        img = Image.open(file_path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        x, y, w, h = face["bbox_x"], face["bbox_y"], face["bbox_w"], face["bbox_h"]
        # Add 30% padding around the face
        pad_w = int(w * 0.3)
        pad_h = int(h * 0.3)
        left = max(0, x - pad_w)
        top = max(0, y - pad_h)
        right = min(img.width, x + w + pad_w)
        bottom = min(img.height, y + h + pad_h)

        crop = img.crop((left, top, right, bottom))
        crop.thumbnail((200, 200), Image.LANCZOS)

        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/jpeg")
    except Exception as exc:
        logger.error("Failed to crop face %d: %s", face_id, exc)
        raise HTTPException(500, "Failed to generate face crop")


@router.post("/faces/rematch-all")
async def api_rematch_all(request: Request):
    """Re-run matching for all detected faces using current reference encodings."""
    db = request.app.state.db
    settings = request.app.state.settings

    mark_cache_dirty()
    known = await load_known_encodings(db)
    if not known:
        return {"matched": 0, "message": "No reference encodings available"}

    # Get all unconfirmed faces with encodings
    cursor = await db.execute(
        "SELECT id, encoding FROM image_faces WHERE confirmed = 0"
    )
    rows = await cursor.fetchall()

    matched = 0
    for row in rows:
        face_id = row[0]
        enc = np.frombuffer(row[1], dtype=np.float64)
        if enc.shape != (128,):
            continue

        pid, pname, dist = match_face(enc, known, settings.face_match_tolerance)
        if pid is not None:
            await db.execute(
                "UPDATE image_faces SET person_id = ?, match_distance = ? WHERE id = ?",
                (pid, dist, face_id),
            )
            matched += 1

    await db.commit()
    return {"matched": matched, "total": len(rows)}


@router.get("/faces/health")
async def api_face_health(request: Request):
    """Check face recognition backend health."""
    face_client = getattr(request.app.state, "face_client", None)
    if not face_client:
        return {"status": "disabled"}
    return await face_client.health()
