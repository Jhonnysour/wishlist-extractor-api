"""
Diagnostico de precio para UNA url — dice de donde sale el precio y por que.

    python -m poc.debug_price <url>
    python -m poc.debug_price <url> --expect 499      # busca donde vive el precio real
    python -m poc.debug_price <url> --rendered        # fuerza el tier headless
    python -m poc.debug_price <url> --rendered --dump-html out.html  # vuelca el HTML a un archivo

Existe porque el desarrollo de este scraper se hace a veces desde una IP
(VPN) a la que el sitio le sirve una pagina distinta — otra tienda, otra
moneda, otro markup. Cuando eso pasa, quien tiene la pagina real es el
usuario, y adivinar la estructura del sitio a ciegas ya salio mal varias
veces. Esta herramienta la corre quien SI ve la pagina buena, y su salida
es la evidencia para arreglar la cascada con certeza.
"""

from __future__ import annotations

import asyncio
import sys

from bs4 import BeautifulSoup

from poc.extractor import (
    PRICE_META_FALLBACK_NAMES,
    PRICE_META_NAMES,
    PRICE_REGEX,
    _attrs_of,
    _clean_price_string,
    _distance_to_h1,
    _extract_meta_price,
    _extract_price,
    _extract_price_jsonld,
    _fetch_rendered_html,
    _fetch_static_html,
    _h1_depth_map,
    _has_upsell_context,
    _is_other_products_price,
    browser_manager,
)

MAX_CANDIDATES = 25


def _describe(tag) -> str:
    cls = " ".join(tag.get("class", []) or [])
    idv = tag.get("id", "") or ""
    out = f"<{tag.name}"
    if cls:
        out += f" class='{cls[:45]}'"
    if idv:
        out += f" id='{idv[:30]}'"
    return out + ">"


def _ancestor_trail(tag, levels: int = 4) -> str:
    """Where the tag lives — the chain that decides the upsell verdict."""
    parts = []
    node = tag.parent
    for _ in range(levels):
        if node is None or not hasattr(node, "get") or node.name in ("body", "html", "[document]"):
            break
        cls = " ".join(node.get("class", []) or [])
        idv = node.get("id", "") or ""
        tag_desc = node.name
        if idv:
            tag_desc += f"#{idv[:24]}"
        elif cls:
            tag_desc += f".{cls.split()[0][:24]}" if cls.split() else ""
        parts.append(tag_desc)
        node = node.parent
    return " < ".join(parts) if parts else "(top level)"


def analyse(html: str, expect: str | None) -> None:
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    print(f"\nh1: {h1.get_text(' ', strip=True)[:70]!r}" if h1 else "\nh1: (ninguno)")

    print("\n=== cascada ===")
    print(f"  1. meta explicito : {_extract_meta_price(soup, PRICE_META_NAMES)}")
    print(f"  2. JSON-LD offers : {_extract_price_jsonld(soup)}")
    itemprops = [
        (t.get("content") or t.get_text(strip=True))
        for t in soup.find_all(attrs={"itemprop": "price"})
    ]
    print(f"  3. itemprop=price : {itemprops[:4]}")
    print(f"  4. twitter:data1  : {_extract_meta_price(soup, PRICE_META_FALLBACK_NAMES)}")
    print(f"  -> _extract_price : {_extract_price(soup)}")

    chain = _h1_depth_map(soup)
    price_kw = __import__("re").compile(r"price|amount|cost|precio", __import__("re").I)

    print("\n=== candidatos de la heuristica, en orden DOM ===")
    print("  ajeno=SI -> dentro de <a> o <table>: es el precio de OTRO producto (se descarta)")
    print("  gana el candidato no-upsell mas cercano al h1 (menor dist)")
    print("   valor      dist  upsell  ajeno  veredicto     elemento / ubicacion")
    shown = 0
    for tag in soup.find_all(["span", "div", "p", "strong", "ins", "del"]):
        if not price_kw.search(_attrs_of(tag)):
            continue
        match = PRICE_REGEX.search(tag.get_text(strip=True))
        if not match:
            continue
        price = _clean_price_string(match.group(0))
        if price is None or price <= 0:
            continue
        shown += 1
        if shown > MAX_CANDIDATES:
            print(f"   ... (mas de {MAX_CANDIDATES})")
            break
        dist = _distance_to_h1(tag, chain)
        upsell = _has_upsell_context(tag)
        foreign = _is_other_products_price(tag)
        if foreign:
            verdict = "descarta:ajeno"
        elif upsell:
            verdict = "upsell:ultimo"
        else:
            verdict = "CANDIDATO"
        print(f"  {price:>9.2f}  {str(dist):>4}  {'SI' if upsell else '--':^6}  "
              f"{'SI' if foreign else '--':^5}  {verdict:<13} {_describe(tag)}")
        print(f"                          en: {_ancestor_trail(tag)}")
    if shown == 0:
        print("  (ninguno — el precio no esta en un elemento con clase/id de precio)")

    if expect:
        print(f"\n=== donde vive '{expect}' en el DOM ===")
        hits = 0
        for tag in soup.find_all(string=lambda s: s and expect in s):
            parent = tag.parent
            if parent is None:
                continue
            hits += 1
            if hits > 8:
                print("  ... (mas)")
                break
            txt = " ".join(str(tag).split())[:50]
            print(f"  {_describe(parent)}  texto={txt!r}")
            print(f"      en: {_ancestor_trail(parent)}")
            print(f"      dist a h1: {_distance_to_h1(parent, chain)}")
        if hits == 0:
            print(f"  '{expect}' no aparece como texto en el HTML "
                  f"(puede estar en un JSON embebido o pintarse por JS)")


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    expect = None
    if "--expect" in args:
        i = args.index("--expect")
        expect = args[i + 1]
        del args[i:i + 2]

    force_render = "--rendered" in args
    if force_render:
        args.remove("--rendered")

    dump_path = None
    if "--dump-html" in args:
        i = args.index("--dump-html")
        dump_path = args[i + 1]
        del args[i:i + 2]

    url = args[0]

    try:
        if force_render:
            html, blocked = await _fetch_rendered_html(url)
            tier = "rendered"
        else:
            html, blocked = await _fetch_static_html(url)
            tier = "static"
            if html is None or blocked:
                print(f"[static fallo/bloqueado -> probando rendered]")
                html, blocked = await _fetch_rendered_html(url)
                tier = "rendered"

        if html is None:
            print(f"no se pudo obtener la pagina (blocked={blocked})")
            return

        print(f"tier={tier}  len={len(html)}  blocked={blocked}")
        if dump_path:
            with open(dump_path, "w", encoding="utf-8") as fh:
                fh.write(html)
            print(f"[HTML volcado a {dump_path}]")
        analyse(html, expect)
    finally:
        await browser_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
