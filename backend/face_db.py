from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import aiosqlite

from backend.faces import mark_cache_dirty

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Person CRUD
# ---------------------------------------------------------------------------

async def insert_person(
    db: aiosqlite.Connection,
    name: str,
    birthday: str | None = None,
    notes: str | None = None,
) -> int:
    cursor = await db.execute(
        "INSERT INTO persons (name, birthday, notes) VALUES (?, ?, ?)",
        (name, birthday, notes),
    )
    await db.commit()
    logger.info("Created person %d: %s", cursor.lastrowid, name)
    return cursor.lastrowid


async def update_person(
    db: aiosqlite.Connection,
    person_id: int,
    **kwargs: Any,
) -> None:
    allowed = {"name", "birthday", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = "CURRENT_TIMESTAMP"
    set_parts = []
    params: dict[str, Any] = {"_id": person_id}
    for k, v in fields.items():
        if v == "CURRENT_TIMESTAMP":
            set_parts.append(f"{k} = CURRENT_TIMESTAMP")
        else:
            set_parts.append(f"{k} = :{k}")
            params[k] = v
    sql = f"UPDATE persons SET {', '.join(set_parts)} WHERE id = :_id"
    await db.execute(sql, params)
    await db.commit()


async def delete_person(db: aiosqlite.Connection, person_id: int) -> None:
    # image_faces.person_id is ON DELETE SET NULL, so faces become unidentified
    await db.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    await db.commit()
    mark_cache_dirty()
    logger.info("Deleted person %d", person_id)


async def get_person(db: aiosqlite.Connection, person_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM persons WHERE id = ?", (person_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_persons(db: aiosqlite.Connection) -> list[dict]:
    """List all persons with face count and photo count."""
    cursor = await db.execute("""
        SELECT p.*,
            (SELECT COUNT(*) FROM image_faces f WHERE f.person_id = p.id) AS face_count,
            (SELECT COUNT(DISTINCT f.image_id) FROM image_faces f WHERE f.person_id = p.id) AS photo_count,
            (SELECT COUNT(*) FROM image_faces f WHERE f.person_id = p.id AND f.is_reference = 1) AS reference_count
        FROM persons p
        ORDER BY p.name
    """)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_person_by_name(db: aiosqlite.Connection, name: str) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM persons WHERE LOWER(name) = LOWER(?)", (name,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Image face CRUD
# ---------------------------------------------------------------------------

async def insert_image_face(
    db: aiosqlite.Connection,
    image_id: int,
    person_id: int | None,
    encoding: bytes | np.ndarray,
    bbox: tuple[int, int, int, int],
    match_distance: float | None = None,
    is_reference: bool = False,
    confirmed: bool = False,
) -> int:
    if isinstance(encoding, np.ndarray):
        encoding = encoding.tobytes()

    cursor = await db.execute(
        "INSERT INTO image_faces "
        "(image_id, person_id, encoding, bbox_x, bbox_y, bbox_w, bbox_h, "
        "match_distance, is_reference, confirmed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (image_id, person_id, encoding,
         bbox[0], bbox[1], bbox[2], bbox[3],
         match_distance, int(is_reference), int(confirmed)),
    )
    await db.commit()
    if is_reference:
        mark_cache_dirty()
    return cursor.lastrowid


async def get_image_faces(db: aiosqlite.Connection, image_id: int) -> list[dict]:
    """Get all detected faces for an image, with person info."""
    cursor = await db.execute("""
        SELECT f.*, p.name AS person_name, p.birthday AS person_birthday
        FROM image_faces f
        LEFT JOIN persons p ON f.person_id = p.id
        WHERE f.image_id = ?
        ORDER BY f.bbox_x
    """, (image_id,))
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # Don't send raw encoding bytes to the frontend
        d.pop("encoding", None)
        result.append(d)
    return result


async def get_face(db: aiosqlite.Connection, face_id: int) -> dict | None:
    cursor = await db.execute("""
        SELECT f.*, p.name AS person_name
        FROM image_faces f
        LEFT JOIN persons p ON f.person_id = p.id
        WHERE f.id = ?
    """, (face_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_person_images(
    db: aiosqlite.Connection,
    person_id: int,
    offset: int = 0,
    limit: int = 50,
) -> list[dict]:
    """Get all images containing a specific person."""
    cursor = await db.execute("""
        SELECT DISTINCT i.*
        FROM images i
        JOIN image_faces f ON i.id = f.image_id
        WHERE f.person_id = ?
        ORDER BY i.exif_date DESC, i.created_at DESC
        LIMIT ? OFFSET ?
    """, (person_id, limit, offset))
    rows = await cursor.fetchall()

    from backend.database import _row_to_dict
    return [_row_to_dict(r) for r in rows]


async def count_person_images(db: aiosqlite.Connection, person_id: int) -> int:
    cursor = await db.execute(
        "SELECT COUNT(DISTINCT image_id) FROM image_faces WHERE person_id = ?",
        (person_id,),
    )
    row = await cursor.fetchone()
    return row[0]


async def get_all_reference_encodings(
    db: aiosqlite.Connection,
) -> list[tuple[int, bytes]]:
    """Get all reference encodings as (person_id, encoding_bytes)."""
    cursor = await db.execute(
        "SELECT person_id, encoding FROM image_faces "
        "WHERE is_reference = 1 AND person_id IS NOT NULL"
    )
    return [(row[0], row[1]) for row in await cursor.fetchall()]


async def confirm_face(
    db: aiosqlite.Connection,
    face_id: int,
    person_id: int,
) -> None:
    """Assign/correct the person for a detected face."""
    await db.execute(
        "UPDATE image_faces SET person_id = ?, confirmed = 1 WHERE id = ?",
        (person_id, face_id),
    )
    await db.commit()


async def set_reference(
    db: aiosqlite.Connection,
    face_id: int,
    is_reference: bool,
) -> None:
    """Mark/unmark a face as a reference encoding for its person."""
    await db.execute(
        "UPDATE image_faces SET is_reference = ? WHERE id = ?",
        (int(is_reference), face_id),
    )
    await db.commit()
    mark_cache_dirty()


async def unidentify_face(db: aiosqlite.Connection, face_id: int) -> None:
    """Remove person assignment from a face."""
    await db.execute(
        "UPDATE image_faces SET person_id = NULL, confirmed = 0, "
        "is_reference = 0, match_distance = NULL WHERE id = ?",
        (face_id,),
    )
    await db.commit()
    mark_cache_dirty()


async def delete_image_faces(db: aiosqlite.Connection, image_id: int) -> int:
    """Delete all detected faces for an image (e.g. before re-detection)."""
    cursor = await db.execute(
        "DELETE FROM image_faces WHERE image_id = ?", (image_id,)
    )
    await db.commit()
    mark_cache_dirty()
    return cursor.rowcount


async def get_persons_for_image(db: aiosqlite.Connection, image_id: int) -> list[str]:
    """Get list of person names detected in an image (for filename generation)."""
    cursor = await db.execute("""
        SELECT DISTINCT p.name
        FROM image_faces f
        JOIN persons p ON f.person_id = p.id
        WHERE f.image_id = ?
        ORDER BY p.name
    """, (image_id,))
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_face_stats(db: aiosqlite.Connection) -> dict[str, int]:
    """Get face recognition statistics for the dashboard."""
    cursor = await db.execute("""
        SELECT
            (SELECT COUNT(*) FROM persons) AS person_count,
            (SELECT COUNT(*) FROM image_faces) AS total_faces,
            (SELECT COUNT(*) FROM image_faces WHERE person_id IS NOT NULL) AS identified_faces,
            (SELECT COUNT(*) FROM image_faces WHERE person_id IS NULL) AS unidentified_faces,
            (SELECT COUNT(*) FROM image_faces WHERE is_reference = 1) AS reference_faces
    """)
    row = await cursor.fetchone()
    return dict(row)
