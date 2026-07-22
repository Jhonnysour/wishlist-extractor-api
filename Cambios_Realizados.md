# Cambios Realizados

---

## 2026-07-21 — Multiples listas con nombre (agrupar productos) — backend
- **Que se hizo:** El usuario ahora puede tener varias listas con nombre; cada producto pertenece a UNA lista. **Sin borrar la DB** — migracion con backfill.
  - **Migracion 0004_lists** (retrocompatible): crea tabla `lists`, una "Mi lista" por usuario existente, agrega `items.list_id` (FK ON DELETE CASCADE, **nullable** para no romper el codigo desplegado viejo), backfillea cada item a la lista de su dueño, y actualiza el trigger de signup para que cada usuario nuevo nazca con "Mi lista". **Aplicada a prod: 0 items sin list_id, 0 usuarios sin lista.**
  - **Modelos:** `app/models/item_list.py` (ItemList, tabla `lists`), `Item.list_id` + relacion, `User.lists`.
  - **Schemas:** `app/schemas/list.py` (ListCreate/Update/Response con item_count); `UrlInput.list_id` y `ItemResponse.list_id` (opcionales).
  - **Endpoints:** `POST/GET /lists`, `PATCH/DELETE /lists/{id}` (delete = cascade borra items). `POST /items` recibe `list_id` (opcional -> default a la lista mas vieja del usuario). `GET /items?list_id=` filtra por lista. Helpers `_get_owned_list` / `_default_list_id`. Todo con ownership (IDOR -> 404).
  - **Diseño retrocompatible:** `list_id` opcional en POST y nullable en DB -> la app/APK viejos siguen funcionando (sus items caen en "Mi lista") durante el rollout.
  - **Verificado:** E2E 14/14 (crear listas, item con/sin list_id, filtro por lista, item_count, rename, delete-cascade, IDOR).
  - **Pendiente:** frontend (pantalla de listas + wishlist por lista) y el deploy (Manual Deploy en Render trae esto + el fix de /health HEAD).
- **Archivos:** alembic/versions/0004_lists.py, alembic/env.py, app/models/item_list.py, app/models/item.py, app/models/user.py, app/schemas/list.py, app/schemas/item.py, app/api/endpoints.py

---

## 2026-07-18 — Deploy: render.yaml + /health (backend hacia Render, capa gratis)
- **Que se hizo:** Preparar el backend para hostearse en Render con auto-deploy desde GitHub.
  - `main.py`: endpoint `GET /health` (sin auth) -> `{"status":"ok"}` para el health check de Render y el pinger anti-sleep.
  - `render.yaml`: blueprint del servicio web (Python, plan free, `pip install -r requirements.txt` SIN `playwright install`, `uvicorn main:app --host 0.0.0.0 --port $PORT`, healthCheckPath /health, autoDeploy). Los 3 env vars (DATABASE_URL, SUPABASE_JWT_SECRET, SUPABASE_URL) van con `sync:false` -> se cargan como secretos en el dashboard, no en el repo. PYTHON_VERSION 3.12.7.
  - **Deploy ligero a proposito:** sin Chromium en el server (IP de datacenter = bloqueada, como la VPN); el scraping pesado lo cubre la Capa 0 del telefono. El lifespan ya degrada a solo-estatico.
  - `DESPLIEGUE.md`: guia con reparto de tareas (Claude vs usuario) y pasos manuales (Render, GitHub Actions, UptimeRobot).
  - **Verificado:** `/health` -> 200 en el openapi/ASGI.
  - **Sigue (usuario):** crear cuenta Render -> New+ -> Blueprint -> repo -> pegar 3 secretos -> deploy -> pasar la URL.
- **Archivos:** main.py, render.yaml, DESPLIEGUE.md

---

## 2026-07-18 — Editar el titulo del item desde el detalle
- **Que se hizo:** Extension del PATCH parcial para permitir renombrar un item.
  - **Backend:** `ItemUpdate.title` (Optional, `max_length=255`); `PATCH /items/{id}` recorta el titulo, rechaza vacio (400) y aplica el cambio. Verificado E2E: trim OK, vacio->400, >255->422, y `purchased`-only no toca el titulo.
  - **Frontend:** `updateTitle` en repo + controller; en el detalle, un lapiz junto al titulo abre un dialogo con TextField (maxLength 255) -> guarda via PATCH. `flutter analyze` sin issues + smoke test pasa.
- **Archivos backend:** app/schemas/item.py, app/api/endpoints.py · **Frontend:** wishlist_repository.dart, wishlist_providers.dart, item_detail_screen.dart

---

## 2026-07-18 — Curacion de imagenes (opcional, en el detalle) + menos junk de Amazon
- **Que se hizo:** El scraping traia imagenes ajenas al producto (sobre todo en Amazon via Capa 0). En vez de forzar una seleccion en cada alta (friccion), la curacion es **opcional dentro del detalle**: quitar las que no van y elegir portada.
  - **Backend:**
    - `app/schemas/item.py`: `ItemUpdate` ahora es **update parcial** — `purchased` y `images` opcionales (solo se aplica lo enviado).
    - `app/api/endpoints.py`: `PATCH /items/{id}` acepta `images` (subset reordenado, portada primero) y **valida que sea un subconjunto** de las imagenes actuales (400 si hay una URL ajena — evita inyeccion). `purchased` sigue igual via update parcial.
    - `poc/extractor.py`: `_is_relevant_image` descarta imagenes de Amazon que no esten bajo `/images/I/` (deja fotos de producto, quita graficos de sitio `/images/G/`, sprites, badges). Reduce el junk de origen.
  - **Frontend (wishlist-frontend):**
    - `wishlist_repository.dart` + `wishlist_providers.dart`: `updateImages(id, images)` -> PATCH.
    - `item_detail_screen.dart`: accion "Editar imagenes" en el AppBar (solo si COMPLETED con imagenes) -> pantalla editora (grid): toca para quitar/incluir, estrella para portada, "Guardar" persiste el subset reordenado; cancelar no cambia nada.
  - **Verificado:** backend E2E (PATCH subset+reorden -> orden correcto con portada; URL ajena -> 400; `purchased` parcial no toca images; IDOR -> 404; filtro Amazon /images/I/ correcto; extractor sin regresion, scrapeme 7 imgs). Frontend `flutter analyze` sin issues + smoke test pasa. **Pendiente prueba en dispositivo del flujo de edicion.**
- **Archivos backend:** app/schemas/item.py, app/api/endpoints.py, poc/extractor.py · **Frontend:** wishlist_repository.dart, wishlist_providers.dart, item_detail_screen.dart

---

## 2026-07-18 — Mejora: imagenes de Amazon en full-res (no borrosas)
- **Que se hizo:** En la app las imagenes de Amazon se veian borrosas: el extractor tomaba las variantes **miniatura** del carrusel. Amazon codifica el tamano en el nombre del archivo (`/images/I/<id>._AC_SX466_.jpg`); quitando ese segmento `._..._` se obtiene el original en resolucion nativa.
  - `poc/extractor.py`: nuevo `_upgrade_image_url()` (regex sobre el path `/images/I/`, especifico de Amazon -> otras URLs pasan intactas) aplicado a las 3 fuentes de imagenes en `_extract_images` (og:image, JSON-LD, `<img>`). Como corre dentro de `_parse_into`, aplica tanto al scraping normal como a la Capa 0.
  - **Verificado:** 8 casos unitarios nuevos en `poc/test_extractor.py` (quita `_AC_SX466_`/`_SS40_`/multiples modificadores/query; conserva ids con `+`/`-`; no toca URLs ya full-res ni de otros sitios). Suite completa pasa; scrapeme sin regresion.
  - **Nota:** aplica a items NUEVOS; el item ya agregado conserva las URLs viejas (re-agregarlo lo actualiza).
- **Archivos:** poc/extractor.py, poc/test_extractor.py

---

## 2026-07-18 — Fix: backend valida tokens ES256 de Supabase (JWKS) — resuelve el 401
- **Que se hizo:** Se confirmo en dispositivo la contingencia prevista: registro/login OK en Supabase pero `GET /items` daba **401** (el interceptor de Dio cerraba sesion -> volvia al login). Causa: el proyecto firma los access tokens con **signing keys asimetricas (ES256)**, no con el `JWT Secret` compartido (HS256). El JWKS del proyecto (`/auth/v1/.well-known/jwks.json`) confirma una sola clave `alg=ES256, kty=EC, P-256`.
  - `app/core/security.py`: `get_current_user` ahora verifica el token segun su `alg` — `_decode_token` usa `PyJWKClient` (JWKS, cacheado) para ES256/RS256 y el secret compartido para HS256 (fallback). La verificacion (que puede bloquear en el fetch del JWKS en frio) corre via `asyncio.to_thread`.
  - Dependencias: `cryptography` (necesaria para ES256) agregada a requirements; se quitaron `passlib`/`bcrypt` (ya no se usan tras mudar el auth a Supabase). `SUPABASE_URL` agregada a `.env` (y default en codigo) para construir la URL del JWKS.
  - **Verificado de verdad (no simulado):** se creo un usuario real via `POST /auth/v1/signup` con la publishable key -> token ES256 real -> el backend lo verifica y `GET /items` -> **200** (antes 401), `POST /items` -> 202. Usuario de prueba borrado de auth.users + public.users.
- **Archivos:** app/core/security.py, requirements.txt, .env (SUPABASE_URL, no versionado)

---

## 2026-07-18 — Fix: usar publishableKey (clave nueva sb_publishable_) en vez de anonKey
- **Que se hizo:** El proyecto de Supabase del usuario usa el **formato nuevo de API keys** (`sb_publishable_...`), no el anon JWT legacy. `Supabase.initialize` estaba con `anonKey:`, que no corresponde a ese formato -> el login no habria arrancado. Cambiado a `publishableKey:`.
  - Frontend: `env.dart` renombra `supabaseAnonKey`/`SUPABASE_ANON_KEY` -> `supabasePublishableKey`/`SUPABASE_PUBLISHABLE_KEY`; `main.dart` usa `publishableKey:` (se quito el `// ignore: deprecated_member_use`); `widget_test.dart` idem con un `sb_publishable_test`.
  - **Verificado:** `flutter analyze` sin issues; smoke test pasa.
  - **Para correr:** `./run-phone.ps1 --dart-define=SUPABASE_PUBLISHABLE_KEY=sb_publishable_...`
  - **Contingencia conocida (no resuelta, a verificar al probar):** si el proyecto firma los access tokens con signing keys asimetricas (JWKS) en vez del JWT Secret compartido (HS256), el backend (que valida con SUPABASE_JWT_SECRET/HS256) dara 401 aunque el login funcione. Sintoma: login OK pero /items -> 401. Fix pendiente en ese caso: verificar por JWKS en `app/core/security.py`.
- **Archivos:** lib/core/config/env.dart, lib/main.dart, test/widget_test.dart

---

## 2026-07-17 — Fase C: auth consolidada en Supabase Auth — backend + frontend
- **Que se hizo:** Se reemplazo el auth propio (bcrypt + JWT casero, /login + /users) por Supabase Auth. El backend ahora SOLO valida el JWT que emite Supabase; registro/login viven en el cliente.
  - **Migracion 0003_supabase_auth:** DELETE de los usuarios viejos de public.users (sus emails chocarian con los nuevos signups; items en cascada), DROP de `hashed_password`, y 3 objetos: `get_email_by_username(text)` (RPC username->email, para conservar login por username sobre el signInWithPassword de Supabase que es por email), `check_username_available(text)` (pre-chequeo antes de signUp), y trigger `on_auth_user_created` sobre `auth.users` que copia (id,email,username de metadata) a public.users. Ambas funciones SECURITY DEFINER con grant a `anon`. Aplicada; el rol del pooler pudo crear el trigger en auth.users.
  - **Backend:** `security.py` solo conserva `get_current_user` (decodifica el JWT de Supabase con SUPABASE_JWT_SECRET, busca por `sub` en public.users) + HTTPBearer; se borro pwd_context/verify_password/get_password_hash/create_access_token/oauth2_scheme. `endpoints.py`: eliminados POST /users y /login + imports muertos. `models/user.py`: sin `hashed_password`.
  - **Frontend (wishlist-frontend):** `supabase_flutter ^2.8.0`; `main.dart` async con `Supabase.initialize`; `env.dart` con `SUPABASE_URL` (default = URL del proyecto) y `SUPABASE_ANON_KEY` (dart-define); `auth_repository.dart` reescrito (login = rpc get_email_by_username -> signInWithPassword; register = check_username_available -> signUp con username en metadata); `auth_controller.dart` basado en `onAuthStateChange`/`currentSession` (refresh automatico del token gratis); `dio_client.dart` toma el token de `currentSession.accessToken` y en 401 hace signOut. Se borro `token_storage.dart` (huerfano; Supabase persiste su sesion). `widget_test.dart` adaptado (mock de SharedPreferences + Supabase.initialize).
  - **Decisiones del usuario:** login sigue por username (via RPC); confirmacion de email DESACTIVADA en el dashboard para testing (login inmediato tras registro); usuarios viejos borrados.
  - **Verificado:** backend E2E post-migracion (trigger crea public.users; GET/POST /items con token estilo Supabase OK; token mal firmado -> 401; /login -> 404; cleanup de auth.users+public.users). Frontend: `flutter analyze` sin issues; `flutter test` smoke pasa (sin sesion -> pantalla de login). **Pendiente de prueba coordinada en dispositivo:** requiere que el usuario (1) pegue el SUPABASE_ANON_KEY, (2) desactive 'Confirm email' en el dashboard, (3) corra backend `--host 0.0.0.0` + app con `--dart-define=SUPABASE_ANON_KEY=...` y registre/inicie sesion.
- **Archivos backend:** alembic/versions/0003_supabase_auth.py, app/core/security.py, app/api/endpoints.py, app/models/user.py · **Frontend:** pubspec.yaml, lib/main.dart, lib/core/config/env.dart, lib/core/api/dio_client.dart, lib/features/auth/data/auth_repository.dart, lib/features/auth/presentation/providers/auth_controller.dart, (borrado) lib/core/storage/token_storage.dart, test/widget_test.dart

---

## 2026-07-17 — Fase B: Capa 0 (captura por WebView) — backend + frontend
- **Que se hizo:** Fallback para paginas cuyo precio nunca llega a un scraper de servidor (Amazon): la app carga la pagina en un WebView headless y manda el HTML renderizado al backend para re-extraer.
  - **Backend:**
    - `poc/extractor.py`: refactor `_finalize_status(result, blocked, fetched_any)` (extraido de `extract_product_data`, sin cambio de comportamiento) + nueva `extract_from_html(html, url)` sincrona que reusa `_parse_into` y `_finalize_status` (tier="client", sin fetch de red ni "blocked").
    - `app/schemas/item.py`: `ItemFromHtml { html: str }`.
    - `app/api/endpoints.py`: `POST /items/{id}/retry-from-html` — usa `_get_owned_item` (ownership/IDOR cerrado), extrae sincrono, actualiza el item y devuelve el `ItemResponse` (200). "ok"->COMPLETED, resto->FAILED.
  - **Frontend (wishlist-frontend):**
    - `pubspec.yaml`: `flutter_inappwebview ^6.1.5`.
    - `lib/features/webview_capture/data/webview_capture_service.dart`: `HeadlessInAppWebView` (sin UI), UA de Chrome, settle 3s tras onLoadStop, timeout 30s, captura `document.documentElement.outerHTML`.
    - `.../webview_capture_repository.dart`: `retryFromHtml(id, html)` -> POST retry-from-html.
    - `wishlist_providers.dart`: en `_poll`, cuando el item queda FAILED dispara `_captureFallback` (una sola vez por item, guardado con `_capturingIds`). El camino feliz (10/11 sitios) nunca abre el WebView.
  - **Verificado:** backend E2E 10/10 (extract_from_html da 63.0/ok/tier=client; endpoint pasa item a COMPLETED con precio; IDOR de otro user -> 404; HTML basura -> FAILED) + tests unitarios del extractor siguen pasando (refactor sin regresion). Frontend: `flutter pub get` resuelve, `flutter analyze` de los archivos nuevos + integracion sin issues. **Pendiente de prueba en dispositivo/emulador (coordinada):** agregar una URL de Amazon y ver PENDING->FAILED->WebView->COMPLETED con precio real.
- **Archivos backend:** poc/extractor.py, app/schemas/item.py, app/api/endpoints.py · **Frontend:** pubspec.yaml, lib/features/webview_capture/*, wishlist_providers.dart

---

## 2026-07-17 — Fase A: Alembic (migraciones versionadas) adoptado sobre la DB existente
- **Que se hizo:** Se adopto Alembic para versionar el esquema y dejar de aplicar `ALTER TABLE` sueltos a mano.
  - `alembic init -t async` (template async, ya usamos asyncpg). `alembic/env.py` configurado para: cargar `.env`, apuntar `target_metadata` a `Base.metadata`, importar los modelos (item, user), tomar `DATABASE_URL` del entorno, y usar `connect_args={"statement_cache_size": 0}` como la app (pooler de Supabase). `compare_type=False` a proposito: String sin longitud vs TEXT/VARCHAR daba falsos "type change" en cada autogenerate.
  - **Baseline en 2 migraciones:** `0001_baseline` = create_table de users+items **fiel a la DB actual** (para que el `stamp` sea no-op real y una DB desde cero reproduzca el esquema). `0002_items_notnull` = `SET NOT NULL` en `items.images` y `items.status` — drift real (la app siempre los llena, pero estaban nullable; 0 filas con NULL, seguro). Primer cambio aplicado 100% via workflow de migracion, sin ALTER manual.
  - **Adopcion:** `alembic stamp 0001_baseline` (la DB ya tenia las tablas) -> `alembic upgrade head` (aplico 0002). `alembic current` = `0002_items_notnull (head)`.
  - **Verificado:** images/status ahora `is_nullable=NO`; un autogenerate de control sale **vacio** (`upgrade()` = solo `pass`) probando que modelos == DB sin drift; el E2E de Fase 3 (19 checks) pasa completo (los inserts respetan el NOT NULL nuevo).
  - **De aqui en mas:** cada cambio de esquema = `alembic revision --autogenerate` + `alembic upgrade head`. Las Fases B y C agregaran migraciones sobre 0002.
- **Archivos:** requirements.txt, alembic.ini, alembic/env.py, alembic/versions/0001_baseline.py, alembic/versions/0002_items_notnull.py

---

## 2026-07-17 — CORS habilitado (desbloquea el frontend Flutter, incl. Web)
- **Que se hizo:** Se agrego `CORSMiddleware` en main.py para que la app Flutter (sobre todo Flutter Web en un navegador) pueda llamar la API.
  - La API es **token-based** (`Authorization: Bearer`), NO usa cookies -> no necesita CORS con credenciales, asi que en dev se permite cualquier origen. `allow_origins` sale de la env `CORS_ORIGINS` (default `*`; en produccion se setea una lista separada por comas). `allow_credentials=False`, `allow_methods=["*"]`, `allow_headers=["*"]`.
  - **Verificado:** preflight `OPTIONS /api/v1/items` -> 200 con `access-control-allow-origin: *`, metodos (incl. PATCH/DELETE) y `authorization` en allow-headers; GET con `Origin` devuelve el header CORS; `/docs` sigue 200.
  - Contexto: se detecto la falta de CORS al preparar el handoff del frontend (el backend ya estaba listo salvo esto). Diferido aparte: Fase 2 (Supabase Auth), Capa 0 (Amazon), cola real/Alembic.
- **Archivos:** main.py (modificado)

---

## 2026-07-17 — Fix: uvicorn --reload rompia el arranque (NotImplementedError de Playwright)
- **Que se hizo:** `uvicorn main:app --reload` fallaba al arrancar con `NotImplementedError` en `create_subprocess_exec` (mismo sintoma que el viejo problema de Python 3.14, pero por otra causa).
  - **Causa raiz (confirmada en el codigo de uvicorn, no adivinada):** `uvicorn/loops/asyncio.py` usa `ProactorEventLoop` en Windows **solo si `use_subprocess` es False**; `--reload` (y `--workers>1`) ponen `use_subprocess=True`, forzando el `SelectorEventLoop`, que en Windows **no puede lanzar subprocesos**. Playwright necesita spawnear el driver del navegador -> revienta. Sin `--reload`, uvicorn usa Proactor y funciona.
  - **main.py:** (1) fija `WindowsProactorEventLoopPolicy` en Windows; (2) el `lifespan` ahora **captura** el fallo de `browser_manager.start()` y sigue arrancando (degrada a solo-estatico con un warning) en vez de tumbar toda la API; (3) `if __name__=="__main__"` con `uvicorn.run(..., reload=False)` para poder correr `python main.py` y que "just works".
  - **Verificado:** sin `--reload` arranca completo con navegador (/docs 200, los 7 endpoints presentes). Con `--reload` ya no se cae: arranca degradado a solo-estatico (imprime un traceback ruidoso de una tarea interna de Playwright, pero "Application startup complete").
  - **Como correr (Windows):** `uvicorn main:app` (sin `--reload`) o `python main.py`. Usar `--reload` deshabilita el tier headless.
- **Archivos:** main.py (modificado)

---

## 2026-07-17 — Fase 3: CRUD de la wishlist (listar, buscar, comprado, borrar) + fix IDOR
- **Que se hizo:** Se completo la funcionalidad de wishlist que faltaba para que la app funcione punta a punta.
  - **Migracion:** `ALTER TABLE items ADD COLUMN purchased boolean NOT NULL DEFAULT false` corrida contra Supabase via script y verificada.
  - **app/models/item.py:** columna `purchased` (Boolean, default false, server_default). Flag ortogonal al `status` del scraping.
  - **app/schemas/item.py:** `ItemResponse` expone `purchased`; nuevo `ItemUpdate` (body del PATCH).
  - **app/api/endpoints.py:**
    - **`GET /items`** — la wishlist del usuario, newest-first. Query params combinables: `q` (busca en titulo OR original_url con ILIKE — el match por URL resuelve el caso Hollister: la camisa cuyo titulo no dice "hollister" pero cuya URL es hollisterco.com), `purchased` (true=comprados / false=pendientes / omitir=todos), `limit`+`offset` con validacion.
    - **`PATCH /items/{id}`** — marca/desmarca comprado.
    - **`DELETE /items/{id}`** — 204.
    - **Fix IDOR:** helper `_get_owned_item` que filtra por `user_id` y da 404 (no 403, para no revelar existencia). Usado por GET-by-id, PATCH y DELETE. Antes `GET /items/{id}` no filtraba por dueño.
  - **Auth:** se mantiene el /login propio (facilita probar en Swagger); migracion a Supabase Auth diferida.
  - **Verificacion:** test E2E in-process (httpx+ASGITransport) con 19 checks, todos pasan: aislamiento por usuario, busqueda por titulo y por URL, case-insensitive, marcar comprado + filtros, combinar q+purchased, IDOR cerrado (GET/PATCH/DELETE de B sobre item de A -> 404 y el item queda intacto), delete propio, paginacion invalida -> 422. Usuarios de prueba borrados al final.
- **Archivos:** app/models/item.py (modificado), app/schemas/item.py (modificado), app/api/endpoints.py (modificado)

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


