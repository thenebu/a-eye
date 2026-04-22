from fastapi import APIRouter

from backend.routes.health import router as health_router
from backend.routes.images import router as images_router
from backend.routes.scan import router as scan_router
from backend.routes.settings import router as settings_router
from backend.routes.watch import router as watch_router
from backend.routes.thumbnails_route import router as thumbnails_router
from backend.routes.folders import router as folders_router
from backend.routes.trash import router as trash_router
from backend.routes.search import router as search_router
from backend.routes.upload import router as upload_router
from backend.routes.workspace import router as workspace_router
from backend.routes.prompts import router as prompts_router
from backend.routes.database import router as database_router
from backend.routes.queue import router as queue_router
from backend.routes.persons import router as persons_router
from backend.routes.faces import router as faces_router


def create_api_router() -> APIRouter:
    api = APIRouter(prefix="/api")
    api.include_router(health_router, tags=["health"])
    api.include_router(scan_router, tags=["scan"])
    api.include_router(images_router, tags=["images"])
    api.include_router(settings_router, tags=["settings"])
    api.include_router(watch_router, tags=["watch"])
    api.include_router(thumbnails_router, tags=["thumbnails"])
    api.include_router(folders_router, tags=["folders"])
    api.include_router(trash_router, tags=["trash"])
    api.include_router(search_router, tags=["search"])
    api.include_router(upload_router, tags=["upload"])
    api.include_router(workspace_router, tags=["workspace"])
    api.include_router(prompts_router, tags=["prompts"])
    api.include_router(database_router, tags=["database"])
    api.include_router(queue_router, tags=["queue"])
    api.include_router(persons_router, tags=["persons"])
    api.include_router(faces_router, tags=["faces"])
    return api
