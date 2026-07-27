"""
Universal Product Data Extractor (two-tier).

Tier 1 (fast, free): fetch raw HTML with httpx and run a generic heuristic
cascade based on Open Graph, JSON-LD and common HTML patterns.

Tier 2 (fallback): when critical fields are missing (a typical sign of a
client-side-rendered / SPA page) or the static fetch fails, render the page
with a shared headless Chromium via Playwright and re-run the *same* parsing
cascade over the rendered HTML.

Stays async-compatible with the FastAPI backend via httpx + Playwright async.
"""

from __future__ import annotations

import json
import asyncio
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_IMAGES = 10
TIMEOUT_SECONDS = 15
RENDER_TIMEOUT_MS = 20_000
MAX_CONCURRENT_RENDERS = 3

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": (
        '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'
    ),
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

USER_AGENT = BROWSER_HEADERS["User-Agent"]

# Anti-bot interstitials answer with a real HTML page (often HTTP 200) whose
# <title> gives them away. Matched against the title only, to avoid flagging
# legitimate pages that merely mention "captcha" somewhere in their markup.
BLOCK_TITLE_SIGNATURES = (
    "attention required",        # Cloudflare
    "just a moment",             # Cloudflare JS challenge
    "client challenge",          # Radware / Akamai (Hollister)
    "checking your browser",
    "access denied",
    "access to this page has been denied",  # PerimeterX
    "robot check",               # Amazon
    "are you a human",
    "verify you are human",
    "unusual traffic",
    "security check",
    "pardon our interruption",   # Distil / Imperva
    "bot verification",
    "request blocked",
    "request unsuccessful",      # Incapsula
    "are you a robot",
    "403 forbidden",
)

EXCLUDE_IMG_KEYWORDS = (
    "logo", "icon", "avatar", "banner", "placeholder",
    "pixel", "spacer", "svg",
)

# Chromium flags that remove the most obvious automation tells.
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
]

# Injected before any page script runs. Deliberately conservative: it only
# hides the automation tells that are cheap and safe to hide.
#
# We intentionally do NOT fake navigator.plugins. The usual trick returns
# [1,2,3,4,5], but real Chrome exposes Plugin objects — an integer array is
# itself a well-known stealth signature, so the "disguise" flags you harder
# than an honest empty list would.
#
# Everything is wrapped in try/catch: this runs in every frame (including
# sandboxed iframes where these APIs may be missing) and a throwing init
# script must never disturb the page under inspection.
STEALTH_INIT_SCRIPT = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'languages', {
      get: () => ['en-US', 'en'],
    });
  } catch (e) {}
  try {
    if (typeof window.chrome === 'undefined') {
      window.chrome = { runtime: {} };
    }
  } catch (e) {}
  try {
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
      parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(parameters)
    );
  } catch (e) {}
})();
"""

# A product page is full of prices that are not the product's: protection
# plans, shipping, financing, accessories, "other sellers". When one of these
# words sits in a candidate's own attributes or its immediate surroundings,
# the number next to it is an upsell, not what the user is wishlisting.
# Bilingual on purpose — Amazon serves /-/es/ pages in Spanish.
# Visible copy is written for humans, so matching it is reliable.
UPSELL_TEXT_RE = re.compile(
    # English
    r"protection|warrant|coverage|insur|"
    r"subscri|per\s*month|/\s*mo\b|monthly|installment|financ|"
    r"shipping|delivery|"
    r"trade[\s-]?in|gift\s*card|"
    r"add[\s-]?on|accessor|"
    r"other\s+sellers|refurb|renewed|"
    # Spanish
    r"protecci|garant|cobertura|seguro|"
    r"suscri|al\s*mes|mensual|cuota|financi|"
    r"env[ií]o|entrega|"
    r"tarjeta\s*de\s*regalo|"
    r"accesorio|complement|"
    r"otros\s+vendedores|reacondicionado",
    re.IGNORECASE,
)

# Class/id names are structural, not prose, and generic substrings misfire:
# WooCommerce tags the *main product container* "shipping-taxable", which
# flagged the real price as a shipping charge. Only unambiguous upsell words
# belong here — "shipping"/"delivery" are deliberately text-only.
UPSELL_ATTR_RE = re.compile(
    r"protection|warranty|add-?on|accessor|insurance|subscription|"
    r"proteccion|garantia|accesorio",
    re.IGNORECASE,
)

# How far up the tree to look for an upsell label wrapping the candidate.
PRICE_CONTEXT_ANCESTORS = 4
PRICE_CONTEXT_TEXT_LIMIT = 250

# Sorts pages with no <h1> behind everything that could be measured.
NO_H1_DISTANCE = 10**6

# NOTE: there is deliberately no "max distance from the <h1>" cutoff. It looks
# reasonable and it is a trap: on Amazon the *real* price (#corePrice_feature_div)
# measures 21 steps from the title while the junk in the comparison table
# measures 27 — separating them would need a threshold accurate to one step.
# Distance only ranks candidates here; what a price is *inside* (a link, a
# comparison table) tells you whose price it is.

# A price number, in either order of the two shapes:
#   grouped  1,234.56 / 1.234,56 / 2,999   (separators every 3 digits)
#   plain    1299.00 / 499 / 63.00         (no grouping at all)
# The grouped branch must come first, and the plain branch must NOT be
# \d{1,3}: an earlier version used \d{1,3} with optional groups, so "$1299.00"
# matched only "$129" and silently reported a 10x-wrong price.
_PRICE_NUMBER = (
    r"(?:"
    r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?"
    r"|"
    r"\d+(?:[.,]\d{1,2})?"
    r")"
)

PRICE_REGEX = re.compile(
    rf"[\$\€\£\¥]\s*{_PRICE_NUMBER}"
    rf"|"
    rf"{_PRICE_NUMBER}\s*[\$\€\£\¥]"
)

# Explicit, product-specific price meta — trustworthy.
PRICE_META_NAMES = (
    "product:price:amount",
    "og:price:amount",
)

# Generic Twitter card slot: sometimes the price, sometimes shipping or a
# rating. Only consulted after the structured sources fail.
PRICE_META_FALLBACK_NAMES = (
    "twitter:data1",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_price_string(raw: str) -> Optional[float]:
    """Parse a price, resolving US (1,234.56) vs EU (1.234,56) notation."""
    stripped = re.sub(r"[^\d.,]", "", raw)
    if not stripped:
        return None

    if "." in stripped and "," in stripped:
        # Both separators present: the rightmost one is the decimal point.
        if stripped.rfind(".") > stripped.rfind(","):
            stripped = stripped.replace(",", "")
        else:
            stripped = stripped.replace(".", "").replace(",", ".")
    else:
        # One separator kind: is it a decimal point or a thousands grouper?
        # Blindly treating "," as decimal turned "2,999" into 2.999 -> 3.0.
        sep = "." if "." in stripped else ("," if "," in stripped else None)
        if sep:
            parts = stripped.split(sep)
            if len(parts) > 2:
                # 1,234,567 — repeated grouping, never decimals.
                stripped = stripped.replace(sep, "")
            elif len(parts[1]) == 3 and parts[0]:
                # Exactly 3 trailing digits ("2,999" / "1.299") reads as
                # grouping; a decimal price would show 1-2 ("1,50" / "63.00").
                stripped = stripped.replace(sep, "")
            else:
                stripped = stripped.replace(sep, ".")

    try:
        return round(float(stripped), 2)
    except ValueError:
        return None


def _is_relevant_image(src: str) -> bool:
    if not src or not isinstance(src, str):
        return False
    lower = src.lower()
    if any(kw in lower for kw in EXCLUDE_IMG_KEYWORDS):
        return False
    # On Amazon, product photos live under /images/I/; everything else on the
    # media host (/images/G/ site graphics, sprites, badges) is chrome. This is
    # where the render tier's <img> sweep picks up the most junk.
    if "media-amazon.com" in lower or "ssl-images-amazon.com" in lower:
        if "/images/i/" not in lower:
            return False
    return True


def _absolutize_url(raw_url: str, base_url: str) -> str:
    if raw_url.startswith(("http://", "https://", "data:")):
        return raw_url
    if raw_url.startswith("//"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}:{raw_url}"
    if raw_url.startswith("/"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{raw_url}"
    base = base_url.rstrip("/") + "/"
    return base + raw_url


# ---------------------------------------------------------------------------
# JSON-LD helpers (shared by the image and price cascades)
# ---------------------------------------------------------------------------


def _iter_jsonld_blobs(soup: BeautifulSoup):
    """Yield every JSON-LD object on the page, flattening ``@graph`` wrappers."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string
        if not text or not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        stack = list(data) if isinstance(data, list) else [data]
        while stack:
            blob = stack.pop(0)
            if not isinstance(blob, dict):
                continue
            graph = blob.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            yield blob


def _iter_jsonld_products(soup: BeautifulSoup):
    """Yield only the schema.org ``Product`` blobs."""
    for blob in _iter_jsonld_blobs(soup):
        raw_type = blob.get("@type", "")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(isinstance(t, str) and "Product" in t for t in types):
            yield blob


# ---------------------------------------------------------------------------
# Extraction cascade (shared by both tiers — operate on a BeautifulSoup)
# ---------------------------------------------------------------------------


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    meta = soup.find("meta", attrs={"property": "og:title"})
    if meta:
        content = meta.get("content")
        if content:
            return content.strip()

    meta_twitter = soup.find("meta", attrs={"name": "twitter:title"})
    if meta_twitter:
        content = meta_twitter.get("content")
        if content:
            return content.strip()

    title_tag = soup.find("title")
    if title_tag:
        text = title_tag.get_text(strip=True)
        if text:
            return text

    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text:
            return text

    return None


def _extract_amazon_description(soup: BeautifulSoup) -> Optional[str]:
    """On Amazon, the useful description lives in two DOM sections, not in the
    generic og/meta blurb: "Sobre este artículo" (#feature-bullets) and
    "Descripción del producto" (#productDescription). Combine them. These ids are
    Amazon-specific, so other stores never match and fall back to the meta cascade.
    """
    parts: list[str] = []

    feature_bullets = soup.find(id="feature-bullets")
    if feature_bullets:
        bullets: list[str] = []
        for li in feature_bullets.find_all("li"):
            if "aok-hidden" in (li.get("class") or []):
                continue  # Amazon hides legal/expander li's
            span = li.find("span", class_="a-list-item")
            text = (span or li).get_text(" ", strip=True)
            if text and text not in bullets:
                bullets.append(text)
        if bullets:
            parts.append("\n".join(f"• {b}" for b in bullets))

    product_description = soup.find(id="productDescription")
    if product_description:
        text = product_description.get_text(" ", strip=True)
        if text:
            parts.append(text)

    return "\n\n".join(parts) if parts else None


def _extract_description(soup: BeautifulSoup) -> Optional[str]:
    # Amazon's real product info first; otherwise the universal og/meta blurb.
    amazon = _extract_amazon_description(soup)
    if amazon:
        return amazon

    for finder in (
        lambda: soup.find("meta", attrs={"property": "og:description"}),
        lambda: soup.find("meta", attrs={"name": "twitter:description"}),
        lambda: soup.find("meta", attrs={"name": "description"}),
    ):
        meta = finder()
        if meta:
            content = meta.get("content")
            if content and content.strip():
                return content.strip()
    return None


# Amazon encodes the thumbnail size in the image filename, e.g.
# /images/I/71abc._AC_SX466_.jpg. Dropping that ._…_ segment yields
# /images/I/71abc.jpg — the full-resolution original. The /images/I/ path is
# Amazon-specific, so non-Amazon URLs never match and pass through untouched.
_AMAZON_IMG_SIZE_RE = re.compile(
    r"(/images/I/[^/.]+)\.[^/]+?(\.(?:jpg|jpeg|png|gif|webp))(\?.*)?$",
    re.IGNORECASE,
)


def _upgrade_image_url(url: str) -> str:
    """Return the highest-resolution variant of *url* when we can infer one.

    Currently strips Amazon's size token so carousel thumbnails (which look
    blurry blown up in the app) resolve to the native-resolution image.
    """
    return _AMAZON_IMG_SIZE_RE.sub(r"\1\2", url)


# AliExpress serves its product gallery not as <img> tags but inside an
# embedded JSON blob (window.runParams) under "imagePathList". The generic <img>
# sweep misses those and instead scoops footer badges (business-license / ICP
# seals hosted on the same alicdn CDN), so the app showed one real photo plus
# junk. Pulling imagePathList yields the true gallery; the key is
# AliExpress-specific, so other stores never match and fall back to the cascade.
_IMAGE_PATH_LIST_RE = re.compile(r'"imagePathList"\s*:\s*(\[[^\]]*\])')


def _extract_embedded_gallery(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Return the product gallery from a page's embedded JSON, if any.

    Currently handles AliExpress's ``imagePathList``. Returns [] when the page
    carries no such blob, leaving every other store to the normal cascade.
    """
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text or "imagePathList" not in text:
            continue
        match = _IMAGE_PATH_LIST_RE.search(text)
        if not match:
            continue
        try:
            urls = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        gallery: list[str] = []
        seen: set[str] = set()
        for u in urls:
            if not isinstance(u, str) or not u.strip():
                continue
            full = _absolutize_url(u.strip(), base_url)
            if full not in seen:
                gallery.append(full)
                seen.add(full)
        if gallery:
            return gallery[:MAX_IMAGES]
    return []


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()

    # Priority 0: an embedded gallery (e.g. AliExpress imagePathList) is the
    # authoritative photo set. When present, trust it alone — the generic <img>
    # sweep below would otherwise scoop unrelated footer badges alongside it.
    embedded = _extract_embedded_gallery(soup, base_url)
    if embedded:
        return embedded

    # Priority 1: Open Graph
    for meta in soup.find_all("meta", attrs={"property": "og:image"}):
        content = meta.get("content")
        if content:
            full = _upgrade_image_url(_absolutize_url(content, base_url))
            if full not in seen:
                images.append(full)
                seen.add(full)

    # Priority 2: JSON-LD Product
    for blob in _iter_jsonld_products(soup):
        img = blob.get("image")
        if img is None:
            continue
        candidates = [img] if isinstance(img, str) else img
        if not isinstance(candidates, list):
            continue
        for c in candidates:
            # schema.org allows an ImageObject instead of a bare URL string.
            if isinstance(c, dict):
                c = c.get("url") or c.get("contentUrl")
            if isinstance(c, str):
                full = _upgrade_image_url(_absolutize_url(c, base_url))
                if full not in seen:
                    images.append(full)
                    seen.add(full)

    # Priority 3: generic <img> tags (filtered)
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            continue
        if not _is_relevant_image(src):
            continue
        full = _upgrade_image_url(_absolutize_url(src, base_url))
        if full in seen:
            continue
        images.append(full)
        seen.add(full)
        if len(images) >= MAX_IMAGES:
            break

    return images[:MAX_IMAGES]


def _coerce_price(value) -> Optional[float]:
    """Turn a JSON-LD price (number or string) into a positive float."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        price = round(float(value), 2)
    elif isinstance(value, str):
        price = _clean_price_string(value)
    else:
        return None
    if price is None or price <= 0:
        return None
    return price


def _extract_price_jsonld(soup: BeautifulSoup) -> Optional[float]:
    """Read the price from schema.org ``Product.offers``.

    Handles a single Offer, a list of Offers, and AggregateOffer (``lowPrice``).
    """
    for blob in _iter_jsonld_products(soup):
        offers = blob.get("offers")
        if offers is None:
            continue
        candidates = offers if isinstance(offers, list) else [offers]
        for offer in candidates:
            if not isinstance(offer, dict):
                continue
            for key in ("price", "lowPrice"):
                price = _coerce_price(offer.get(key))
                if price is not None:
                    return price
            # AggregateOffer may nest the real offers one level down.
            nested = offer.get("offers")
            nested_list = nested if isinstance(nested, list) else [nested]
            for sub in nested_list:
                if isinstance(sub, dict):
                    price = _coerce_price(sub.get("price"))
                    if price is not None:
                        return price
    return None


def _attrs_of(node) -> str:
    return " ".join(node.get("class", []) or []) + " " + (node.get("id", "") or "")


def _has_upsell_context(tag) -> bool:
    """True when *tag*'s own attributes or nearby markup label it as an upsell
    (protection plan, shipping, financing...) rather than the product price."""
    if UPSELL_ATTR_RE.search(_attrs_of(tag)):
        return True

    node = tag
    for _ in range(PRICE_CONTEXT_ANCESTORS):
        node = node.parent
        if node is None or not hasattr(node, "get"):
            break
        # <body>/<html> are not "context", they are the whole page: their text
        # contains every upsell on it, which would flag every candidate —
        # including the real price sitting in an unrelated sibling section.
        if node.name in ("body", "html", "[document]"):
            break
        if UPSELL_ATTR_RE.search(_attrs_of(node)):
            return True
        # Only read text from a tight wrapper; a big section's text would
        # sweep in unrelated copy.
        text = node.get_text(" ", strip=True)
        if len(text) <= PRICE_CONTEXT_TEXT_LIMIT and UPSELL_TEXT_RE.search(text):
            return True

    return False


def _is_other_products_price(tag) -> bool:
    """True when *tag* prices something other than the product on the page.

    Two structural tells, both about what the price is *inside*:

    * an <a> — you would navigate to it, so it belongs to a recommendation,
      a related item or an ad. A page does not hyperlink its own price.
      Amazon nests carousel prices in <a class="a-link-normal">, WooCommerce
      in <a class="woocommerce-LoopProduct-link">; both leave the real one
      outside any anchor.
    * a <table> — comparison grids ("compare with similar items") list rival
      products in plain <td>s, with no link and no upsell wording to give
      them away. The product's own price is not tabular data.

    Structure identifies these where wording and distance cannot: on an Amazon
    page with no price block, all 16 candidates were inside a link or a
    comparison table, so dropping both leaves nothing — which is the correct
    answer, and lets the headless tier retry.
    """
    return tag.find_parent(["a", "table"]) is not None


def _h1_depth_map(soup: BeautifulSoup) -> dict[int, int]:
    """Ancestors of the product <h1>, mapped to their distance from it."""
    depths: dict[int, int] = {}
    node = soup.find("h1")
    depth = 0
    while node is not None:
        depths[id(node)] = depth
        node = node.parent
        depth += 1
    return depths


def _distance_to_h1(tag, depths: dict[int, int]) -> Optional[int]:
    """Tree distance from *tag* to the <h1>, through their common ancestor.

    The product's own price sits right next to its title; prices for related
    items, ads and add-ons live in far-away sections. On a WooCommerce page
    the real price scores 2 while the "related products" ones score 7-8.
    """
    if not depths:
        return None
    node = tag
    up = 0
    while node is not None:
        depth = depths.get(id(node))
        if depth is not None:
            return up + depth
        node = node.parent
        up += 1
    return None


def _extract_meta_price(soup: BeautifulSoup, names: tuple[str, ...]) -> Optional[float]:
    for name in names:
        meta = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if meta:
            content = meta.get("content")
            if content:
                price = _clean_price_string(content)
                if price is not None:
                    return price
    return None


def _extract_price(soup: BeautifulSoup) -> Optional[float]:
    # Priority 1: explicit product price meta tags
    price = _extract_meta_price(soup, PRICE_META_NAMES)
    if price is not None:
        return price

    # Priority 2: JSON-LD Product.offers (structured, most accurate on
    # complex pages where the heuristic would grab an accessory's price)
    price = _extract_price_jsonld(soup)
    if price is not None:
        return price

    # Priority 3: structured data via itemprop
    for tag in soup.find_all(attrs={"itemprop": "price"}):
        content = tag.get("content") or tag.get_text(strip=True)
        if content:
            price = _clean_price_string(content)
            if price is not None:
                return price

    # Priority 4: generic Twitter card slot
    price = _extract_meta_price(soup, PRICE_META_FALLBACK_NAMES)
    if price is not None:
        return price

    # Priority 5: rank every price-ish element instead of taking the first.
    # Ranking (not filtering) matters: an over-eager upsell rule used to
    # discard every candidate and fall back to whichever came first in the
    # DOM — which on Amazon is a sponsored item, not the product.
    price_keywords = re.compile(r"price|amount|cost|precio", re.I)
    depths = _h1_depth_map(soup)
    candidates: list[tuple[int, int, int, float]] = []

    for order, tag in enumerate(soup.find_all(["span", "div", "p", "strong", "ins", "del"])):
        if not price_keywords.search(_attrs_of(tag)):
            continue
        # Dropped outright, not just ranked down: this is some other product's
        # price. Keeping it as a fallback is what made Amazon report $47.99
        # from a "customers also bought" carousel — and, worse, that bogus
        # price satisfied _needs_render(), so the headless tier that could
        # have found the real one never ran.
        if _is_other_products_price(tag):
            continue
        # Join child text with a space, never bare. Amazon splits a price into
        # <span class="a-price-whole">499</span><span class="a-price-fraction">00</span>,
        # which concatenates to "$49900"; neighbouring fragments fused into a
        # single plausible-looking number (one page yielded "$499004.00").
        match = PRICE_REGEX.search(tag.get_text(" ", strip=True))
        if not match:
            continue
        price = _clean_price_string(match.group(0))
        if price is None or price <= 0:
            continue
        distance = _distance_to_h1(tag, depths)
        candidates.append((
            1 if _has_upsell_context(tag) else 0,   # upsells last
            distance if distance is not None else NO_H1_DISTANCE,  # then nearest the title
            order,                                  # then document order
            price,
        ))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[:3])
    return candidates[0][3]


def _extract_price_from_url(url: str) -> Optional[float]:
    """Read the price from an AliExpress deep link's ``pdp_npi`` parameter.

    AliExpress injects its price via a late XHR, so it is absent from the HTML
    we capture (server tier or WebView). But links shared from a search/listing
    carry the price in ``pdp_npi``, which URL-decodes to an ``!``-delimited list
    ``...!<currency>!<listPrice>!<salePrice>!...`` (e.g. ``6@dis!USD!981.61!765.56!...``).
    We take the sale price — what the page shows — falling back to the list price.

    The parameter is AliExpress-specific, so other stores yield ``None``.
    """
    params = parse_qs(urlparse(url).query)
    npi = params.get("pdp_npi")
    if not npi:
        return None
    parts = npi[0].split("!")
    for i, token in enumerate(parts):
        # The currency code (USD/EUR/...) anchors the two prices that follow it.
        if len(token) == 3 and token.isalpha() and token.isupper():
            for j in (i + 2, i + 1):  # sale price first, then list price
                if j < len(parts):
                    price = _clean_price_string(parts[j])
                    if price is not None and price > 0:
                        return price
            break
    return None


def _parse_into(result: dict, html: str, base_url: str) -> None:
    """Run the cascade over *html* and fill any missing fields in *result*.

    Fields already populated (e.g. by the static tier) are kept — the render
    tier only fills the gaps.
    """
    soup = BeautifulSoup(html, "html.parser")

    if not result.get("title"):
        title = _extract_title(soup)
        if title:
            result["title"] = title

    if not result.get("description"):
        description = _extract_description(soup)
        if description:
            result["description"] = description

    if not result.get("images"):
        images = _extract_images(soup, base_url)
        if images:
            result["images"] = images

    if result.get("price") is None:
        # In-page price wins; the URL (AliExpress pdp_npi) only fills the gap
        # when the price never made it into the captured HTML.
        price = _extract_price(soup) or _extract_price_from_url(base_url)
        if price is not None:
            result["price"] = price


def _needs_render(result: dict) -> bool:
    """Static extraction is considered insufficient when price or images are
    missing — the fields most often injected by client-side JavaScript."""
    return result.get("price") is None or not result.get("images")


# ---------------------------------------------------------------------------
# Shared headless browser (Tier 2)
# ---------------------------------------------------------------------------


class _BrowserManager:
    """Owns a single long-lived Chromium instance shared across scrapes.

    Started/stopped from the FastAPI lifespan; also lazy-starts on first use
    so the standalone CLI and background tasks work without app wiring.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        if self._browser is not None:
            return
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=LAUNCH_ARGS,
        )

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    async def get_browser(self):
        if self._browser is None:
            async with self._lock:
                await self.start()
        return self._browser


browser_manager = _BrowserManager()
_render_semaphore = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)


def _looks_blocked(html: str) -> bool:
    """True when *html* is an anti-bot interstitial rather than the real page."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return False
    title = match.group(1).strip().lower()
    return any(sig in title for sig in BLOCK_TITLE_SIGNATURES)


async def _fetch_static_html(url: str) -> tuple[Optional[str], bool]:
    """Tier 1 fetch. Returns ``(html, blocked)``; html is None if the request
    failed outright."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=BROWSER_HEADERS,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
        ) as client:
            response = await client.get(url)
            if response.status_code in (403, 429):
                return None, True
            response.raise_for_status()
            html = response.text
            return html, _looks_blocked(html)
    except Exception:
        return None, False


async def _fetch_rendered_html(url: str) -> tuple[Optional[str], bool]:
    """Tier 2 fetch. Renders the page with headless Chromium. Returns
    ``(html, blocked)``; html is None if rendering failed."""
    try:
        browser = await browser_manager.get_browser()
    except Exception:
        return None, False

    async with _render_semaphore:
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": BROWSER_HEADERS["Accept-Language"],
            },
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        try:
            page = await context.new_page()
            # "networkidle" never settles on sites with persistent analytics
            # beacons (e.g. IKEA) and causes false timeouts; wait for the DOM
            # plus a short settle window for client-side rendering instead.
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT_MS
            )
            await page.wait_for_timeout(2_500)
            html = await page.content()
            blocked = (
                response is not None and response.status in (403, 429)
            ) or _looks_blocked(html)
            return html, blocked
        except Exception:
            return None, False
        finally:
            await context.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _finalize_status(result: dict, blocked: bool, fetched_any: bool) -> str:
    """Decide the terminal status from what the cascade managed to fill in.

    Usable means a title plus at least a price or an image. Otherwise the
    outcome says *why* we came up empty: an anti-bot wall (``blocked``), a page
    we retrieved but couldn't parse (``no_data``), or one we never fetched at
    all (``fetch_error``). Shared by the network fetch path and the
    client-supplied-HTML path (Capa 0), so both classify results identically.
    """
    has_usable = bool(result.get("title")) and (
        result.get("price") is not None or bool(result.get("images"))
    )
    if has_usable:
        return "ok"
    if blocked:
        return "blocked"
    if fetched_any:
        return "no_data"
    return "fetch_error"


async def extract_product_data(url: str) -> dict:
    """Extract product data from *url* using the static tier, falling back to
    the headless render tier when needed.

    Returns a dict with ``title``, ``price``, ``images``, ``description``,
    ``domain_source``, a ``status`` of:
      * ``"ok"``          — usable data extracted
      * ``"blocked"``     — the site served an anti-bot interstitial
      * ``"no_data"``     — page(s) fetched but nothing usable found
      * ``"fetch_error"`` — could not retrieve the page at all
    and a ``tier`` of ``"static"`` (tier 1 sufficed), ``"rendered"`` (the
    headless fallback ran and its HTML was parsed) or ``"none"`` (no fetch
    succeeded).
    """
    parsed = urlparse(url)
    result: dict = {
        "title": None,
        "price": None,
        "images": [],
        "description": None,
        "domain_source": f"{parsed.scheme}://{parsed.netloc}",
        "status": "no_data",
        "tier": "none",
    }

    fetched_any = False

    # --- Tier 1: static HTML ---
    static_html, blocked = await _fetch_static_html(url)
    if static_html is not None and not blocked:
        fetched_any = True
        result["tier"] = "static"
        _parse_into(result, static_html, url)

    # --- Tier 2: headless render fallback ---
    if _needs_render(result):
        rendered_html, rendered_blocked = await _fetch_rendered_html(url)
        # The render is the final word on whether we got through.
        blocked = rendered_blocked
        if rendered_html is not None and not rendered_blocked:
            fetched_any = True
            result["tier"] = "rendered"
            _parse_into(result, rendered_html, url)

    # --- Status ---
    result["status"] = _finalize_status(result, blocked, fetched_any)

    return result


def extract_from_html(html: str, url: str) -> dict:
    """Run the extraction cascade over already-rendered *html* (Capa 0).

    Same parsing as :func:`extract_product_data`, but the HTML is supplied by
    the client's WebView instead of fetched here — so there's no network tier,
    no anti-bot wall to hit, and the call is synchronous. Used for pages that
    never serve their price to a server-side scraper (e.g. Amazon).
    """
    parsed = urlparse(url)
    result: dict = {
        "title": None,
        "price": None,
        "images": [],
        "description": None,
        "domain_source": f"{parsed.scheme}://{parsed.netloc}",
        "status": "no_data",
        "tier": "client",
    }
    _parse_into(result, html, url)
    # The client already loaded the page in a real browser, so there is no
    # "blocked" outcome here; fetched_any is True because we have the HTML.
    result["status"] = _finalize_status(result, blocked=False, fetched_any=True)
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the extractor against a sample product page."""
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://scrapeme.live/shop/Bulbasaur/"
    try:
        data = await extract_product_data(url)
        print(json.dumps(data, indent=4, ensure_ascii=False))
    finally:
        await browser_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
