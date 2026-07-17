"""
Wishlist Extractor API — FastAPI application entry point.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from poc.extractor import browser_manager  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm the shared headless browser on startup and close it on
    shutdown so scrapes don't pay the launch cost per request."""
    await browser_manager.start()
    try:
        yield
    finally:
        await browser_manager.stop()


app = FastAPI(
    title="Wishlist Extractor API",
    version="0.1.0",
    lifespan=lifespan,
)

from app.api.endpoints import router  # noqa: E402

app.include_router(router, prefix="/api/v1")
