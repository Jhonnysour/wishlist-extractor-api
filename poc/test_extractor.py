"""
Tests del extractor — sin dependencias externas.

    python -m poc.test_extractor

Cubren sobre todo el parseo de precios, porque sus fallos son *silenciosos*:
no lanzan excepcion, devuelven un numero plausible pero equivocado
($1299.00 -> 129.0) y llegan hasta la wishlist del usuario como si nada.
"""

from __future__ import annotations

import sys

from bs4 import BeautifulSoup

from poc.extractor import (
    PRICE_REGEX,
    _clean_price_string,
    _extract_images,
    _extract_price,
    _extract_price_jsonld,
    _looks_blocked,
    _upgrade_image_url,
)

_failures: list[str] = []


def check(name: str, got, expected) -> None:
    if got == expected:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}\n          got={got!r}  expected={expected!r}")
        _failures.append(name)


def price_from_text(text: str):
    match = PRICE_REGEX.search(text)
    return _clean_price_string(match.group(0)) if match else None


def page(body: str, head: str = "") -> BeautifulSoup:
    return BeautifulSoup(f"<html><head>{head}</head><body>{body}</body></html>",
                         "html.parser")


# ---------------------------------------------------------------------------


def test_price_parsing() -> None:
    print("\n[precios en texto libre]")
    # Regression: \d{1,3} + optional grouping matched only "$129" of "$1299.00".
    check("4 cifras sin coma no se trunca", price_from_text("$1299.00"), 1299.00)
    check("$1099.00", price_from_text("$1099.00"), 1099.00)
    check("$2999.00", price_from_text("$2999.00"), 2999.00)
    check("3 cifras con decimales", price_from_text("$499.00"), 499.00)
    check("2 cifras con decimales", price_from_text("$63.00"), 63.00)
    check("entero sin decimales", price_from_text("$999"), 999.00)
    # Regression: "," read as decimal turned 2,999 into 2.999 -> round -> 3.0
    check("miles con coma, sin decimales", price_from_text("$2,999"), 2999.00)
    check("miles con coma y decimales", price_from_text("$2,999.00"), 2999.00)
    check("millones", price_from_text("$1,234,567.89"), 1234567.89)
    check("prefijo US$", price_from_text("US$499.00"), 499.00)
    check("simbolo a la derecha (EU)", price_from_text("1.299,50 EUR".replace("EUR", "€")), 1299.50)
    check("EU decimal", price_from_text("89,95 €"), 89.95)
    check("centimos", price_from_text("$0.99"), 0.99)
    check("precio dentro de una frase", price_from_text("Precio: US$89.95 hoy"), 89.95)

    print("\n[_clean_price_string directo (meta / JSON-LD)]")
    check("1299.00", _clean_price_string("1299.00"), 1299.00)
    check("2,999 -> miles", _clean_price_string("2,999"), 2999.00)
    check("1,50 -> decimal", _clean_price_string("1,50"), 1.50)
    check("1.299 -> miles EU", _clean_price_string("1.299"), 1299.00)
    check("1.299,50 -> EU", _clean_price_string("1.299,50"), 1299.50)
    check("1,299.50 -> US", _clean_price_string("1,299.50"), 1299.50)
    check("vacio -> None", _clean_price_string("sin numeros"), None)


def test_price_cascade() -> None:
    print("\n[cascada de precio]")
    check(
        "meta explicito gana a JSON-LD",
        _extract_price(page(
            "",
            '<meta property="product:price:amount" content="10.00">'
            '<script type="application/ld+json">'
            '{"@type":"Product","offers":{"price":"99"}}</script>',
        )),
        10.00,
    )
    check(
        "JSON-LD gana a la heuristica",
        _extract_price(page(
            '<span class="price">$129.00</span>',
            '<script type="application/ld+json">'
            '{"@type":"Product","offers":{"price":"1099.00"}}</script>',
        )),
        1099.00,
    )


def test_jsonld() -> None:
    print("\n[JSON-LD offers]")

    def ld(blob: str):
        return _extract_price_jsonld(
            page("", f'<script type="application/ld+json">{blob}</script>')
        )

    check("offer numero", ld('{"@type":"Product","offers":{"price":1299.00}}'), 1299.00)
    check("offer string", ld('{"@type":"Product","offers":{"price":"1299.00"}}'), 1299.00)
    check("lista de offers", ld('{"@type":"Product","offers":[{"price":"49.99"}]}'), 49.99)
    check("AggregateOffer lowPrice",
          ld('{"@type":"Product","offers":{"@type":"AggregateOffer","lowPrice":"899.99"}}'), 899.99)
    check("AggregateOffer anidado",
          ld('{"@type":"Product","offers":{"@type":"AggregateOffer","offers":[{"price":"75.50"}]}}'), 75.50)
    check("@graph", ld('{"@graph":[{"@type":"WebPage"},{"@type":"Product","offers":{"price":"33.00"}}]}'), 33.00)
    check("array raiz", ld('[{"@type":"BreadcrumbList"},{"@type":"Product","offers":{"price":"12.34"}}]'), 12.34)
    check("@type lista", ld('{"@type":["Product","Thing"],"offers":{"price":"21.00"}}'), 21.00)
    check("sin offers -> None", ld('{"@type":"Product","name":"x"}'), None)
    check("no es Product -> None", ld('{"@type":"Article","offers":{"price":"99"}}'), None)
    check("JSON roto -> None", ld('{"@type":"Product", ROTO'), None)
    check("precio 0 -> None", ld('{"@type":"Product","offers":{"price":0}}'), None)

    check(
        "ImageObject y string mezclados",
        _extract_images(page("", '<script type="application/ld+json">'
                                 '{"@type":"Product","image":['
                                 '{"@type":"ImageObject","url":"https://x.com/a.jpg"},'
                                 '"https://x.com/b.jpg"]}</script>'), "https://x.com"),
        ["https://x.com/a.jpg", "https://x.com/b.jpg"],
    )


def test_upsell_context() -> None:
    print("\n[upsell: el precio del producto, no el del plan de proteccion]")
    # El bug reportado: Amazon ES daba 47.99 (plan de proteccion) por 499 (Switch 2).
    check(
        "Amazon ES: producto vs plan de proteccion",
        _extract_price(page(
            '<div id="ppd"><span class="a-price">US$499.00</span></div>'
            '<div id="mbb"><label>Agregar un plan de proteccion:</label>'
            '<span class="a-price">US$47.99</span></div>'
        )),
        499.00,
    )
    check(
        "upsell primero en el DOM",
        _extract_price(page(
            '<div class="protection-plan"><span class="a-price">US$47.99</span></div>'
            '<div class="core-price"><span class="a-price">US$499.00</span></div>'
        )),
        499.00,
    )
    check(
        "EN: warranty",
        _extract_price(page(
            '<div class="warranty"><span class="price">$29.99</span>'
            '<span>2-year protection plan</span></div>'
            '<div><span class="price">$1099.00</span></div>'
        )),
        1099.00,
    )
    check(
        "ES: envio no gana",
        _extract_price(page(
            '<div><span class="precio-envio">US$5.99</span><span>Costo de envio</span></div>'
            '<div><span class="price">US$88.00</span></div>'
        )),
        88.00,
    )
    check(
        "EN: financiacion mensual no gana",
        _extract_price(page(
            '<div><span class="price">$41.58</span><span>per month for 24 months</span></div>'
            '<div><span class="price">$999.00</span></div>'
        )),
        999.00,
    )
    check(
        "precio limpio unico intacto",
        _extract_price(page('<span class="price">$63.00</span>')),
        63.00,
    )
    # Regression: walking ancestors up to <body> flagged every candidate,
    # because body's text contains the upsell copy of a sibling section.
    check(
        "el precio real no se marca por un hermano upsell",
        _extract_price(page(
            '<div class="protection"><span class="price">$47.99</span></div>'
            '<div><span class="price">$499.00</span></div>'
        )),
        499.00,
    )
    check(
        "si SOLO hay upsell, se usa como ultimo recurso",
        _extract_price(page('<div class="protection"><span class="price">$47.99</span></div>')),
        47.99,
    )
    # Regression: WooCommerce pone "shipping-taxable" en el contenedor del
    # producto; buscar "shipping" en class/id marcaba el precio REAL como envio.
    check(
        "clase 'shipping-taxable' de WooCommerce no marca el precio real",
        _extract_price(page(
            '<div class="post-759 product shipping-taxable">'
            '<h1>Bulbasaur</h1><p class="price">£63.00</p></div>'
        )),
        63.00,
    )
    # Regression: cuando el filtro marca todo, el orden del DOM elegia un
    # patrocinado. La distancia al h1 tiene que decidir.
    check(
        "cercania al h1 gana al orden del DOM",
        _extract_price(page(
            '<div class="sponsored"><span class="price">$6.47</span></div>'
            '<div id="main"><h1>Nintendo Switch 2</h1>'
            '<span class="a-price">US$499.00</span></div>'
        )),
        499.00,
    )
    check(
        "productos relacionados no le ganan al precio del producto",
        _extract_price(page(
            '<div class="summary"><h1>Bulbasaur</h1><p class="price">£63.00</p></div>'
            '<section class="related"><span class="price">£60.00</span>'
            '<span class="price">£87.00</span></section>'
        )),
        63.00,
    )

    print("\n[precios dentro de <a> = de otro producto]")
    # Estructura real del carrusel p13n de Amazon ("tambien compraron"), que
    # hacia reportar 47.99 como precio de una Switch 2 de 499.
    check(
        "carrusel p13n de Amazon se descarta",
        _extract_price(page(
            '<div id="ppd"><h1>Nintendo Switch 2</h1>'
            '<span class="a-price">US$499.00</span></div>'
            '<div class="p13n-carousel"><a class="a-link-normal" href="/dp/OTRO">'
            '<span class="p13n-sc-price">US$47.99</span></a></div>'
        )),
        499.00,
    )
    # Estructura real de WooCommerce: el precio propio fuera de <a>, los
    # relacionados dentro.
    check(
        "relacionados de WooCommerce (dentro de <a>) se descartan",
        _extract_price(page(
            '<div class="summary"><h1>Bulbasaur</h1><p class="price">£63.00</p></div>'
            '<ul class="products"><li><a class="woocommerce-LoopProduct-link" href="/x">'
            '<span class="price">£60.00</span></a></li></ul>'
        )),
        63.00,
    )
    # Lo importante del caso Amazon: si SOLO hay precios de otros productos,
    # devolver None deja que _needs_render dispare el tier headless. Un precio
    # inventado bloquearia el unico camino hacia el correcto.
    check(
        "solo precios en <a> -> None (deja que renderice)",
        _extract_price(page(
            '<h1>Nintendo Switch 2</h1>'
            '<div class="p13n"><a class="a-link-normal" href="/dp/A">'
            '<span class="p13n-sc-price">US$47.99</span></a>'
            '<a class="a-link-normal" href="/dp/B">'
            '<span class="a-price">US$6.47</span></a></div>'
        )),
        None,
    )
    check(
        "el precio propio nunca esta en un <a>: no se descarta de mas",
        _extract_price(page(
            '<div><h1>Producto</h1><span class="price">$88.00</span>'
            '<a href="/envio">Politica de envio</a></div>'
        )),
        88.00,
    )

    print("\n[fragmentos partidos no se fusionan]")
    # Marcado real de Amazon: el precio va partido en spans. Concatenar sin
    # separador daba "$49900" (y en una pagina real, "$499004.00").
    check(
        "precio partido de Amazon (whole/fraction)",
        _extract_price(page(
            '<h1>Nintendo Switch 2</h1>'
            '<span class="a-price"><span class="a-price-symbol">$</span>'
            '<span class="a-price-whole">499</span>'
            '<span class="a-price-fraction">00</span></span>'
        )),
        499.00,
    )
    check(
        "simbolo en un span aparte (WooCommerce) sigue bien",
        _extract_price(page(
            '<h1>Bulbasaur</h1><p class="price"><span class="amount">'
            '<span class="currencySymbol">£</span>63.00</span></p>'
        )),
        63.00,
    )

    print("\n[tabla comparativa: <td> planos, sin link ni palabras de upsell]")
    # "Compara con articulos similares" de Amazon: precios de rivales en una
    # tabla. Nada en el texto ni en las clases los delata — solo la estructura.
    check(
        "tabla comparativa se descarta",
        _extract_price(page(
            '<div id="ppd"><h1>Nintendo Switch 2</h1></div>'
            '<table class="a-bordered"><tr><td>'
            '<span class="a-color-price">US$6.47</span></td>'
            '<td><span class="a-color-price">US$330.50</span></td></tr></table>'
        )),
        None,
    )
    check(
        "el precio propio le gana a la tabla comparativa",
        _extract_price(page(
            '<div id="ppd"><h1>Nintendo Switch 2</h1>'
            '<div id="corePrice_feature_div"><span class="a-price">US$499.00</span></div></div>'
            '<table class="a-bordered"><tr><td>'
            '<span class="a-color-price">US$6.47</span></td></tr></table>'
        )),
        499.00,
    )
    # Regresion critica: un umbral de "distancia maxima al h1" habria borrado
    # el precio REAL de Amazon, que esta a 21 pasos del titulo mientras la
    # basura de la tabla esta a 27. La distancia solo rankea; nunca descarta.
    check(
        "un precio real lejano (dist ~21, como Amazon) NO se descarta",
        _extract_price(page(
            "<div><div><div><div><div><div><div><div><div><div>"
            '<div id="corePrice_feature_div"><span class="a-price">US$499.00</span></div>'
            "</div></div></div></div></div></div></div></div></div></div>"
            "<div><div><div><div><div><div><div><div><div><div>"
            "<h1>Nintendo Switch 2</h1>"
            "</div></div></div></div></div></div></div></div></div></div>"
        )),
        499.00,
    )


def test_block_detection() -> None:
    print("\n[deteccion de anti-bot]")
    for title in ("Attention Required! | Cloudflare", "Just a moment...",
                  "Client Challenge", "Robot Check", "Access Denied"):
        check(f"bloqueo: {title}", _looks_blocked(f"<html><head><title>{title}</title></head></html>"), True)
    for title in ("Bulbasaur - ScrapeMe", "BILLY Bookcase, white",
                  "Boxy Heavyweight Crew T-Shirt 5-Pack | Hollister"):
        check(f"legitimo: {title[:28]}", _looks_blocked(f"<html><head><title>{title}</title></head></html>"), False)
    check("captcha en el body no es bloqueo",
          _looks_blocked("<html><head><title>Nintendo Switch 2</title></head>"
                         "<body>captcha access denied</body></html>"), False)
    check("sin title", _looks_blocked("<html><body>x</body></html>"), False)


def test_image_upgrade() -> None:
    print("\n[imagenes: full-res en Amazon]")
    base = "https://m.media-amazon.com/images/I/61abcXYZ"
    check("quita el token de tamano (_AC_SX466_)",
          _upgrade_image_url(f"{base}._AC_SX466_.jpg"), f"{base}.jpg")
    check("miniatura chica (_SS40_)",
          _upgrade_image_url(f"{base}._SS40_.jpg"), f"{base}.jpg")
    check("varios modificadores (_SX300_SY300_)",
          _upgrade_image_url(f"{base}._AC_SX300_SY300_.jpg"), f"{base}.jpg")
    check("id con + y - se conserva",
          _upgrade_image_url("https://m.media-amazon.com/images/I/71pG+ab-L._AC_SL1500_.jpg"),
          "https://m.media-amazon.com/images/I/71pG+ab-L.jpg")
    check("otro host de Amazon (ssl-images)",
          _upgrade_image_url("https://images-na.ssl-images-amazon.com/images/I/81x._SS40_.jpg"),
          "https://images-na.ssl-images-amazon.com/images/I/81x.jpg")
    check("descarta query de tamano",
          _upgrade_image_url(f"{base}._AC_SX466_.jpg?x=1"), f"{base}.jpg")
    # No debe tocar lo que ya es full-res ni URLs de otros sitios.
    check("ya full-res: intacta", _upgrade_image_url(f"{base}.jpg"), f"{base}.jpg")
    check("no-Amazon: intacta",
          _upgrade_image_url("https://scrapeme.live/wp-content/uploads/001.png"),
          "https://scrapeme.live/wp-content/uploads/001.png")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    test_price_parsing()
    test_price_cascade()
    test_jsonld()
    test_upsell_context()
    test_block_detection()
    test_image_upgrade()

    print("\n" + "=" * 50)
    if _failures:
        print(f"{len(_failures)} FALLOS:")
        for name in _failures:
            print(f"  - {name}")
        return 1
    print("TODO PASA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
