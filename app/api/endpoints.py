"""
API endpoints for item extraction, user registration, and authentication.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.item import Item
from app.models.item_list import ItemList
from app.models.user import User
from app.schemas.item import ItemFromHtml, ItemResponse, ItemUpdate, UrlInput
from app.schemas.list import ListCreate, ListResponse, ListUpdate
from poc.extractor import extract_from_html, extract_product_data

router = APIRouter()


# ---------------------------------------------------------------------------
# Lists (named groups of items)
# ---------------------------------------------------------------------------


async def _get_owned_list(
    list_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> ItemList:
    """Fetch a list, 404ing unless it belongs to *current_user*."""
    stmt = select(ItemList).where(
        ItemList.id == list_id,
        ItemList.user_id == current_user.id,
    )
    lst = (await db.execute(stmt)).scalar_one_or_none()
    if lst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List {list_id} not found",
        )
    return lst


async def _default_list_id(db: AsyncSession, current_user: User) -> uuid.UUID:
    """The user's oldest list, creating a 'Mi lista' if they somehow have none.
    Used when a client adds an item without specifying a list."""
    stmt = (
        select(ItemList.id)
        .where(ItemList.user_id == current_user.id)
        .order_by(ItemList.created_at)
        .limit(1)
    )
    lid = (await db.execute(stmt)).scalar_one_or_none()
    if lid is None:
        lst = ItemList(user_id=current_user.id, name="Mi lista")
        db.add(lst)
        await db.flush()
        lid = lst.id
    return lid


@router.post("/lists", response_model=ListResponse, status_code=status.HTTP_201_CREATED)
async def create_list(
    body: ListCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ListResponse:
    """Create a new list for the current user."""
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de la lista no puede estar vacío.",
        )
    lst = ItemList(user_id=current_user.id, name=name)
    db.add(lst)
    await db.commit()
    await db.refresh(lst)
    return ListResponse(
        id=lst.id, name=lst.name, created_at=lst.created_at, item_count=0
    )


@router.get("/lists", response_model=list[ListResponse])
async def list_lists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ListResponse]:
    """The current user's lists, oldest first, each with its item count."""
    stmt = (
        select(ItemList, func.count(Item.id))
        .outerjoin(Item, Item.list_id == ItemList.id)
        .where(ItemList.user_id == current_user.id)
        .group_by(ItemList.id)
        .order_by(ItemList.created_at)
    )
    rows = (await db.execute(stmt)).all()
    return [
        ListResponse(
            id=lst.id, name=lst.name, created_at=lst.created_at, item_count=count
        )
        for lst, count in rows
    ]


@router.patch("/lists/{list_id}", response_model=ListResponse)
async def update_list(
    list_id: uuid.UUID,
    body: ListUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ListResponse:
    """Rename a list."""
    lst = await _get_owned_list(list_id, db, current_user)
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de la lista no puede estar vacío.",
        )
    lst.name = name
    await db.commit()
    await db.refresh(lst)
    count = (
        await db.execute(
            select(func.count(Item.id)).where(Item.list_id == lst.id)
        )
    ).scalar_one()
    return ListResponse(
        id=lst.id, name=lst.name, created_at=lst.created_at, item_count=count
    )


@router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(
    list_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a list AND its items (the DB cascades via items.list_id)."""
    lst = await _get_owned_list(list_id, db, current_user)
    await db.delete(lst)
    await db.commit()


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


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
    """Submit a product URL for extraction, into a list."""
    url = str(body.url)
    if body.list_id is not None:
        await _get_owned_list(body.list_id, db, current_user)  # 404 if not owned
        list_id = body.list_id
    else:
        list_id = await _default_list_id(db, current_user)
    item = Item(
        original_url=url,
        user_id=current_user.id,
        list_id=list_id,
        status="PENDING",
    )
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
    list_id: uuid.UUID | None = Query(
        default=None,
        description="Solo los items de esta lista. Omitir = todos los del usuario.",
    ),
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
    """The current user's items, newest first, filtered by list and/or search."""
    stmt = select(Item).where(Item.user_id == current_user.id)

    if list_id is not None:
        await _get_owned_list(list_id, db, current_user)  # 404 if not owned
        stmt = stmt.where(Item.list_id == list_id)

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

    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El título no puede estar vacío.",
            )
        item.title = title

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
    # Fill gaps, never downgrade: this retry now also runs for items the server
    # completed *without a price* (MercadoLibre's anti-bot wall still yields a
    # title and an og:image). If the WebView hits that same wall, its thinner
    # result must not wipe the title/images/description we already had.
    item.title = result.get("title") or item.title
    item.price = result.get("price") if result.get("price") is not None else item.price
    item.images = result.get("images") or item.images
    item.description = result.get("description") or item.description
    item.domain_source = result.get("domain_source") or item.domain_source
    if item.price is not None or item.images:
        item.status = "COMPLETED" if item.title else "FAILED"
    else:
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
