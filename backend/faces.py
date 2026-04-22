from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np

import aiosqlite

logger = logging.getLogger(__name__)

# In-memory cache for reference encodings
_known_cache: list[tuple[int, str, np.ndarray]] | None = None  # (person_id, name, encoding)
_cache_dirty = True


def mark_cache_dirty() -> None:
    """Signal that reference encodings have changed and cache should reload."""
    global _cache_dirty
    _cache_dirty = True


async def load_known_encodings(
    db: aiosqlite.Connection,
) -> list[tuple[int, str, np.ndarray]]:
    """Load all reference face encodings from DB. Cached in memory.

    Returns list of (person_id, person_name, encoding_array).
    """
    global _known_cache, _cache_dirty

    if _known_cache is not None and not _cache_dirty:
        return _known_cache

    cursor = await db.execute(
        "SELECT f.person_id, p.name, f.encoding "
        "FROM image_faces f "
        "JOIN persons p ON f.person_id = p.id "
        "WHERE f.is_reference = 1 AND f.person_id IS NOT NULL"
    )
    rows = await cursor.fetchall()

    _known_cache = []
    for row in rows:
        person_id = row[0]
        name = row[1]
        enc = np.frombuffer(row[2], dtype=np.float64)
        if enc.shape == (128,):
            _known_cache.append((person_id, name, enc))

    _cache_dirty = False
    logger.info("Loaded %d reference face encoding(s) for %d person(s)",
                len(_known_cache),
                len({pid for pid, _, _ in _known_cache}))
    return _known_cache


def match_face(
    encoding: np.ndarray,
    known_encodings: list[tuple[int, str, np.ndarray]],
    tolerance: float = 0.6,
) -> tuple[int | None, str | None, float | None]:
    """Compare one face encoding against all known person encodings.

    Returns (person_id, person_name, distance) for the best match
    under the tolerance threshold, or (None, None, None) if no match.
    """
    if not known_encodings:
        return None, None, None

    known_encs = np.array([enc for _, _, enc in known_encodings])
    distances = np.linalg.norm(known_encs - encoding, axis=1)

    best_idx = int(np.argmin(distances))
    best_distance = float(distances[best_idx])

    if best_distance <= tolerance:
        person_id, name, _ = known_encodings[best_idx]
        return person_id, name, best_distance

    return None, None, best_distance


def calculate_age_at_date(birthday: str, photo_date: str) -> float | None:
    """Calculate a person's age at the time a photo was taken.

    Both dates should be YYYY-MM-DD strings.
    Returns age in years (float), or None if dates are invalid.
    """
    try:
        bd = date.fromisoformat(birthday)
        pd = date.fromisoformat(photo_date)
    except (ValueError, TypeError):
        return None

    if pd < bd:
        return None

    age = pd.year - bd.year
    if (pd.month, pd.day) < (bd.month, bd.day):
        age -= 1

    return float(age)


def age_to_date_range(
    birthday: str, age_min: int | None, age_max: int | None
) -> tuple[str | None, str | None]:
    """Convert an age range to a date range for photo searching.

    Returns (date_from, date_to) as YYYY-MM-DD strings.
    date_from = birthday + age_min years
    date_to = birthday + (age_max + 1) years - 1 day
    """
    try:
        bd = date.fromisoformat(birthday)
    except (ValueError, TypeError):
        return None, None

    date_from = None
    date_to = None

    if age_min is not None:
        try:
            date_from = bd.replace(year=bd.year + age_min).isoformat()
        except ValueError:
            # Feb 29 edge case
            date_from = bd.replace(year=bd.year + age_min, day=28).isoformat()

    if age_max is not None:
        try:
            date_to = (bd.replace(year=bd.year + age_max + 1) - timedelta(days=1)).isoformat()
        except ValueError:
            date_to = (bd.replace(year=bd.year + age_max + 1, day=28) - timedelta(days=1)).isoformat()

    return date_from, date_to
