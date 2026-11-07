from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from vocalika import desktop
from vocalika.storage import StorageError, StorageManager, describe, normalize, pick_folder


class FolderRequest(BaseModel):
    path: str


class StorageChange(BaseModel):
    path: str
    # True moves the current projects into the new folder; False only
    # switches to it (an existing library on another drive, say).
    move: bool


def create_settings_router(storage: StorageManager) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["settings"])

    @router.get("/app")
    def app_status() -> dict[str, bool]:
        # The page asks instead of guessing from the browser: the desktop
        # app's window is an ordinary web view on the same local server.
        return {"desktop": desktop.is_desktop()}

    @router.get("/storage")
    def storage_status() -> dict[str, Any]:
        return storage.status()

    @router.post("/storage/inspect")
    def inspect_folder(request: FolderRequest) -> dict[str, Any]:
        try:
            return describe(normalize(request.path))
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/storage/browse")
    async def browse_folder(request: FolderRequest | None = None) -> dict[str, str | None]:
        start = Path(request.path).expanduser() if request and request.path else None
        try:
            chosen = await run_in_threadpool(pick_folder, start)
        except (OSError, StorageError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"path": None if chosen is None else str(chosen)}

    @router.put("/storage")
    async def change_storage(change: StorageChange) -> dict[str, Any]:
        try:
            return await run_in_threadpool(storage.relocate, change.path, move=change.move)
        except StorageError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OSError as error:
            raise HTTPException(
                status_code=422,
                detail=f"The projects could not be moved, and are still where they were: {error}",
            ) from error

    return router
