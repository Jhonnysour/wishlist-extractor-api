"""
Wishlist Extractor API — FastAPI application entry point.

Windows note: the headless tier (Playwright) must spawn the browser driver as a
subprocess, which only asyncio's ProactorEventLoop supports. Run the server with
``uvicorn main:app`` (or ``python main.py``) — do NOT pass ``--reload``: uvicorn's
reloader forces a SelectorEventLoop that can't spawn subprocesses, which disables
the headless tier (the API still boots and serves the static tier).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

# Prefer the ProactorEventLoop on Windows so Playwright can launch the browser.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger("wishlist")

from poc.extractor import browser_manager  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm the shared headless browser so scrapes don't pay the launch cost
    per request. A browser failure must never stop the API from booting: if it
    can't start (e.g. under an event loop that can't spawn subprocesses),
    extraction degrades to the static httpx tier instead of crashing."""
    try:
        await browser_manager.start()
    except Exception as exc:
        logger.warning(
            "Headless browser unavailable — extraction will use the static "
            "tier only. Cause: %s",
            exc,
        )
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


if __name__ == "__main__":
    import uvicorn

    # reload=False on purpose: --reload/reload=True forces a SelectorEventLoop on
    # Windows, which breaks the headless browser tier (see module docstring).
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
