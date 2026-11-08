from __future__ import annotations

import webbrowser
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from vocalika import about, desktop


class LinkRequest(BaseModel):
    url: str


def create_about_router() -> APIRouter:
    router = APIRouter(prefix="/api/about", tags=["about"])

    @router.get("")
    async def summary() -> dict[str, Any]:
        # Reading every package's metadata takes a moment the first time.
        return await run_in_threadpool(about.summary)

    @router.get("/licenses/{source}/{name}")
    async def license_texts(source: str, name: str) -> dict[str, Any]:
        readers = {"python": about.license_texts, "launcher": about.launcher_license_texts}
        if source not in readers:
            raise HTTPException(status_code=404, detail=f"No license list called {source!r}.")
        try:
            texts = await run_in_threadpool(readers[source], name)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"{name} is not one of them.") from error
        return {"name": name, "texts": texts}

    @router.post("/open")
    def open_link(link: LinkRequest) -> dict[str, bool]:
        """Open a web link in the system browser, from the desktop app.

        Its window would otherwise leave the app for the page. Web links
        only: nothing that could start a program or open a local file.
        """
        if not desktop.is_desktop():
            raise HTTPException(status_code=404, detail="Opening links is a desktop app feature.")
        parsed = urlparse(link.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Only https links open.")
        webbrowser.open(link.url)
        return {"opened": True}

    return router
