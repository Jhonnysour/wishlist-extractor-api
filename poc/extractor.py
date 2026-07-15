"""
PoC — Async E-Commerce Product Data Extractor.

Uses httpx (async) and beautifulsoup4 to extract title, price and images
from a product page following a strict cascade / fallback strategy.
"""

from __future__ import annotations

import json
import asyncio
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

MAX_IMAGES = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
EXCLUDE_IMG_SUBSTRINGS = ("logo", "icon", "svg", "avatar")


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str:
    """Fetch the HTML content of *url* and return it as a decoded string."""
    response = await client.get(url)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Image extraction — cascade helpers
# ---------------------------------------------------------------------------


def _extract_images_from_ld_json(soup: BeautifulSoup) -> list[str]:
    """
    Priority 1 — parse ``<script type="application/ld+json">`` blocks.

    Returns a list of image URLs extracted from the first *Product*-typed
    JSON-LD block found, or an empty list if nothing could be extracted.
    """
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        text = script.string
        if not text or not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            for item in data:
                images = _extract_images_from_ld_blob(item)
                if images:
                    return images
        else:
            images = _extract_images_from_ld_blob(data)
            if images:
                return images
    return []


def _extract_images_from_ld_blob(blob: dict) -> list[str]:
    """Extract ``image`` from a single JSON-LD blob if it's a Product."""
    if not isinstance(blob, dict):
        return []
    raw_type = blob.get("@type", "")
    if isinstance(raw_type, list):
        types = raw_type
    else:
        types = [raw_type]
    if not any("Product" in t for t in types):
        return []
    image_field = blob.get("image")
    if image_field is None:
        return []
    if isinstance(image_field, str):
        return [image_field]
    if isinstance(image_field, list):
        return [str(i) for i in image_field if isinstance(i, str)]
    return []


def _extract_images_from_og(soup: BeautifulSoup) -> list[str]:
    """
    Priority 2 — collect ``content`` attributes from all
    ``<meta property="og:image">`` tags.
    """
    metas = soup.find_all("meta", attrs={"property": "og:image"})
    images: list[str] = []
    for meta in metas:
        content = meta.get("content")
        if content:
            images.append(content)
    return images


def _extract_images_from_img_tags(soup: BeautifulSoup) -> list[str]:
    """
    Priority 3 — collect ``src`` from ``<img>`` tags, filtering out
    common non-product images (logos, icons, avatars, SVGs).
    """
    imgs = soup.find_all("img")
    images: list[str] = []
    for img in imgs:
        src = img.get("src")
        if not src or not isinstance(src, str):
            continue
        src_lower = src.lower()
        if any(bad in src_lower for bad in EXCLUDE_IMG_SUBSTRINGS):
            continue
        images.append(src)
    return images


# ---------------------------------------------------------------------------
# Title & price extraction helpers
# ---------------------------------------------------------------------------


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    """Extract the product title from ``og:title`` or ``<title>``."""
    meta = soup.find("meta", attrs={"property": "og:title"})
    if meta:
        content = meta.get("content")
        if content:
            return content
    title_tag = soup.find("title")
    if title_tag:
        text = title_tag.get_text(strip=True)
        if text:
            return text
    return None


def _extract_price(soup: BeautifulSoup) -> Optional[float]:
    """Extract the product price from ``<meta property="og:price:amount">``."""
    meta = soup.find("meta", attrs={"property": "og:price:amount"})
    if meta:
        content = meta.get("content")
        if content:
            try:
                return float(content)
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_product_data(url: str) -> dict:
    """
    Extract title, price and up to *MAX_IMAGES* product images from *url*.

    Returns a dictionary with keys ``title`` (``str``), ``price``
    (``float | None``) and ``images`` (``list[str]``).
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            html = await _fetch_html(client, url)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc

    soup = BeautifulSoup(html, "html.parser")

    # --- Image cascade ---
    images = _extract_images_from_ld_json(soup)
    if not images:
        images = _extract_images_from_og(soup)
    if not images:
        images = _extract_images_from_img_tags(soup)

    # --- Title & price ---
    title = _extract_title(soup) or ""
    price = _extract_price(soup)

    return {
        "title": title,
        "price": price,
        "images": images[:MAX_IMAGES],
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the extractor against a sample product page."""
    url = "https://scrapeme.live/shop/Bulbasaur/"
    try:
        data = await extract_product_data(url)
    except Exception as exc:
        print(f"Error: {exc}")
        return
    print(json.dumps(data, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
