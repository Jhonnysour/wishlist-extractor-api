# Cambios Realizados

---

## 2026-07-15 — PoC: Web Scraper asincrono
- **Que se hizo:** Se creo el extractor de productos de e-commerce. Funcion asincrona `extract_product_data(url)` con httpx + BeautifulSoup. Implementa cascada de extraccion de imagenes (JSON-LD > OpenGraph > img tags), titulo (og:title > title) y precio (og:price:amount). User-Agent Chrome/Win, follow_redirects, max 10 imagenes, filtro anti-logos/icons/avatars. Bloque `__main__` con test a scrapeme.live.
- **Archivos:** poc/extractor.py (nuevo), poc/__init__.py (nuevo)

---

## 2026-07-15 — API inicial con memoria (v1, reemplazada despues)
- **Que se hizo:** Se creo main.py con FastAPI usando tasks_db en memoria. Endpoints POST /api/v1/items (202) y GET /api/v1/items/{task_id}. BackgroundTasks con extract_product_data. Schemas inline: UrlInput y TaskResponse.
- **Archivos:** main.py (creado, luego reemplazado)

---

## 2026-07-15 — Arquitectura modular con SQLAlchemy 2.0 async + PostgreSQL
- **Que se hizo:** Reestructuracion completa del proyecto a arquitectura modular:

  - **app/core/database.py:** Engine async con create_async_engine (asyncpg), async_sessionmaker, DeclarativeBase, get_db() generator. DATABASE_URL desde .env con fallback.
  - **app/models/item.py:** Modelo Item con Mapped/mapped_column (SQLAlchemy 2.0). UUID PK con gen_random_uuid(), ARRAY(String) para images, Numeric(10,2) para price, status PENDING/COMPLETED/FAILED, created_at con timezone.
  - **app/schemas/item.py:** UrlInput (url: str) y ItemResponse con from_attributes=True.
  - **app/api/endpoints.py:** Router con POST /items (202 + background scraping con sesion DB propia) y GET /items/{item_id} (404 si no existe).
  - **main.py:** Simplificado a carga de .env, instancia FastAPI, include_router en /api/v1.
  - Se instalo asyncpg, python-dotenv (ya existian SQLAlchemy, FastAPI, uvicorn).
- **Archivos:** app/__init__.py (nuevo), app/core/__init__.py (nuevo), app/core/database.py (nuevo), app/models/__init__.py (nuevo), app/models/item.py (nuevo), app/schemas/__init__.py (nuevo), app/schemas/item.py (nuevo), app/api/__init__.py (nuevo), app/api/endpoints.py (nuevo), main.py (modificado)

---

## 2026-07-15 — Modelo User + relacion 1:N con Item + registro
- **Que se hizo:** 
  - **app/models/user.py:** Modelo User con id (UUID), email (unique), username (unique), created_at, relacion items con cascade="all, delete-orphan".
  - **app/models/item.py:** Agregado user_id FK (users.id, ON DELETE CASCADE, nullable) y relacion owner back_populates="items".
  - **app/schemas/user.py:** UserCreate con EmailStr + username, UserResponse con from_attributes=True.
  - **app/api/endpoints.py:** Nuevo POST /users (201) con manejo de IntegrityError (400 si duplicado). Se instalo email-validator + dnspython.
- **Archivos:** app/models/user.py (nuevo), app/schemas/user.py (nuevo), app/models/item.py (modificado), app/api/endpoints.py (modificado)

---

## 2026-07-15 — Autenticacion JWT con Supabase
- **Que se hizo:**
  - **app/core/security.py:** Creado con get_current_user (decode JWT HS256, extrae sub, busca User en DB), HTTPBearer scheme, SUPABASE_JWT_SECRET desde .env.
  - **app/api/endpoints.py:** Protegidos POST /items y GET /items/{item_id} con current_user: User = Depends(get_current_user). El POST asigna user_id=current_user.id al crear el item.
  - Se instalo PyJWT.
- **Archivos:** app/core/security.py (nuevo), app/api/endpoints.py (modificado)

---

## 2026-07-15 — Passwords encriptados (bcrypt) + endpoint de login
- **Que se hizo:**
  - **app/schemas/user.py:** Agregado password: str a UserCreate. UserResponse sin cambios (nunca expone contraseña).
  - **app/models/user.py:** Agregada columna hashed_password: Mapped[str] (nullable=False).
  - **app/core/security.py:** Agregado pwd_context (CryptContext bcrypt), verify_password, get_password_hash, create_access_token (JWT 24h exp), OAuth2PasswordBearer (tokenUrl=/api/v1/login).
  - **app/api/endpoints.py:** POST /users ahora hashea contraseña con get_password_hash antes de guardar. Nuevo POST /login con OAuth2PasswordRequestForm, verify_password, retorna access_token + token_type.
  - Se instalo bcrypt 4.0.1 (compatible con passlib 1.7.4), python-multipart (requerido por OAuth2 form data).
- **Archivos:** app/schemas/user.py (modificado), app/models/user.py (modificado), app/core/security.py (modificado), app/api/endpoints.py (modificado)

---

## 2026-07-15 — Reglas de opencode: documentacion automatica de cambios
- **Que se hizo:** Se creo la configuracion de reglas para que los agentes de IA documenten automaticamente los cambios tras cada prompt.
  - **opencode.json:** Config del proyecto con $schema e instructions apuntando a INSTRUCTIONS.md.
  - **INSTRUCTIONS.md:** Regla que define el formato y obligacion de registrar cambios en Cambios_Realizados.md.
  - **Cambios_Realizados.md:** Bitacora inicial de cambios del proyecto.
- **Archivos:** opencode.json (nuevo), INSTRUCTIONS.md (nuevo), Cambios_Realizados.md (nuevo)

---

## Resumen de endpoints activos

| Metodo | Ruta | Auth | Status |
|--------|------|------|--------|
| POST | /api/v1/users | Publico | 201 |
| POST | /api/v1/login | Publico | 200 |
| POST | /api/v1/items | Bearer JWT | 202 |
| GET | /api/v1/items/{item_id} | Bearer JWT | 200 |

## Stack de dependencias

fastapi, uvicorn, httpx, beautifulsoup4, sqlalchemy (async), asyncpg, pydantic v2, python-dotenv, PyJWT, passlib (bcrypt 4.0.1), python-multipart, email-validator

---

## 2026-07-15 — Scraping universal: extractor reescrito
- **Que se hizo:** Se reescribio poc/extractor.py con enfoque de scraping universal para funcionar con tiendas reales (Hollister, etc.):
  - Headers completos de navegador real (Chrome/Win) con Accept-Language, Sec-Ch-Ua, etc.
  - Timeout de 15s en httpx.AsyncClient.
  - Titulo: og:title > twitter:title > <title> > <h1>.
  - Imagenes: og:image como prioridad > JSON-LD Product > <img> tags con filtro anti-logos/icons/placeholders, con resolucion absoluta de URLs.
  - Precio: meta product:price:amount > itemprop="price" > regex heuristica en elementos con clase/id "price"/"amount".
  - domain_source extraido con urllib.parse desde la URL.
  - Si la peticion falla o da timeout, retorna dict con campos en None en vez de lanzar excepcion.
  - Nuevo campo `domain_source` en el dict de respuesta.
- **Archivos:** poc/extractor.py (reescrito)

---

## 2026-07-15 — Migracion a Playwright para Client-Side Rendering
- **Que se hizo:** Se reescribio poc/extractor.py para usar Playwright asincrono en lugar de httpx:
  - `async_playwright()` lanza Chromium headless con contexto realista (user-agent Chrome/Win, viewport 1920x1080, locale en-US).
  - `page.goto(url, wait_until="domcontentloaded", timeout=15000)` renderiza el JS antes de extraer.
  - `page.content()` obtiene el HTML final; BeautifulSoup parsea igual que antes.
  - Las funciones de extraccion (_extract_title, _extract_images, _extract_price) se mantienen sin cambios.
  - try/except retorna dict con None si Playwright falla (timeout, deteccion, etc.).
  - app/api/endpoints.py ya usaba `await extract_product_data(url)` — no requirio cambios.
  - Se instalo playwright 1.61.0 + chromium 1228.
- **Archivos:** poc/extractor.py (reescrito)

---

## 2026-07-15 — Revertido Playwright, vuelta a httpx
- **Que se hizo:** Se revirtio toda la migracion a Playwright debido a incompatibilidad con Python 3.14 en Windows (`NotImplementedError` en `create_subprocess_exec` con `ProactorEventLoop`). El proyecto vuelve a usar httpx para las peticiones HTTP:
  - **poc/extractor.py:** restaurado a version "scraping universal" con httpx, headers de Chrome real, timeout 15s, cascada de extraccion og/twitter/JSON-LD/img/heuristicas, domain_source con urlparse.
  - **main.py:** revertido a version simple sin lifespan (sin init/shutdown de browser).
  - **app/api/endpoints.py:** revertido background task a version original (sin validacion de datos nulos ni domain_source).
  - **Eliminado run.py:** ya no necesario.
  - Playwright permanece instalado en venv para uso futuro cuando se resuelva la compatibilidad con Python 3.14.
- **Archivos:** poc/extractor.py (revertido), main.py (revertido), app/api/endpoints.py (revertido), run.py (eliminado)

---

## 2026-07-16 — Fase 1: Scraper robusto de dos niveles (httpx + Playwright fallback)
- **Que se hizo:** Se destrabó el scraping headless y se robusteció el extractor.
  - **Entorno:** proyecto bajado a **Python 3.12** (winget `Python.Python.3.12`), venv recreado. Playwright async ya funciona en Windows (resuelto el `NotImplementedError` de Python 3.14). Verificado con smoke test de Chromium.
  - **requirements.txt (nuevo):** dependencias directas fijadas (fastapi, uvicorn, sqlalchemy, asyncpg, httpx, beautifulsoup4, lxml, playwright, pydantic, PyJWT, passlib, bcrypt, python-multipart, email-validator, python-dotenv). Paso `playwright install chromium` documentado.
  - **poc/extractor.py (refactor):** extracción en **dos niveles**. Nivel 1 httpx (HTML crudo); si faltan precio o imágenes (señal de render en cliente) o el fetch falla, Nivel 2 renderiza con Chromium headless (`wait_until="networkidle"`) y reutiliza la misma cascada de parseo. Navegador **compartido** vía `_BrowserManager` (singleton, lazy-start + lock), `asyncio.Semaphore(3)` para limitar renders concurrentes, contexto nuevo por scrape. Nuevo `_extract_description` (og:description > twitter:description > meta description). `extract_product_data` ahora devuelve `description` y un `status` explícito (`ok` / `no_data` / `fetch_error`). CLI acepta URL por argumento.
  - **main.py:** `lifespan` que arranca/cierra el browser compartido al iniciar/parar la app (pre-warm).
  - **app/api/endpoints.py:** el background task persiste `domain_source` y `description`, y mapea `status=="ok"` → COMPLETED, resto → FAILED (evita items COMPLETED con campos vacíos). El endpoint convierte `HttpUrl` a `str`.
  - **app/schemas/item.py:** `UrlInput.url` ahora es `HttpUrl` (valida y devuelve 422 ante URLs inválidas); `ItemResponse` expone `description` y `domain_source`.
  - **Verificación:** nivel 1 (scrapeme.live), nivel 2 (quotes.toscrape.com/js: 0 vs 10 elementos inyectados por JS), lifespan del browser, esquema de la tabla `items`, y E2E in-process (POST 202 → poll → COMPLETED con title/price/domain_source/images; URL inválida → 422). Datos de prueba limpiados.
- **Archivos:** requirements.txt (nuevo), poc/extractor.py (refactor), main.py (modificado), app/api/endpoints.py (modificado), app/schemas/item.py (modificado)

---

## 2026-07-16 — Matriz de cobertura + 2 bugs del extractor corregidos
- **Que se hizo:** Se creo una herramienta para medir la cobertura real del scraper contra sitios reales, y los datos destaparon dos bugs que se corrigieron:
  - **poc/coverage_matrix.py (nuevo):** corre `extract_product_data` secuencialmente contra una lista de URLs y reporta tabla (dominio, status, tier, title, price, imgs, segundos) + resumen. Uso: `python -m poc.coverage_matrix [archivo.txt]`.
  - **poc/test_urls.txt (nuevo):** lista semilla editable con categorias: controles (scrapeme, books/quotes.toscrape), Shopify (allbirds, deathwishcoffee), retail (IKEA), SPA (Apple), anti-bot duro (Amazon, Nike, Hollister).
  - **poc/extractor.py:** nuevo campo `tier` en el resultado (`static` / `rendered` / `none`) para saber que nivel hizo el trabajo.
  - **Bug 1 (brotli):** los headers anuncian `Accept-Encoding: br` pero el venv no tenia el paquete `brotli`; httpx entregaba bytes sin descomprimir y el nivel 1 parseaba basura silenciosamente en sitios que responden brotli (books.toscrape, muchos con Cloudflare). Fix: instalado `brotli==1.2.0` y agregado a requirements.txt.
  - **Bug 2 (networkidle):** `wait_until="networkidle"` nunca se asienta en sitios con beacons persistentes (IKEA daba fetch_error a los 20s). Fix: `domcontentloaded` + settle de 2.5s.
  - **Resultado (IP residencial):** 6/10 ok — scrapeme y books (static), IKEA con precio correcto $79 (rendered), Apple (rendered), Amazon y Nike con precios correctos (static). Bloqueados por anti-bot: allbirds/deathwishcoffee (429 Shopify). Hollister portada = sin datos de producto (esperado, no es pagina de producto). Caveat: en Apple el precio heuristico saco 129.00 (accesorio/financiamiento, no el precio del Mac).
- **Archivos:** poc/coverage_matrix.py (nuevo), poc/test_urls.txt (nuevo), poc/extractor.py (modificado), requirements.txt (modificado)

---

## 2026-07-16 — Precio desde JSON-LD + stealth + deteccion de bloqueo
- **Que se hizo:** Mejoras de precision del extractor guiadas por la matriz de cobertura.
  - **Helpers JSON-LD reutilizables:** `_iter_jsonld_blobs` (aplana wrappers `@graph`) e `_iter_jsonld_products`. `_extract_images` los reutiliza en vez de duplicar el parseo, y ahora soporta `ImageObject` (dict con url/contentUrl) ademas de strings.
  - **Precio desde JSON-LD `Product.offers`** (`_extract_price_jsonld`): maneja Offer simple, lista de Offers, AggregateOffer (`lowPrice`) y offers anidados. Nueva cascada de precio: meta explicito (product:price:amount / og:price:amount) > **JSON-LD offers** > itemprop=price > twitter:data1 > heuristica por clase/id. `twitter:data1` se bajo de prioridad por ser un slot generico (a veces trae envio o rating).
  - **Resultado:** Apple MacBook Air paso de **129.00 (precio de un accesorio) a 1299.00 correcto**, y ademas se resuelve por tier `static` en ~1.3s en vez de renderizar.
  - **Stealth de Playwright:** `LAUNCH_ARGS` (`--disable-blink-features=AutomationControlled`) + `STEALTH_INIT_SCRIPT` que parcha navigator.webdriver/plugins/languages y window.chrome; contexto con timezone y Accept-Language. **Verificado que aplica** (webdriver True→None, plugins 0→5, window.chrome presente), pero **NO rescato ningun sitio bloqueado**: los 403 de Cloudflare/Shopify llegan a nivel de red/IP antes de que corra el JS, asi que el stealth (que solo oculta señales visibles desde JS) no los toca. Se mantiene por ser gratis y util contra fingerprinting JS.
  - **Nuevo status `blocked`** (`_looks_blocked` + `BLOCK_TITLE_SIGNATURES`): detecta interstitials anti-bot por el `<title>` (Cloudflare "Attention Required"/"Just a moment", Amazon "Robot Check", PerimeterX, etc.) y por HTTP 403/429. Antes una pagina de bloqueo se contaba como `no_data` porque tenia `<title>` — la matriz no distinguia "el sitio no sirve" de "te bloquearon". Los fetchers ahora devuelven `(html, blocked)`.
  - **Hallazgo importante:** IKEA funciono en la primera corrida (precio 79.00) y despues empezo a dar 403 Cloudflare — **el scrapeo repetido de la matriz quemo la IP**. Verificado A/B que no fue culpa del stealth (403 identico con y sin el).
  - **Matriz final (11 URLs, IP residencial):** 6 ok / 3 blocked (allbirds, deathwishcoffee, ikea — todos por rate-limit acumulado) / 2 no_data / 0 fetch_error. Pendientes conocidos: Amazon saca titulo+10 imagenes pero no precio; Hollister solo titulo; el precio de Apple MacBook Pro varia entre corridas (1999 vs 2999 — la pagina lista varias configuraciones).
  - **Tests:** 16 casos de variantes JSON-LD (incluye el caso "JSON-LD gana a heuristica" que reproduce el bug de Apple) y 8 de deteccion de bloqueo (incluye no marcar como bloqueo una pagina legitima que mencione "captcha").
- **Archivos:** poc/extractor.py (modificado), poc/coverage_matrix.py (modificado)

---

## 2026-07-16 — Correccion: deteccion de bloqueo incompleta + stealth menos ingenuo
- **Que se hizo:** El usuario aporto una corrida previa (con su lista de URLs, antes de los cambios de stealth/JSON-LD) donde salian **10/11 ok**, incluido **hollister con precio 89.95** y amazon 47.99 — contra 6/11 de la corrida posterior. Se investigo la aparente regresion:
  - **Hipotesis descartada (stealth):** se hizo A/B real de Hollister con stealth ON vs OFF. **Resultado identico**: HTTP 200 con una pagina de 3105 bytes titulada **"Client Challenge"** (interstitial anti-bot de Radware/Akamai), sin precio, sin JSON-LD, sin errores JS. El stealth NO causo la regresion. Igual A/B previo en IKEA (403 Cloudflare identico con y sin stealth).
  - **Causa real:** degradacion de reputacion de IP por scrapeo repetido (3 corridas de la matriz en pocos minutos + diagnosticos). Los sitios que funcionaban en la primera pasada empezaron a responder con challenges.
  - **Bug real encontrado gracias al reporte:** `BLOCK_TITLE_SIGNATURES` no incluia "client challenge", asi que Hollister se etiquetaba `no_data` ("el sitio no tiene datos") cuando en realidad era `blocked` ("te bloquearon") — diagnostico enganoso. Agregadas firmas: client challenge, checking your browser, request unsuccessful (Incapsula), are you a robot, 403 forbidden. Verificado: Hollister ahora reporta `status=blocked`.
  - **Stealth menos ingenuo:** se quito el parche `navigator.plugins = [1,2,3,4,5]`. Chrome real expone objetos `Plugin`, no enteros: el array falso es en si una firma de stealth conocida y delata mas que una lista vacia honesta. Se conservan webdriver/languages/window.chrome, ahora envueltos en try/catch (el init script corre en cada frame, incluidos iframes donde esas APIs pueden faltar, y no debe perturbar la pagina).
  - **poc/coverage_matrix.py:** pausa configurable entre peticiones (`--delay`, default 3s) y advertencia en el docstring de que correr la matriz repetidamente envenena sus propios resultados.
  - **Lectura correcta:** la corrida del usuario (10/11, IP fresca) es el baseline real de lo que el scraper logra; los `blocked` son un veredicto sobre la reputacion reciente de la IP, no sobre el scraper. La mejora de JSON-LD sigue siendo valida y ortogonal (en esa misma corrida apple daba 129.00 incorrecto; ahora da 1299.00).
  - **NOTA:** la causa raiz real se identifico despues (ver entrada siguiente) — era la VPN, no el rate-limiting.
- **Archivos:** poc/extractor.py (modificado), poc/coverage_matrix.py (modificado)

---

## 2026-07-16 — Causa raiz real de los "blocked": la IP (VPN vs residencial)
- **Que se hizo:** El usuario revelo la causa real de la discrepancia 10/11 vs 6/11: **necesita la VPN encendida para usar Claude, pero la apago para acceder a Hollister**. Mis dos diagnosis previas (stealth, luego rate-limiting) eran incorrectas.
  - **La variable era la IP, no el codigo:** los anti-bot (Cloudflare, Akamai/Radware, PerimeterX) filtran por reputacion de IP antes de mirar el request. VPN = IP de datacenter = challenge. Sin VPN = IP residencial = pasa. Mismo codigo, mismas URLs: **VPN off -> 10/11 ok** (Hollister $89.95) / **VPN on -> 6/11, resto blocked**.
  - **Implicacion clave (la mas importante del proyecto):** la VPN es un **preview gratis de produccion**. Railway/AWS/Render tambien son IPs de datacenter, asi que la corrida "mala" (6/11) es el pronostico realista del scraping server-side en produccion, y la "buena" (10/11) es lo que veria el telefono del usuario. Es decir, ya tenemos medido el A/B de las dos arquitecturas: **scraping desde servidor = 6/11, scraping desde el movil (Capa 0) = 10/11**. La Capa 0 deja de ser teoria.
  - **poc/coverage_matrix.py:** nueva flag `--label` para etiquetar cada corrida (la salida avisa "[unlabeled — which IP? VPN on/off?]" si falta). Docstring reescrito explicando que la IP decide el resultado, con los dos numeros medidos y que significa cada escenario (residencial ~= telefono del usuario; datacenter ~= servidor cloud). El aviso de `blocked` ahora dice que juzga a la IP, no al scraper.
  - **Protocolo de medicion:** el usuario corre la matriz con VPN off (escenario telefono); Claude la corre con VPN on (escenario servidor cloud). No se le puede pedir apagar la VPN para que Claude pruebe: perderia la conexion.
- **Archivos:** poc/coverage_matrix.py (modificado)

---

## 2026-07-16 — Precios equivocados: 3 bugs (regex, parser, upsell) + suite de tests
- **Que se hizo:** Corrida del usuario con VPN off: **10/11 ok, 0 blocked** (confirma que los "blocked" eran la VPN). Reporto un unico error real: Amazon Switch 2 devolvia **47.99** (plan de proteccion) en vez de **499.00**. Investigarlo destapo tres bugs, dos de ellos graves y silenciosos:

  - **BUG 1 — la regex truncaba precios de 4 cifras (grave).** `\d{1,3}(?:[,.]\d{3})*` capturaba solo `$129` de `$1299.00`. Cualquier precio >= 1000 sin coma de miles se reportaba con sus 3 primeros digitos, **sin error, con un numero plausible**. Fix: `_PRICE_NUMBER` con dos ramas (agrupada `1,234.56` / plana `1299.00`).
    - **CORRECCION DE UN DIAGNOSTICO PREVIO:** el "bug de Apple" (129.00) que se documento antes como "precio de un accesorio/financiamiento" **era en realidad esta truncacion de $1299.00**. JSON-LD no lo arreglo: lo esquivo, dejando el bug vivo para cualquier sitio sin JSON-LD.
  - **BUG 2 — `_clean_price_string` leia la coma de miles como decimal (grave).** `"2,999"` -> `"2.999"` -> `round()` -> **3.0**. Fix: cuando hay un solo tipo de separador, se decide por el numero de digitos a la derecha (3 = miles, 1-2 = decimal) y por la cantidad de separadores.
  - **BUG 3 — la heuristica no distinguia el precio del producto de un upsell.** El scoring era codigo muerto (`score = 2 if ... else 1` con un filtro previo que ya garantizaba el match, asi que todo sacaba 2 y el sort no ordenaba nada): devolvia el primer precio del DOM, fuera del producto o de un plan de proteccion. Fix: `PRICE_NEGATIVE_CONTEXT` (bilingue EN+ES, porque Amazon sirve /-/es/) + `_has_upsell_context` que revisa clase/id propios y de hasta 4 ancestros, y el texto de wrappers cortos. Los candidatos en contexto de upsell solo se usan como ultimo recurso.
    - Sub-bug encontrado durante el desarrollo: el paseo por ancestros llegaba hasta `<body>`, cuyo texto contiene los upsells de secciones **hermanas**, marcando como upsell **el precio correcto**. Peor: hacia que un test pasara por la razon equivocada. Fix: cortar en body/html.

  - **poc/test_extractor.py (nuevo):** suite permanente sin dependencias (`python -m poc.test_extractor`), 48 casos: parseo de precios (US/EU/miles/millones/centimos), cascada de prioridad, variantes de JSON-LD, contexto de upsell y deteccion de anti-bot. Motivada por que estos fallos son **silenciosos**: devuelven un numero creible y llegan a la wishlist del usuario. Incluye tests de regresion explicitos para los 3 bugs.
  - **Nota:** no se pudo reproducir la pagina del usuario — la VPN sale por Canada y Amazon sirve otra tienda (precios en CAD, sin `#corePrice_feature_div`). Los fixes se validaron con mocks que replican la estructura reportada (incluido el español de la captura).
- **Archivos:** poc/extractor.py (modificado), poc/test_extractor.py (nuevo)

---

## 2026-07-16 — Ranking por cercania al h1 + fix de falsos positivos del filtro upsell
- **Que se hizo:** Corrida del usuario post-fix con VPN off: **10/11 ok, 9/11 con precio**, Apple 1299/2999 correctos (confirma los fixes de regex y parser), IKEA 79, Hollister 89.95, Nike 97.97. Pero **Amazon paso de 47.99 a 6.47** — seguia equivocado. Se creo `poc/debug_price.py` para diagnosticar con hechos en vez de suposiciones, y destapo dos problemas:

  - **BUG — el filtro upsell marcaba TODO, incluido el precio real.** WooCommerce pone la clase **`shipping-taxable`** en el contenedor principal del producto; buscar `shipping` en class/id marcaba el precio correcto como si fuera un envio. En scrapeme.live los 100% de candidatos salian `upsell=SI` y la funcion devolvia el primero del DOM: acertaba **por accidente**. En Amazon el primero del DOM es un patrocinado -> 6.47. Fix: separar `UPSELL_TEXT_RE` (texto visible, prosa escrita para humanos: fiable) de `UPSELL_ATTR_RE` (class/id: estructural y ruidoso, solo terminos inequivocos; `shipping`/`delivery` quedan como solo-texto).

  - **MEJORA — ranking por cercania al `<h1>` en vez de "el primero gana".** El diagnostico mostro la señal: en una pagina WooCommerce el precio real esta a **distancia 2** del h1 y los "productos relacionados" a **7-8**. El precio de un producto vive pegado a su titulo; los upsells, anuncios y relacionados viven lejos. `_h1_depth_map` + `_distance_to_h1` calculan la distancia por el ancestro comun. `_extract_price` ahora ordena los candidatos por `(es_upsell, distancia_al_h1, orden_dom)` en vez de devolver el primero no marcado. Es **seleccion positiva** ademas de filtrado, y sobre todo **degrada con gracia**: si el filtro upsell se equivoca, la distancia sigue eligiendo bien, en vez de caer al precipicio de "devuelve el primero".

  - **poc/debug_price.py (nuevo):** diagnostico de una URL (`python -m poc.debug_price <url> --expect 499`). Imprime que devuelve cada nivel de la cascada, los candidatos con su valor/distancia-al-h1/veredicto-upsell/ubicacion en el DOM, y donde vive un precio esperado. Existe porque el desarrollo se hace desde una VPN a la que Amazon le sirve otra tienda: la evidencia la tiene que producir quien ve la pagina real. Reutiliza las funciones del extractor (no las duplica), asi que refleja exactamente su comportamiento.
  - **Tests:** +3 de regresion (clase `shipping-taxable` no marca el precio real; la cercania al h1 le gana al orden del DOM; los relacionados no le ganan al producto). Total 55, todos pasan.
- **Archivos:** poc/extractor.py (modificado), poc/debug_price.py (nuevo), poc/test_extractor.py (modificado)

---

## 2026-07-16 — Regla: un precio dentro de un `<a>` es de OTRO producto
- **Que se hizo:** El usuario corrio `poc/debug_price.py` contra la Switch 2 (VPN off) y la salida resolvio el caso con hechos:
  - **El precio real NO esta en el HTML estatico.** `--expect 499` encontro **una sola** aparicion de "499" en 1.5 MB, y era ruido dentro de un `<script>` de telemetria (`window.ue_ibe`). Amazon le sirve a httpx una pagina con titulo, imagenes y carruseles, pero **sin el bloque de precio** — aunque el navegador del usuario si lo ve, desde la misma IP residencial. Para Amazon, el tier 1 no puede traer el precio: hace falta el tier headless.
  - **Todos los candidatos eran de otros productos:** los seis a **distancia 26-27** del h1, con clases `p13n-sc-price` (p13n = personalization, los carruseles de "tambien compraron") y **todos dentro de `<a class="a-link-normal">`**.
  - **Nueva regla universal (`_is_inside_link`):** un precio dentro de un `<a>` es el precio de algo a lo que navegarias — una recomendacion, un relacionado, un anuncio. **Una pagina de producto no hipervincula su propio precio.** Confirmado en dos stacks sin relacion: Amazon (`a.a-link-normal`) y WooCommerce (`a.woocommerce-LoopProduct-link`) meten ahi los precios ajenos y dejan el propio fuera de todo `<a>`.
  - **Se descarta, no se rankea abajo** — y esa distincion es el nucleo del bug: al conservar el 47.99 como fallback, ese precio inventado **satisfacia `_needs_render()`** (que solo dispara si falta precio o imagenes), de modo que el tier headless —el unico que podia traer el precio real— **nunca corria**. El precio malo bloqueaba el camino al bueno. Devolver `None` deja que renderice.
  - **poc/debug_price.py:** nueva columna `link` en la tabla de candidatos (fue la pista decisiva, tiene que verse).
  - **Tests:** +4 de regresion con las estructuras reales observadas (carrusel p13n de Amazon; relacionados de WooCommerce; "solo precios en `<a>` -> None para que renderice"; y que un `<a href="/envio">` vecino no descarte de mas). Total 59, todos pasan. scrapeme (63.00) y books (51.77) sin regresion.
  - **Pendiente de verificar por el usuario:** si el tier headless con VPN off consigue el precio real de Amazon (`python -m poc.debug_price <url> --expect 499 --rendered`). Claude no puede: su VPN sale por Canada y Amazon le sirve otra tienda.
- **Archivos:** poc/extractor.py (modificado), poc/debug_price.py (modificado), poc/test_extractor.py (modificado)

---

## 2026-07-16 — Amazon resuelto: reglas estructurales + el umbral de distancia descartado
- **Que se hizo:** El `--rendered` del usuario mostro que el precio tampoco esta en la pagina renderizada (1.67 MB, "499" solo como ruido en un script de telemetria), y que quedaban candidatos ajenos fuera de enlaces: la **tabla comparativa** de Amazon ("compara con articulos similares"), `<td>` planos sin link ni palabras de upsell. Investigando eso se corrigio un error propio y se cerro el caso:

  - **UMBRAL DE DISTANCIA DESCARTADO (casi un desastre).** Se habia añadido `MAX_PRICE_DISTANCE_FROM_H1 = 20` razonando que la basura de Amazon estaba a 26-29. Una corrida de diagnostico revelo que **el precio REAL de Amazon (`#corePrice_feature_div`) esta a distancia 21**, y las variantes a 25-26: el umbral recien escrito **habria borrado el precio correcto**. Real 21-26 vs tabla comparativa 27 exige un umbral exacto al paso — eso no es una heuristica, es superstición. **La distancia solo rankea; nunca descarta.** El comentario en el codigo documenta la trampa para que nadie la reponga.

  - **`_is_other_products_price` (antes `_is_inside_link`):** ahora `<a>` **o** `<table>`. Un precio dentro de un enlace es de algo a lo que navegarias; uno dentro de una tabla es de una grilla comparativa de rivales. El precio propio no es ni hipervinculo ni dato tabular. La evidencia: en la pagina de Amazon **sin** bloque de precio, los **16** candidatos estaban dentro de un `<a>` o de una `<table>` — descartarlos deja cero, que es la respuesta correcta y ademas deja que `_needs_render` dispare el tier headless.

  - **BUG — fusion de digitos entre elementos.** Amazon parte el precio en `<span class="a-price-whole">499</span><span class="a-price-fraction">00</span>`; `get_text(strip=True)` los pega sin separador -> `"$49900"`. En una pagina real produjo **`499004.00`** al fusionar fragmentos vecinos. Fix: `get_text(" ", strip=True)`.

  - **Resultado:** Amazon devuelve **499.00** de forma consistente en las corridas de Claude (2/2), y scrapeme (63.00) y books (51.77) siguen sin regresion. **Nota importante: la respuesta de Amazon varia mucho entre peticiones** (1.5 / 1.66 / 1.77 / 2.05 MB; a veces con bloque de precio, a veces sin el, a veces con JSON-LD). No es "Amazon nunca da el precio" — es una loteria, y por eso hace falta que el fallo (sin precio) sea seguro.
  - **Tests:** 61 en total. Nuevos de regresion: tabla comparativa se descarta; el precio propio le gana a la tabla; **un precio real lejano (dist ~21, como Amazon) NO se descarta** (blinda contra reponer el umbral); precio partido whole/fraction; simbolo en span aparte (WooCommerce).
- **Archivos:** poc/extractor.py (modificado), poc/debug_price.py (modificado), poc/test_extractor.py (modificado)


