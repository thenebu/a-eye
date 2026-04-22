"""Standalone Face Detection API — deploy on a GPU server for remote face recognition."""

from __future__ import annotations

import base64
import io
import logging

import face_recognition
import numpy as np
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="A-Eye Face API")


class DetectRequest(BaseModel):
    image: str  # base64-encoded image
    model: str = "hog"  # hog | cnn


class BBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class FaceResult(BaseModel):
    encoding: list[float]
    bbox: BBox


class DetectResponse(BaseModel):
    faces: list[FaceResult]


@app.post("/detect", response_model=DetectResponse)
async def detect_faces(body: DetectRequest):
    """Detect faces in a base64-encoded image, return encodings + bounding boxes."""
    if body.model not in ("hog", "cnn"):
        raise HTTPException(400, "model must be 'hog' or 'cnn'")

    try:
        image_bytes = base64.b64decode(body.image)
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        image_array = np.array(img)
    except Exception as exc:
        raise HTTPException(400, f"Invalid image: {exc}")

    locations = face_recognition.face_locations(image_array, model=body.model)
    if not locations:
        return DetectResponse(faces=[])

    encodings = face_recognition.face_encodings(image_array, known_face_locations=locations)

    faces = []
    for loc, enc in zip(locations, encodings):
        top, right, bottom, left = loc
        faces.append(FaceResult(
            encoding=enc.tolist(),
            bbox=BBox(x=left, y=top, w=right - left, h=bottom - top),
        ))

    logger.info("Detected %d face(s) using %s model", len(faces), body.model)
    return DetectResponse(faces=faces)


@app.get("/health")
async def health():
    return {"status": "ok", "model": "face_recognition"}
