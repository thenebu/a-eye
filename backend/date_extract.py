from __future__ import annotations

import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

# -- Month name lookup --------------------------------------------------------

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Alternation pattern: longest names first to avoid partial matches
_MONTH_PATTERN = "|".join(sorted(_MONTH_NAMES.keys(), key=len, reverse=True))

# -- Tier 1: Full date patterns (most specific) ------------------------------

_FULL_DATE_PATTERNS = [
    # ISO: 2024-06-15
    re.compile(r"\b((?:19|20)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b"),
    # DD/MM/YYYY: 15/06/2024
    re.compile(r"\b(0?[1-9]|[12]\d|3[01])/(0?[1-9]|1[0-2])/((?:19|20)\d{2})\b"),
    # "June 15, 2024" or "June 15 2024"
    re.compile(
        rf"\b({_MONTH_PATTERN})\s+(0?[1-9]|[12]\d|3[01]),?\s+((?:19|20)\d{{2}})\b",
        re.IGNORECASE,
    ),
    # "15 June 2024" or "15th June 2024"
    re.compile(
        rf"\b(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})\s+((?:19|20)\d{{2}})\b",
        re.IGNORECASE,
    ),
]

# -- Tier 2: Month + year patterns (medium specificity) ----------------------

_MONTH_YEAR_PATTERNS = [
    # "June 2024" or "Jun 2024"
    re.compile(
        rf"\b({_MONTH_PATTERN})\s+((?:19|20)\d{{2}})\b",
        re.IGNORECASE,
    ),
    # ISO partial: 2024-06
    re.compile(r"\b((?:19|20)\d{2})-(0[1-9]|1[0-2])\b"),
    # 06/2024
    re.compile(r"\b(0?[1-9]|1[0-2])/((?:19|20)\d{2})\b"),
]

# -- Tier 3: Year only (least specific) --------------------------------------

_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")


# -- Validation ---------------------------------------------------------------

def _validate_date(year: int, month: int, day: int) -> str | None:
    """Return YYYY-MM-DD string if the date is valid, else None."""
    try:
        d = date(year, month, day)
        # Reject dates more than 1 year in the future
        if d.year > date.today().year + 1:
            return None
        return d.isoformat()
    except ValueError:
        return None


# -- Pattern-specific parsers -------------------------------------------------

def _parse_full_date(pattern_index: int, m: re.Match) -> str | None:
    """Parse a full date match based on which pattern matched."""
    if pattern_index == 0:
        # ISO: 2024-06-15 → (year, month, day)
        return _validate_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif pattern_index == 1:
        # DD/MM/YYYY → (day, month, year)
        return _validate_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    elif pattern_index == 2:
        # "June 15, 2024" → (month_name, day, year)
        month = _MONTH_NAMES.get(m.group(1).lower())
        if month:
            return _validate_date(int(m.group(3)), month, int(m.group(2)))
    elif pattern_index == 3:
        # "15 June 2024" → (day, month_name, year)
        month = _MONTH_NAMES.get(m.group(2).lower())
        if month:
            return _validate_date(int(m.group(3)), month, int(m.group(1)))
    return None


def _parse_month_year(pattern_index: int, m: re.Match) -> str | None:
    """Parse a month+year match, defaulting to day 1."""
    if pattern_index == 0:
        # "June 2024" → (month_name, year)
        month = _MONTH_NAMES.get(m.group(1).lower())
        if month:
            return _validate_date(int(m.group(2)), month, 1)
    elif pattern_index == 1:
        # ISO partial: 2024-06 → (year, month)
        return _validate_date(int(m.group(1)), int(m.group(2)), 1)
    elif pattern_index == 2:
        # 06/2024 → (month, year)
        return _validate_date(int(m.group(2)), int(m.group(1)), 1)
    return None


# -- Core search function ----------------------------------------------------

def _search_text_for_date(text: str) -> tuple[str, str] | None:
    """Search text for date patterns. Returns (YYYY-MM-DD, tier_name) or None."""
    # Tier 1: Full dates
    for i, pat in enumerate(_FULL_DATE_PATTERNS):
        m = pat.search(text)
        if m:
            parsed = _parse_full_date(i, m)
            if parsed:
                return parsed, "full_date"

    # Tier 2: Month + year
    for i, pat in enumerate(_MONTH_YEAR_PATTERNS):
        m = pat.search(text)
        if m:
            parsed = _parse_month_year(i, m)
            if parsed:
                return parsed, "month_year"

    # Tier 3: Year only
    matches = _YEAR_PATTERN.findall(text)
    if matches:
        unique_years = list(dict.fromkeys(matches))
        if len(unique_years) == 1:
            year = int(unique_years[0])
            result = _validate_date(year, 1, 1)
            if result:
                return result, "year_only"
        else:
            logger.debug(
                "Multiple year-only matches found (%s), skipping as ambiguous",
                ", ".join(unique_years),
            )

    return None


# -- Public API ---------------------------------------------------------------

def extract_date_from_text(
    vision_description: str,
    ai_tags: list[str],
    processing_context: str | None = None,
) -> str | None:
    """Attempt to extract a date from AI-generated text.

    Scans processing_context first, then vision_description, then ai_tags.
    Returns a date string in YYYY-MM-DD format, or None.
    """
    sources: list[tuple[str, str]] = []
    if processing_context:
        sources.append(("context", processing_context))
    sources.append(("description", vision_description))
    sources.append(("tags", ", ".join(ai_tags)))

    for source_label, text in sources:
        if not text:
            continue

        result = _search_text_for_date(text)
        if result:
            extracted_date, tier = result
            logger.info(
                "Extracted date %s from %s (tier: %s)",
                extracted_date, source_label, tier,
            )
            return extracted_date

    return None
