# Guía de despliegue — Backend en Render + APK por CI

> Meta: backend **siempre encendido en internet** (Render, capa gratis, auto-deploy desde GitHub)
> y un **APK autónomo** (construido en CI, publicado en un GitHub Release) para usar la app con
> datos/WiFi **sin PC** y poder pasársela a un amigo.
>
> Se despliega **ligero (sin Chromium)**: el server corre desde IP de datacenter (bloqueada por
> muchos sitios), así que el scraping pesado se apoya en la **Capa 0 del teléfono**; el `lifespan`
> del backend ya degrada a solo-estático si no hay navegador.

## Reparto de tareas
| # | Tarea | Quién |
|---|---|---|
| 1 | `render.yaml` + endpoint `/health` en el backend | **Claude** |
| 2 | Crear cuenta en Render y desplegar (blueprint + 3 secretos) | **Tú** (guiado) |
| 3 | Verificar el backend (`/health`, `/docs`) | Claude + Tú |
| 4 | Workflow de GitHub Actions (build + Release del APK) | **Claude** |
| 5 | 2 variables en GitHub Actions (URL de Render + Supabase key) | **Tú** (guiado) |
| 6 | Lanzar build, instalar el APK y probar sin PC | **Tú** |
| 7 | (Opcional) UptimeRobot anti-sleep; pasar APK a un amigo | **Tú** (guiado) |

**Orden importante:** primero el backend (1-3), porque su URL hace falta para el paso 5.

---

## PASO 1 — Claude: archivos en el backend (`wishlist-extractor-api`)
- `render.yaml` (blueprint): servicio web Python, `plan: free`,
  `buildCommand: pip install -r requirements.txt` (SIN `playwright install`),
  `startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT`, `healthCheckPath: /health`,
  env vars `DATABASE_URL` / `SUPABASE_JWT_SECRET` / `SUPABASE_URL` con `sync: false`, `PYTHON_VERSION`.
- Endpoint `GET /health` (sin auth) → `{"status":"ok"}`.
- Commit + push (con tu OK).

## PASO 2 — TÚ: crear cuenta y desplegar en Render
1. **Sí, necesitas una cuenta.** Entra a **render.com** → *Get Started* → **Sign up with GitHub**.
   Autoriza el acceso (puedes limitarlo solo a `wishlist-extractor-api`).
2. Dashboard → **New +** → **Blueprint**.
3. Elige el repo **wishlist-extractor-api**. Render detecta `render.yaml` y muestra el servicio.
4. Pega los 3 secretos (están en tu `.env` local):
   - `DATABASE_URL` → la línea `postgresql+asyncpg://postgres...pooler.supabase.com:6543`.
   - `SUPABASE_JWT_SECRET` → el de tu `.env`.
   - `SUPABASE_URL` → `https://pyvpxqtfikctmslffmvt.supabase.co`.
5. **Apply/Create** → espera el deploy (~2-4 min) → copia la **URL pública**
   `https://<algo>.onrender.com` y **pásamela**.
6. El auto-deploy en cada push queda activo por defecto.

## PASO 3 — Verificar el backend
- Abrir `https://<app>.onrender.com/health` → `{"status":"ok"}`; `/docs` debe cargar.
  (La 1ª petición tras dormirse tarda ~50s — normal en capa gratis.)

## PASO 4 — Claude: workflow del APK en el frontend (`wishlist-frontend`)
- `.github/workflows/build-apk.yml`: en `push` a `main` (+ botón manual) → build de
  `flutter build apk --release` con `--dart-define API_BASE_URL` y `SUPABASE_PUBLISHABLE_KEY`
  desde las *Variables* de Actions → publica `app-release.apk` en un Release (tag `latest`).
- La app ya lee esas variables por `--dart-define`; no cambia código de la app.

## PASO 5 — TÚ: variables en GitHub Actions
Repo **wishlist-frontend** → **Settings → Secrets and variables → Actions →** pestaña **Variables**
→ **New repository variable** (son públicas):
- `API_BASE_URL` = la URL de Render del paso 2.
- `SUPABASE_PUBLISHABLE_KEY` = `sb_publishable_xWUI5jF2S3fwVVgKcfkgdA_3eKImKVw`.

## PASO 6 — TÚ: build, instalar y probar
1. GitHub → pestaña **Actions** → **Run workflow** (o pushea algo).
2. **Releases** del repo → descarga `app-release.apk` en el teléfono (logueado en GitHub) →
   instálalo (activa "instalar apps de esta fuente").
   - **Una sola vez:** desinstala primero la app actual (fue firmada con otra clave debug en tu PC).
3. **Apaga el WiFi / usa datos** → abre la app → regístrate/login → agrega un item (prueba
   Amazon/Capa 0). Debe funcionar sin la PC.

## PASO 7 — TÚ (opcional)
- **Anti-sleep:** UptimeRobot (gratis) → Add Monitor → HTTP(s) → `https://<app>.onrender.com/health`
  cada 5 min.
- **Amigo:** mándale el `app-release.apk` (WhatsApp/Drive); instala, se registra con su cuenta, ve
  solo su lista. (Repo privado = no puede bajar del Release directo.)

---

## Verificación end-to-end
Backend `/health` 200 + `/docs` cargan; app con **datos móviles** (sin PC) registra/login y agrega
items; un 2º teléfono/amigo instala el APK y usa su propia cuenta.

## Fuera de alcance (siguientes pasos posibles)
Keystore de release propio · Firebase App Distribution · reactivar confirmación de email en
Supabase · endurecer CORS · env `ENABLE_BROWSER=false` para saltar el tier render en el server.
