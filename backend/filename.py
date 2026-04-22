from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def sanitize_filename(name: str, max_len: int = 120, case: str = "lower") -> str:
    """Clean a string into a safe, readable filename (no extension).

    - Normalizes unicode → ASCII approximations
    - Strips everything except letters, numbers, hyphens, underscores
    - Collapses runs of hyphens/underscores
    - Applies case transform
    - Truncates to max_len
    """
    # Unicode → ASCII approximation (e.g. "ü" → "u")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")

    # Replace common separators with hyphens
    name = re.sub(r"[\s,./\\]+", "-", name)

    # Strip everything except alphanumeric, hyphens, underscores
    name = re.sub(r"[^a-zA-Z0-9\-_]", "", name)

    # Collapse runs of hyphens/underscores
    name = re.sub(r"[-_]{2,}", "-", name)

    # Strip leading/trailing hyphens and underscores
    name = name.strip("-_")

    # Apply case
    if case == "lower":
        name = name.lower()
    elif case == "title":
        # Title-case each word (split on hyphens/underscores)
        name = re.sub(r"(?<=[-_])\w|^\w", lambda m: m.group().upper(), name.lower())

    # Truncate — but try to break on a hyphen/underscore to avoid chopping words
    if len(name) > max_len:
        truncated = name[:max_len]
        last_sep = max(truncated.rfind("-"), truncated.rfind("_"))
        if last_sep > max_len // 2:
            truncated = truncated[:last_sep]
        name = truncated.rstrip("-_")

    return name or "unnamed"


def render_template(
    template: str,
    date: str | None = None,
    location: str | None = None,
    description: str = "",
    camera: str | None = None,
    persons: str | None = None,
) -> str:
    """Render a filename template with available values.

    Template placeholders: {date}, {location}, {description}, {camera}, {persons}
    Missing values are omitted (and their surrounding separators cleaned up).
    """
    replacements = {
        "{date}": date or "",
        "{location}": location or "",
        "{description}": description,
        "{camera}": camera or "",
        "{persons}": persons or "",
    }

    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    # Clean up orphaned separators from missing values
    # e.g. "{date}_{description}" with no date → "_some-description" → "some-description"
    result = re.sub(r"^[_\-]+", "", result)
    result = re.sub(r"[_\-]+$", "", result)
    result = re.sub(r"[_\-]{2,}", "_", result)

    return result or description or "unnamed"


def ensure_unique(target_path: Path) -> Path:
    """If target_path already exists, append _2, _3, etc. until it's unique."""
    if not target_path.exists():
        return target_path

    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent

    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
