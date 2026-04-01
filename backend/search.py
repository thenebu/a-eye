from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiosqlite

from backend.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# System prompt for query interpretation
_SEARCH_SYSTEM_PROMPT = """\
You are a photo search assistant. Given a natural language query, generate a JSON search plan.

Searchable fields (all searched via keyword matching):
- vision_description: AI-generated text description of the photo content
- ai_tags: comma-separated keyword tags (e.g. "dog, beach, sunset, portrait")
- current_filename: descriptive filename (e.g. "golden_retriever_playing_on_sandy_beach")
- location_name: city/country name (often NULL — most photos lack GPS data)
- processing_context: user-provided context for AI processing (e.g. "holiday to Crete", "dog named Jax")

Filter fields (exact match only):
- exif_date: date in YYYY-MM-DD format
- quality_flags: image quality issues (blurry, accidental, overexposed, underexposed, low-resolution)
- status: processing status (pending, processing, proposed, renamed, skipped, error, trashed)

Rules for generating keywords:
1. Always include the literal search terms from the query
2. You MUST always add at least 2 synonyms or closely related terms
3. ONLY add place names or landmarks when the query is specifically about a location. Do NOT add location terms for non-location queries.
4. Generate 4-6 keywords total. Never return fewer than 4.
5. Do NOT put dates or years in the keywords array. Dates belong ONLY in date_from/date_to.
6. If the query is purely about a time period with no visual content (e.g. "photos from 2019"), return an EMPTY keywords array and only set date_from/date_to.

Example: "puppy" → keywords: ["puppy", "dog", "canine", "pet"], date_from: null
Example: "sunset beach" → keywords: ["sunset", "beach", "coast", "ocean", "shore"], date_from: null
Example: "photos from 2019" → keywords: [], date_from: "2019-01-01", date_to: "2019-12-31"
Example: "cats 2020" → keywords: ["cat", "cats", "kitten", "feline"], date_from: "2020-01-01", date_to: "2020-12-31"

Do NOT return any fields beyond the schema below.
Return ONLY this JSON, no explanation:
{
  "keywords": ["term1", "term2", "synonym1", "synonym2"],
  "date_from": "YYYY-MM-DD" or null,
  "date_to": "YYYY-MM-DD" or null,
  "quality_flags": [] or null,
  "status": null
}"""


async def search_images(
    db: aiosqlite.Connection,
    query: str,
    ollama: OllamaClient | None = None,
    use_llm: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """Execute a search query, using LLM interpretation if available.

    Returns {results: [...], mode: "llm"|"structured", query_interpretation: {...}}.
    """
    if use_llm and ollama and ollama.llm_model:
        return await _llm_search(db, query, ollama, limit)
    return await _structured_search(db, query, limit)


async def _llm_search(
    db: aiosqlite.Connection,
    query: str,
    ollama: OllamaClient,
    limit: int,
) -> dict[str, Any]:
    """Use the text LLM to interpret the query, then execute SQL."""
    # Ask the LLM to interpret the query
    prompt = (
        f"{_SEARCH_SYSTEM_PROMPT}\n\n"
        f"User query (between delimiters):\n---\n{query}\n---\n\n"
        "JSON:"
    )

    try:
        raw = await ollama._generate(
            model=ollama.llm_model, prompt=prompt,
            options={"temperature": 0},
        )
        interpretation = _parse_search_json(raw)

        # Merge any non-schema fields the LLM invented into keywords
        _SCHEMA_KEYS = {"keywords", "date_from", "date_to", "quality_flags", "status"}
        kws = list(interpretation.get("keywords", []))
        for key in list(interpretation.keys()):
            if key in _SCHEMA_KEYS:
                continue
            val = interpretation.pop(key)
            if isinstance(val, list):
                kws.extend(str(v) for v in val if v)
            elif isinstance(val, str) and val:
                kws.append(val)
        # Split compound keywords ("brown table" → "brown", "table")
        expanded = []
        for kw in kws:
            if " " in kw:
                expanded.extend(kw.split())
            else:
                expanded.append(kw)
        # Strip date-like tokens from keywords when date filters handle them
        if interpretation.get("date_from") or interpretation.get("date_to"):
            expanded = [kw for kw in expanded if not _is_date_token(kw)]
        interpretation["keywords"] = list(dict.fromkeys(expanded))  # dedupe, preserve order

        logger.info("Search interpretation for %r: %s", query, interpretation)
    except Exception as exc:
        logger.warning("LLM search interpretation failed: %s — falling back to structured", exc)
        result = await _structured_search(db, query, limit)
        result["mode"] = "llm_fallback"
        return result

    # Build SQL from the interpretation
    conditions, params = _build_sql_conditions(interpretation)
    keywords = interpretation.get("keywords", [])

    results = await _execute_search(db, conditions, params, limit)

    # Score results by weighted keyword match density
    scored = _score_results(results, keywords, query)

    return {
        "results": scored,
        "mode": "llm",
        "query_interpretation": interpretation,
    }


async def _structured_search(
    db: aiosqlite.Connection,
    query: str,
    limit: int,
) -> dict[str, Any]:
    """Simple keyword-based search without LLM."""
    # Split query into keywords
    keywords = [w.strip().lower() for w in query.split() if w.strip() and len(w.strip()) >= 2]

    if not keywords:
        return {"results": [], "mode": "structured", "query_interpretation": {"keywords": []}}

    interpretation = {"keywords": keywords}
    conditions, params = _build_sql_conditions(interpretation)

    results = await _execute_search(db, conditions, params, limit)
    scored = _score_results(results, keywords, query)

    return {
        "results": scored,
        "mode": "structured",
        "query_interpretation": interpretation,
    }


def _is_date_token(token: str) -> bool:
    """Return True if a token looks like a year or date (e.g. '2019', '2019-07')."""
    t = token.strip()
    if re.fullmatch(r"\d{4}", t):           # 4-digit year: 2019
        return True
    if re.fullmatch(r"\d{4}-\d{2}", t):     # year-month: 2019-07
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):  # full date: 2019-07-10
        return True
    return False


def _parse_search_json(raw: str) -> dict[str, Any]:
    """Parse JSON from the LLM response, handling markdown code blocks."""
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object within the text
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        # Last resort: extract keywords from the text
        logger.warning("Could not parse LLM search response as JSON")
        words = [w.strip().lower() for w in raw.split() if w.strip() and len(w.strip()) >= 2]
        return {"keywords": words[:10]}


def _build_sql_conditions(interpretation: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Build SQL WHERE conditions from the interpreted search plan."""
    conditions: list[str] = []
    params: dict[str, Any] = {}

    # Merge location and camera into keywords (they're often NULL, so AND filtering excludes too much)
    keywords = list(interpretation.get("keywords", []))
    if interpretation.get("location"):
        loc = interpretation["location"].lower()
        if loc not in [k.lower() for k in keywords]:
            keywords.append(loc)
    if interpretation.get("camera"):
        cam = interpretation["camera"].lower()
        if cam not in [k.lower() for k in keywords]:
            keywords.append(cam)

    if keywords:
        kw_conditions = []
        for i, kw in enumerate(keywords):
            key = f"kw_{i}"
            # Prefix matching: pad columns with spaces, LIKE '% word%' matches words starting with keyword
            kw_conditions.append(
                f"(' ' || LOWER(COALESCE(vision_description,'')) || ' ' LIKE :{key}"
                f" OR ' ' || LOWER(COALESCE(ai_tags,'')) || ' ' LIKE :{key}"
                f" OR ' ' || LOWER(COALESCE(location_name,'')) || ' ' LIKE :{key}"
                f" OR REPLACE(REPLACE(' ' || LOWER(COALESCE(current_filename,'')) || ' ', '_', ' '), '-', ' ') LIKE :{key}"
                f" OR ' ' || LOWER(COALESCE(processing_context,'')) || ' ' LIKE :{key})"
            )
            params[key] = f"% {kw.lower()}%"
        conditions.append(f"({' OR '.join(kw_conditions)})")

    if interpretation.get("date_from"):
        conditions.append("exif_date >= :date_from")
        params["date_from"] = interpretation["date_from"]

    if interpretation.get("date_to"):
        conditions.append("exif_date <= :date_to")
        params["date_to"] = interpretation["date_to"]

    if interpretation.get("quality_flags"):
        qf_conditions = []
        for i, flag in enumerate(interpretation["quality_flags"]):
            key = f"qf_{i}"
            qf_conditions.append(f"LOWER(quality_flags) LIKE :{key}")
            params[key] = f"%{flag.lower()}%"
        conditions.append(f"({' OR '.join(qf_conditions)})")

    if interpretation.get("status"):
        conditions.append("status = :status")
        params["status"] = interpretation["status"]

    # Exclude trashed by default (unless specifically searching for trashed)
    if interpretation.get("status") != "trashed":
        conditions.append("status != 'trashed'")

    return conditions, params


async def _execute_search(
    db: aiosqlite.Connection,
    conditions: list[str],
    params: dict[str, Any],
    limit: int,
) -> list[dict]:
    """Execute the search SQL and return results."""
    where = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE status != 'trashed'"
    sql = f"SELECT * FROM images {where} ORDER BY created_at DESC LIMIT :limit"
    params["limit"] = limit

    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()

    from backend.database import _row_to_dict
    return [_row_to_dict(r) for r in rows]


def _score_results(results: list[dict], keywords: list[str], query: str = "") -> list[dict]:
    """Score each result by weighted keyword match density and sort by score.

    Two-tier matching:
    - Exact word match (\\bkeyword\\b) → full weight
    - Prefix match (\\bkeyword) → 70% weight (catches plurals like flowers/dogs)

    Core query terms (words from the original query) are weighted 2x so that
    LLM-added synonyms don't dilute scores when they don't match.
    """
    PARTIAL_WEIGHT = 0.7

    if not keywords:
        for r in results:
            r["relevance_score"] = 0.5
            r["match_details"] = []
        return results

    query_terms = {w.lower() for w in query.split() if len(w) >= 2}

    # Pre-compile two patterns per keyword: exact word boundary and prefix-only
    kw_exact = {kw: re.compile(r"\b" + re.escape(kw.lower()) + r"\b") for kw in keywords}
    kw_prefix = {kw: re.compile(r"\b" + re.escape(kw.lower())) for kw in keywords}

    for r in results:
        score = 0.0
        max_score = 0.0
        match_info = []

        desc = (r.get("vision_description") or "").lower()
        tags = (r.get("ai_tags") or "")
        if isinstance(tags, list):
            tags = " ".join(tags).lower()
        else:
            tags = str(tags).lower()
        location = (r.get("location_name") or "").lower()
        filename = (r.get("current_filename") or "").lower().replace("_", " ").replace("-", " ")
        context = (r.get("processing_context") or "").lower()

        searchable = f"{desc} {tags} {location} {filename} {context}"

        for kw in keywords:
            weight = 2.0 if kw.lower() in query_terms else 1.0
            max_score += weight

            exact_pat = kw_exact[kw]
            prefix_pat = kw_prefix[kw]

            if exact_pat.search(searchable):
                # Full points for exact word match
                score += weight
                found_in = []
                if exact_pat.search(desc):
                    found_in.append("description")
                if exact_pat.search(tags):
                    found_in.append("tags")
                if exact_pat.search(location):
                    found_in.append("location")
                if exact_pat.search(filename):
                    found_in.append("filename")
                if exact_pat.search(context):
                    found_in.append("context")
                match_info.append({"keyword": kw, "found_in": found_in})
            elif prefix_pat.search(searchable):
                # Partial points for prefix match (e.g. "flower" matching "flowers")
                score += weight * PARTIAL_WEIGHT
                found_in = []
                if prefix_pat.search(desc):
                    found_in.append("description")
                if prefix_pat.search(tags):
                    found_in.append("tags")
                if prefix_pat.search(location):
                    found_in.append("location")
                if prefix_pat.search(filename):
                    found_in.append("filename")
                if prefix_pat.search(context):
                    found_in.append("context")
                match_info.append({"keyword": kw, "found_in": found_in, "partial": True})

        r["relevance_score"] = round(score / max_score, 2) if max_score > 0 else 0.0
        r["match_details"] = match_info

    # Sort by relevance descending, then by date
    results.sort(key=lambda r: (-r["relevance_score"], r.get("exif_date") or ""))
    return results
