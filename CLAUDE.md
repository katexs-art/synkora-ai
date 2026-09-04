# CLAUDE.md — Katexs Platform (fork of Synkora)

You are editing the **Katexs** product: a white-label AI-agent platform (fork of open-source
Synkora, MIT). This repo = the ENGINE (FastAPI) + the FULL platform UI (Next.js). It is
**LIVE in production** — be careful, follow the deploy rules.

## Production topology
- UI: `https://app.katexs.tech` — Next.js app in `web/` (port 3005 on the VPS host)
- API: `https://api.katexs.tech` — FastAPI in `api/` (Docker container `synkora-api`, port 5001)
- Widget script: `https://app.katexs.tech/widget.js`
- All on VPS `2.24.124.236` under `/opt/synkora-ai` (docker compose stack, 27 services)

## Repo layout (what matters)
- `api/src/controllers/` — FastAPI routes (registered declaratively in `router_registry.py`)
- `api/src/services/` — business logic (`billing/platform_settings_service.py`, `phone/phone_config_service.py`, `agent_api/api_key_service.py`)
- `api/src/models/` — SQLAlchemy models (`agent.py`, `agent_widget.py`, `platform_settings.py`, `phone_*.py`)
- `api/migrations/versions/` — alembic migrations
- `web/app/` — Next.js 15 App Router pages (route groups: `(auth)`, `(dashboard)`, `(public)`)
- `web/components/` — React components (`layout/Sidebar.tsx`, `settings/BrandingCard.tsx`, `agents/platform-engineer/PlatformEngineerPanel.tsx`)
- `web/public/` — static assets served at root: `widget.js`, `logo.png` (black bg), `logo-transparent.png` (white mark on alpha), `widget-demo.html`
- `web/styles/` — Tailwind v3; `globals.css` (base), `katexs-accent.css` (brand-color var mapping — import in `app/layout.tsx`)

## Katexs-custom code (added by us — keep)
- `api/src/controllers/katexs.py` — product endpoints:
  - `POST /api/v1/katexs/auto-build` (business info → creates ACTIVE agent + LLM config + widget, returns preview URL + embed snippet; `lane: chat|voice`, voice lane auto-provisions a Vapi assistant)
  - `GET /api/v1/katexs/stats` · `GET /api/v1/katexs/agents/{id}/embed`
- `platform_settings.py` — branding: `GET/PUT /api/v1/platform-settings/branding`, `GET /api/v1/platform-settings/branding/public` (fields: platform_name, platform_logo_url, support_email, primary_color, secondary_color)
- `widgets.py` — embed generator branded "Katexs AI Chat Widget" + default branding `Powered by Katexs` → `https://katexs.com`
- `web/components/BrandingApplier.tsx` — fetches public branding, sets CSS vars `--k-primary/--k-secondary/--k-logo`, dispatches `katexs:branding` event
- `web/components/settings/BrandingCard.tsx` — admin UI on Settings → Platform
- Sidebar: jet black `#000000`, logo = transparent variant, pinned-open default, NO "Enterprise platform" tag

## Theming system (HOW COLORS WORK)
1. Brand colors persist in the `platform_settings` row (`primary_color`, `secondary_color`).
2. `BrandingApplier` (mounted in root `app/layout.tsx`) applies them as CSS vars on `<html>`.
3. `web/styles/katexs-accent.css` maps Tailwind **emerald** utility classes → `var(--k-primary)` (buttons/links/highlights). Change the mapping there to theme more surfaces.
4. **Theme is LIGHT (original Synkora cream)** — the dark override `katexs-dark.css` exists but is deliberately NOT imported. Do not re-enable without asking the owner.
5. Hardcoded accents still exist in components — search `bg-[#...]` etc. Example: the floating Platform Engineer FAB (bottom-right, every dashboard page) in `PlatformEngineerPanel.tsx` was changed from pink `#ff355d` to blue `#2563eb` — keep blue.

## Widget system (embed on customer sites)
- Snippet format (owner-facing name: "Katexs AI Chat Widget"):
  ```html
  <script src="https://app.katexs.tech/widget.js" async></script>
  <script>window.addEventListener('load', function () { SynkoraWidget.init({ widgetId: '<slug or id>', apiKey: '<plain key>', apiUrl: 'https://api.katexs.tech/api/v1', brandingText: 'Powered by Katexs' }); });</script>
  ```
- JS global MUST stay `SynkoraWidget` (widget.js API contract). Visible strings may say Katexs.
- Widget config: `GET /api/v1/widgets/config` (header `X-Widget-API-Key`) returns agent + theme.
- Per-widget theme (DB `agent_widgets.theme_config`, JSONB) keys: `chat_title`, `chat_primary_color`, `chat_welcome_message`, `chat_placeholder`, `branding_text` (string or `false` to hide), `branding_url`, `privacy_policy_*`, `pre_chat_form`.
- Widget rows: `agent_widgets` table; `allowed_domains` array — empty = allow all; supports `*` and `*.domain`. Update via API `PUT /api/v1/widgets/{id}` or SQL `jsonb_set`.
- Chat runtime: `POST /api/v1/widgets/chat` (SSE). CORS for widgets is validated per key/domain (see `DynamicCORSMiddleware`).
- To restyle the chat UI itself: edit `web/public/widget.js` (shadow DOM; CSS vars `--snkr-c` etc.) — then restart the web server to serve the change.

## API auth
- Console/admin: `POST /console/api/auth/login` → `data.access_token` (JWT) → `Authorization: Bearer`. Refresh cookie is optional. Never use Supabase for this platform's auth.
- Widget/embedded: `X-Widget-API-Key` header with the widget's plaintext key (only shown at creation/regeneration).
- CORS: browser origins must be in `INNER_CORS_ORIGINS` in `api/.env` (comma list; `docker compose up -d api` to apply env changes — `docker restart` does NOT re-read .env).

## Deploy rules (CRITICAL — read before changing anything)
- **Never run `pnpm dev`/`next dev` on port 3005.** Dev mode has a hydration bug → blank pages. Production = `npm run start -- -p 3005` from `web/` with a production build.
- **Never run two web servers.** A stale second server serves chunks as `text/plain` → blank/500 pages. To rebuild+deploy:
  1. `cd web && NEXT_PUBLIC_API_URL=https://api.katexs.tech npm run build`
  2. Kill ALL: `pkill -9 -f 'next-server'; pkill -9 -f 'next start'`; sleep; confirm port 3005 free (`ss -ltn | grep 3005`).
  3. Start ONE: `nohup npm run start -- -p 3005 &` — confirm single process, then test `https://app.katexs.tech/signin` (expect 200, login form visible).
- Files under `web/public/` (widget.js, html, logos) are served from disk but the server snapshots availability at start: after adding/removing public files, restart the web server.
- API edits under `api/src` auto-reload (container runs `uvicorn --reload`, source bind-mounted). `.env` changes need `docker compose up -d api` (recreate).
- Migrations: `cd /opt/synkora-ai && docker compose exec -T api alembic upgrade head`.
- Vapi/phone config uses `APP_BASE_URL` (= https://api.katexs.tech) for webhook URLs. LLM runtime key = `ANTHROPIC_API_KEY` in `api/.env`.

## UI conventions
- Original Synkora cream/light design (dark sidebar `#000`, content cream). New custom UI should match.
- Logo: use `/logo-transparent.png` on dark surfaces; `/logo.png` (black bg) only on light surfaces.
- Verify visual changes with a real browser (screenshots) — many color regressions hide in hardcoded hexes.

## Secrets
- Admin login is NOT in the repo. Server holds it at `/root/.katexs-admin-pw`. Ask the owner.
- Never commit `.env*`, API keys, or tokens. `.env` files are gitignored — keep it that way.

## Owner
Kevin (founder). Voice/chat agents are the product; the current sprint is: brand polish,
widget professionalization, agent auto-build funnel, Vapi voice provisioning, and mirroring
the platform UX on the customer site. Ask before large refactors; ship small verified changes.
