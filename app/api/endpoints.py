"""
API endpoints for item extraction, user registration, and authentication.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.item import Item
from app.models.user import User
from app.schemas.item import ItemFromHtml, ItemResponse, ItemUpdate, UrlInput
from poc.extractor import extract_from_html, extract_product_data

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
    "/items",
    response_model=list[ItemResponse],
)
async def list_items(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    q: str | None = Query(
        default=None,
        description="Búsqueda por texto en el título y en la URL del producto.",
    ),
    purchased: bool | None = Query(
        default=None,
        description="true = solo comprados, false = solo pendientes, omitir = todos.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Item]:
    """The current user's wishlist, newest first, with optional search."""
    stmt = select(Item).where(Item.user_id == current_user.id)

    if purchased is not None:
        stmt = stmt.where(Item.purchased == purchased)

    if q:
        # Match the title OR the URL: a Hollister shirt whose title never says
        # "hollister" still matches because its URL is on hollisterco.com.
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(Item.title.ilike(pattern), Item.original_url.ilike(pattern))
        )

    stmt = stmt.order_by(Item.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all())


async def _get_owned_item(
    item_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> Item:
    """Fetch an item, 404ing unless it belongs to *current_user*.

    A single ownership gate for every by-id route — using 404 (not 403) so it
    doesn't even reveal that someone else's item exists.
    """
    stmt = select(Item).where(
        Item.id == item_id,
        Item.user_id == current_user.id,
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found",
        )
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
    return await _get_owned_item(item_id, db, current_user)


@router.patch(
    "/items/{item_id}",
    response_model=ItemResponse,
)
async def update_item(
    item_id: uuid.UUID,
    body: ItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    """Update an item: toggle ``purchased`` and/or curate its ``images``."""
    item = await _get_owned_item(item_id, db, current_user)
    data = body.model_dump(exclude_unset=True)

    if "purchased" in data:
        item.purchased = data["purchased"]

    if "images" in data:
        new_images = data["images"] or []
        # Curation only: the new list must be a re-ordering/subset of what we
        # already scraped, never arbitrary URLs the client made up.
        current = set(item.images or [])
        invalid = [url for url in new_images if url not in current]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Las imágenes deben ser un subconjunto de las actuales.",
            )
        item.images = new_images

    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/items/{item_id}/retry-from-html",
    response_model=ItemResponse,
)
async def retry_from_html(
    item_id: uuid.UUID,
    body: ItemFromHtml,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    """Re-extract an item from HTML captured by the client's WebView (Capa 0).

    For pages that never serve their price to a server-side scraper, the app
    loads the URL in a real browser and posts the rendered HTML here. Extraction
    is synchronous (no network fetch), so the updated item is returned directly.
    """
    item = await _get_owned_item(item_id, db, current_user)
    result = extract_from_html(body.html, item.original_url)
    item.title = result.get("title")
    item.price = result.get("price")
    item.images = result.get("images", [])
    item.description = result.get("description")
    item.domain_source = result.get("domain_source")
    item.status = "COMPLETED" if result.get("status") == "ok" else "FAILED"
    await db.commit()
    await db.refresh(item)
    return item


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Remove an item from the wishlist."""
    item = await _get_owned_item(item_id, db, current_user)
    await db.delete(item)
    await db.commit()


# Registration and login now happen client-side against Supabase Auth (GoTrue).
# A DB trigger mirrors each new auth.users row into public.users, and this API
# only validates the Supabase-issued JWT (see app.core.security).
