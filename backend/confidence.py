from __future__ import annotations

import re

# Words that suggest the vision model is uncertain
HEDGE_WORDS = {
    "unclear", "possibly", "perhaps", "maybe", "might", "seems",
    "appears to be", "could be", "some kind of", "looks like it might",
    "hard to tell", "not sure", "difficult to determine", "blurry",
    "uncertain", "ambiguous",
}

# Generic filename terms that indicate low-quality output
GENERIC_TERMS = {
    "photo", "image", "picture", "untitled", "img", "pic",
    "screenshot", "file", "unnamed", "unknown",
}


def score_confidence(
    vision_description: str,
    proposed_filename: str,
    metadata: dict,
) -> float:
    """Score how confident we are in a proposed filename (0.0 to 1.0).

    Uses simple heuristics — no extra model needed.
    """
    score = 0.7  # Base score

    desc_lower = vision_description.lower()
    name_lower = proposed_filename.lower()
    word_count = len(vision_description.split())

    # Very short description → the model didn't have much to say
    if word_count < 5:
        score = 0.3
    elif word_count < 10:
        score -= 0.1

    # Hedge words in description → model is uncertain
    for hedge in HEDGE_WORDS:
        if hedge in desc_lower:
            score -= 0.2
            break  # Only penalize once

    # Generic terms in the proposed filename
    name_words = set(re.split(r"[-_\s]+", name_lower))
    if name_words & GENERIC_TERMS:
        score -= 0.3

    # No metadata at all + vague description → very low confidence
    has_date = bool(metadata.get("date"))
    has_gps = metadata.get("gps_lat") is not None
    if not has_date and not has_gps and word_count < 10:
        score -= 0.2

    # Bonus: rich metadata makes us more confident
    if has_date and has_gps:
        score += 0.1
    elif has_date or has_gps:
        score += 0.05

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, score))
