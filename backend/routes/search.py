from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.search import search_images

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    use_llm: bool | None = None  # None = auto (use setting), False = force keyword


@router.post("/search")
async def api_search(request: Request, body: SearchRequest):
    """Execute a search query. Uses LLM interpretation when available."""
    db = request.app.state.db
    settings = request.app.state.settings
    ollama = request.app.state.ollama

    # None = auto (use LLM if configured), True/False = override
    if body.use_llm is None:
        use_llm = bool(settings.llm_model)
    else:
        use_llm = body.use_llm

    result = await search_images(
        db=db,
        query=body.query,
        ollama=ollama,
        use_llm=use_llm,
    )
    return result
