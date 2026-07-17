"""
API endpoints for item extraction, user registration, and authentication.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
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
            db_item.description = result.get("description")
            db_item.domain_source = result.get("domain_source")
            # "ok" -> COMPLETED; "no_data"/"fetch_error" -> FAILED so the app
            # never shows a COMPLETED item with empty fields.
            db_item.status = (
                "COMPLETED" if result.get("status") == "ok" else "FAILED"
            )
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
    current_user: User = Depends(get_current_user),
) -> Item:
    """Submit a product URL for extraction."""
    url = str(body.url)
    item = Item(original_url=url, user_id=current_user.id, status="PENDING")
    db.add(item)
    await db.commit()
    await db.refresh(item)
    background_tasks.add_task(_background_scraping_task, item.id, url)
    return item


@router.get(
    "/items/{item_id}",
    response_model=ItemResponse,
)
async def get_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    """Register a new user with a hashed password."""
    new_user = User(
        email=user_in.email,
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
    )
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


@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Authenticate a user and return a JWT access token."""
    stmt = select(User).where(User.username == form_data.username)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )
    token = create_access_token(str(user.id))
    return {"access_token": token, "token_type": "bearer"}
