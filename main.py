"""
Wishlist Extractor API — FastAPI application entry point.
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

app = FastAPI(title="Wishlist Extractor API", version="0.1.0")

from app.api.endpoints import router  # noqa: E402

app.include_router(router, prefix="/api/v1")
