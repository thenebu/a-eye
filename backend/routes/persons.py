from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.face_db import (
    count_person_images,
    delete_person,
    get_person,
    get_person_images,
    insert_person,
    list_persons,
    update_person,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class PersonCreate(BaseModel):
    name: str
    birthday: str | None = None
    notes: str | None = None


class PersonUpdate(BaseModel):
    name: str | None = None
    birthday: str | None = None
    notes: str | None = None


@router.get("/persons")
async def api_list_persons(request: Request):
    db = request.app.state.db
    persons = await list_persons(db)
    return {"persons": persons}


@router.post("/persons")
async def api_create_person(request: Request, body: PersonCreate):
    db = request.app.state.db
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    person_id = await insert_person(
        db, name=body.name.strip(),
        birthday=body.birthday or None,
        notes=body.notes or None,
    )
    person = await get_person(db, person_id)
    return {"person": person}


@router.get("/persons/{person_id}")
async def api_get_person(request: Request, person_id: int):
    db = request.app.state.db
    person = await get_person(db, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    person["photo_count"] = await count_person_images(db, person_id)
    return {"person": person}


@router.put("/persons/{person_id}")
async def api_update_person(request: Request, person_id: int, body: PersonUpdate):
    db = request.app.state.db
    person = await get_person(db, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await update_person(db, person_id, **updates)
    person = await get_person(db, person_id)
    return {"person": person}


@router.delete("/persons/{person_id}")
async def api_delete_person(request: Request, person_id: int):
    db = request.app.state.db
    person = await get_person(db, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    await delete_person(db, person_id)
    return {"success": True}


@router.get("/persons/{person_id}/photos")
async def api_person_photos(
    request: Request, person_id: int, page: int = 1, limit: int = 50,
):
    db = request.app.state.db
    person = await get_person(db, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    offset = (page - 1) * limit
    images = await get_person_images(db, person_id, offset=offset, limit=limit)
    total = await count_person_images(db, person_id)
    return {"images": images, "total": total, "page": page}
