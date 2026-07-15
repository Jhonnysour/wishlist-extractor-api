"""
API endpoints for item extraction and retrieval.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.item import Item
from app.models.user import User
from app.schemas.item import ItemResponse, UrlInput
from app.schemas.user import UserCreate, UserResponse
from poc.extractor import extract_product_data

router = APIRouter()


async def _background_scraping_task(item_id: uuid.UUID, url: str) -> None:
    """Run the scraper and save results to the database."""
    from app.core.database import async_session

    async with async_session() as session:
        try:
            result = await extract_product_data(url)
            stmt = (
                select(Item)
                .where(Item.id == item_id)
            )
            db_item = (await session.execute(stmt)).scalar_one_or_none()
            if db_item is None:
                return
            db_item.title = result.get("title")
            db_item.price = result.get("price")
            db_item.images = result.get("images", [])
            db_item.status = "COMPLETED"
            await session.commit()
        except Exception:
            await session.rollback()
            stmt = select(Item).where(Item.id == item_id)
            db_item = (await session.execute(stmt)).scalar_one_or_none()
            if db_item is not None:
                db_item.status = "FAILED"
                await session.commit()


@router.post(
    "/items",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ItemResponse,
)
async def create_item(
    body: UrlInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Item:
    """Submit a product URL for extraction."""
    item = Item(original_url=body.url, status="PENDING")
    db.add(item)
    await db.commit()
    await db.refresh(item)
    background_tasks.add_task(_background_scraping_task, item.id, body.url)
    return item


@router.get(
    "/items/{item_id}",
    response_model=ItemResponse,
)
async def get_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Item:
    """Query the status and result of an extraction task."""
    stmt = select(Item).where(Item.id == item_id)
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found",
        )
    return item


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Register a new user."""
    new_user = User(**user_in.model_dump())
    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email o nombre de usuario ya está registrado",
        )
    await db.refresh(new_user)
    return new_user
