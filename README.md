# Lens — photographer/videographer marketplace + business platform (AU)

The first platform where an Australian client can discover, compare and book a vetted
photographer/videographer — and where that creative runs the whole job (quote → contract
→ payment → shoot → gallery) in one place. Melbourne first.

> "Lens" is the working brand name (set `BRAND_NAME` in `.env` to rename everywhere).

## Stack (build plan §2)
- **Django 5** + **Django REST Framework**
- **HTMX + Alpine.js** for interactivity (no SPA)
- **Tailwind CSS** with the brand palette
- **PostgreSQL + PostGIS** in production; **SQLite** for local dev (default)
- django-allauth (email login) · WhiteNoise (static)

## Brand palette
| Token | Hex | Use |
|---|---|---|
| Navy | `#2F4156` | Headlines, primary buttons, footer |
| Teal | `#567C8D` | Accents, secondary CTAs, links |
| Sky Blue | `#C8D9E6` | Soft fills, badges |
| Beige | `#F5EFEB` | Page background |
| White | `#FFFFFF` | Cards |

Fonts: **Fraunces** (display serif) + **Plus Jakarta Sans** (body).

## Project layout
```
config/            Django project (settings split: base/dev/prod/test)
apps/
  core/            TimeStampedModel, brand context processor
  accounts/        Custom email-first User
  workspaces/      (Phase 1) Workspace + Member + roles
  profiles/        (Phase 1) CreativeProfile, Service, Package, Availability
  marketplace/     Public pages: home, search, pricing, how-it-works, for-creatives
  dashboard/       Authed app shell + Overview
templates/         base.html, base_public.html, base_app.html, partials, pages
static/            Tailwind input (src/input.css) → built css/app.css
```

## First-time setup
```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
npm install                      # Tailwind
cp .env.example .env             # then edit SECRET_KEY

npm run build:css                # build Tailwind once
python manage.py migrate
python manage.py seed_demo       # creates test accounts + a full demo
python manage.py runserver
```

Visit http://127.0.0.1:8000/ — admin at `/admin/`, creative dashboard at `/app/`, client portal at `/portal/`.

## Test accounts (after `seed_demo`)
All passwords: **`lens12345`**

| Role | Email | What to try |
|---|---|---|
| Platform admin | `admin@lens.test` | `/admin/` — approve `Newport Films` & verification docs |
| Creative (weddings) | `harper@lens.test` | Dashboard → Leads → send a quote; manage bookings |
| Creative (brand/reels) | `marlow@lens.test` | A confirmed booking awaiting delivery |
| Creative (real estate) | `bright@lens.test` | Has a quote out awaiting client acceptance |
| Creative (family) | `juniper@lens.test` | A brand-new enquiry to quote |
| Creative (PENDING) | `pending@lens.test` | Unverified/unpublished — approve it in admin |
| Client | `olivia@lens.test` | `/portal/` — a completed booking + gallery + review |
| Client | `northcote@lens.test` | `/portal/` — **accept a quote → sign → pay deposit** |

**End-to-end demo flow:** log in as `northcote@lens.test` → *My portal* → accept the quote → sign the contract → pay the deposit (test gateway). Then log in as the creative to mark the shoot complete, deliver a gallery, and send the final invoice.

> Payments use a built-in **test gateway** that simulates charges. **Going live with Stripe** is a config switch, not a rewrite:
> 1. `pip install stripe`
> 2. Set `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` in `.env`.
> 3. Point a Stripe webhook at `POST /api/v1/webhooks/stripe/` (events: `payment_intent.succeeded`).
>
> `get_gateway()` then returns the real `StripeGateway`; the booking advances only when Stripe's signed, idempotent webhook fires (never from the client), via the same `settle_invoice()` the test gateway uses.

## Tests
```bash
python manage.py test --settings=config.settings.test
```
Covers GST/deposit maths, the full booking state machine, no-double-charge, and cross-client access control.

## Day-to-day
- `npm run watch:css` — rebuild Tailwind on template changes (run alongside runserver)
- `python manage.py runserver`
- Settings default to `config.settings.dev`; prod uses `config.settings.prod`.

## Switching to Postgres/PostGIS (Phase 2)
Set `DATABASE_URL` in `.env`, e.g. `postgis://user:pass@localhost:5432/lens`,
install `psycopg[binary]` (already in requirements), and add `django.contrib.gis`
when you move geo search from the Haversine fallback to PostGIS.

## Deployment (Fly.io, Sydney)
The repo ships a `Dockerfile`, `fly.toml` (syd region, `/healthz` check,
`migrate` release command) and a GitHub Actions pipeline (`.github/workflows/ci.yml`:
lint → test → deploy on push to `main`).

```bash
fly launch --no-deploy            # creates the app
fly postgres create               # managed Postgres, then attach it
fly secrets set SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))") \
                DATABASE_URL=postgres://...                 # from the attach step
                # optional: STRIPE_SECRET_KEY=... STRIPE_WEBHOOK_SECRET=... etc.
fly deploy
```

CI auto-deploys on push to `main` if a `FLY_API_TOKEN` GitHub secret is set.
Tailwind CSS is pre-built and committed, so the image needs no Node.

## Roadmap (build plan §9)
- [x] **Phase 0 — Foundations**: project skeleton, design system, auth, public + dashboard shells
- [x] **Phase 1 — Supply side**: workspaces + roles, creative profiles, services/packages, verification docs, admin approval queue
- [x] **Phase 2 — Marketplace**: DB-backed search + ranking, public profile pages, enquiry flow, distance-aware geo matching (Haversine; PostGIS-upgradeable), programmatic suburb × service SEO pages + sitemap/robots/schema
- [x] **Phase 3 — Transactional spine**: enquiry → quote (GST) → accept → contract + e-sign → deposit (test gateway) → booking state machine
- [x] **Phase 4 — Delivery**: calendar, galleries, in-app notifications, reviews, final payment *(Google Calendar sync + email/SMS dispatch via Celery still to come)*
- [ ] **Phase 5 — Polish + private beta**: real Stripe, Postgres/PostGIS, programmatic SEO, Celery jobs, legal pages, deploy

### Not yet wired (clearly stubbed)
- **Real Stripe** — `apps/payments/services.py` uses a test gateway
- **Postgres/PostGIS** — dev runs on SQLite with an in-Python Haversine; on a PostGIS Postgres DB set `USE_POSTGIS=True` and radius search uses index-backed `ST_DWithin` automatically (the profiles migration installs the extension + GiST index). No GDAL/GeoDjango needed — the query runs server-side against the lat/lng columns.
- **Celery** is wired but runs **inline (eager)** until `REDIS_URL` is set; then emails/reminders process on a worker and the hourly Beat schedule activates (`celery -A config worker` / `celery -A config beat`)
- **SMS** — email + in-app notifications are wired; SMS is not
- **Google Calendar sync**
