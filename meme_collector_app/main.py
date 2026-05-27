"""Application factory."""

from __future__ import annotations

import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from meme_collector_app.core.config import get_settings
from meme_collector_app.db.models import init_db
from meme_collector_app.services.scheduler import create_scheduler_service
from meme_collector_app.web.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler_service = create_scheduler_service()
    app.state.scheduler_service = scheduler_service
    scheduler_service.start()
    try:
        yield
    finally:
        scheduler_service.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="Meme Collector Agent", lifespan=lifespan)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory="meme_collector_app/web/static"), name="static")
    return app


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "meme_collector_app.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
    )


if __name__ == "__main__":
    run()
