from __future__ import annotations

import asyncio
import base64
import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Max dimension for images sent to face detection (saves memory + time)
_FACE_MAX_PX = 1600
_FACE_JPEG_QUALITY = 90


@dataclass
class FaceDetection:
    encoding: np.ndarray          # 128-dim float64
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    person_id: int | None = None
    match_distance: float | None = None
    person_name: str | None = None


class FaceClient(ABC):
    """Abstract interface for face detection — local or remote."""

    @abstractmethod
    async def detect(self, image_path: Path) -> list[FaceDetection]:
        """Detect faces in an image, return encodings + bounding boxes."""

    async def health(self) -> dict:
        """Check if the backend is available."""
        return {"status": "ok"}

    async def close(self) -> None:
        pass


class LocalFaceClient(FaceClient):
    """Uses face_recognition (dlib) directly in-process."""

    def __init__(self, model: str = "hog") -> None:
        self.model = model
        self._fr = None  # lazy import

    def _get_fr(self):
        if self._fr is None:
            try:
                import face_recognition
                self._fr = face_recognition
            except ImportError:
                raise RuntimeError(
                    "face_recognition is not installed. "
                    "Install it or switch to face_backend='remote'."
                )
        return self._fr

    async def detect(self, image_path: Path) -> list[FaceDetection]:
        fr = self._get_fr()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._detect_sync, fr, image_path)

    def _detect_sync(self, fr, image_path: Path) -> list[FaceDetection]:
        image = fr.load_image_file(str(image_path))

        # Detect face locations (top, right, bottom, left format)
        locations = fr.face_locations(image, model=self.model)
        if not locations:
            return []

        # Compute 128-dim encodings for each detected face
        encodings = fr.face_encodings(image, known_face_locations=locations)

        detections = []
        for loc, enc in zip(locations, encodings):
            top, right, bottom, left = loc
            detections.append(FaceDetection(
                encoding=enc,
                bbox=(left, top, right - left, bottom - top),  # x, y, w, h
            ))

        logger.info("Local face detection: found %d face(s) in %s", len(detections), image_path.name)
        return detections

    async def health(self) -> dict:
        try:
            self._get_fr()
            return {"status": "ok", "backend": "local", "model": self.model}
        except RuntimeError as e:
            return {"status": "error", "backend": "local", "error": str(e)}


class RemoteFaceClient(FaceClient):
    """Sends images to an external Face API service via HTTP."""

    def __init__(self, api_url: str, model: str = "hog") -> None:
        self.api_url = api_url.rstrip("/")
        self.model = model
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def detect(self, image_path: Path) -> list[FaceDetection]:
        client = self._get_client()

        # Read and optionally resize image, then base64 encode
        img = Image.open(image_path)
        if max(img.size) > _FACE_MAX_PX:
            img.thumbnail((_FACE_MAX_PX, _FACE_MAX_PX), Image.LANCZOS)

        buf = io.BytesIO()
        img_format = "JPEG" if img.mode == "RGB" else "PNG"
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
            img_format = "JPEG"
        img.save(buf, format=img_format, quality=_FACE_JPEG_QUALITY)
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        resp = await client.post(
            f"{self.api_url}/detect",
            json={"image": image_b64, "model": self.model},
        )
        resp.raise_for_status()
        data = resp.json()

        detections = []
        for face in data.get("faces", []):
            enc = np.array(face["encoding"], dtype=np.float64)
            bbox_data = face["bbox"]
            detections.append(FaceDetection(
                encoding=enc,
                bbox=(bbox_data["x"], bbox_data["y"], bbox_data["w"], bbox_data["h"]),
            ))

        logger.info(
            "Remote face detection: found %d face(s) in %s",
            len(detections), image_path.name,
        )
        return detections

    async def health(self) -> dict:
        try:
            client = self._get_client()
            resp = await client.get(f"{self.api_url}/health")
            resp.raise_for_status()
            data = resp.json()
            data["backend"] = "remote"
            return data
        except Exception as e:
            return {"status": "error", "backend": "remote", "error": str(e)}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


def create_face_client(settings) -> FaceClient | None:
    """Factory: create the appropriate face client based on settings."""
    if not settings.face_recognition_enabled:
        return None
    if settings.face_backend == "remote":
        if not settings.face_api_url:
            logger.error("face_backend is 'remote' but face_api_url is empty")
            return None
        return RemoteFaceClient(
            api_url=settings.face_api_url,
            model=settings.face_detection_model,
        )
    return LocalFaceClient(model=settings.face_detection_model)
