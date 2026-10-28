# Transcitis Courier Operations

Transcitis Courier Operations is a Django application that serves the responsive staff interface, JSON API, and Swagger reference from one Django service. The interface is built with Django templates and HTML, CSS, and JavaScript; there is no separate frontend service.

## Capabilities

- Station-scoped parcel registration, scan and search, exception handling, event history, handover, and CSV export.
- Configurable item categories with charge mapping. Initial category names are seeded with rates unset and inactive; parcels cannot be registered against a category until an approved charge is configured and activated.
- Route-based charge estimates for category, origin/destination, service level, actual/volumetric weight, declared value, delivery method, and quantity. Superadmins manage these tariffs from the Pricing screen.
- Optional product market-value suggestions from Gemini with Google Search grounding. Results include sources and require human confirmation before they can affect a declared-value charge.
- Trip manifests with assigned drivers, keyboard-wedge barcode scanning, immediate parcel feedback, dispatch confirmation, arrival scanning, and printable parcel-level manifests.
- Two-page 80 mm thermal receipts: customer receipt with amount paid, then a Code 128 barcode copy with parcel details and no amount-paid value. Receipt print history is audited; only a Django superuser can reprint after the first print.
- JWT authentication with user, role, station, and permissions claims in access tokens; staff invitation and password setup; user and driver administration.
- A branded role and permission administration screen with editable grants for built-in roles. Permission changes are persisted and enforced by protected APIs while station scoping and superadmin-only operations remain server-side.
- Swagger API documentation grouped by business module at `/api/docs/` and OpenAPI schema at `/api/schema/`.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Configure stations in Django Admin at `/admin/`. The Django superuser is the super administrator. Superusers can configure categories, invite station administrators and couriers, manage all users, and reprint receipts. Station administrators can invite supervisors and station staff assigned to their station.

## Authentication and invitations

`POST /api/auth/login/` accepts `username` and `password`; it returns `access`, `refresh`, and a user summary. The JWT includes the identity, roles, permissions, station ID, and station code. Send `Authorization: Bearer <access>` to protected APIs. The same service sets secure, HttpOnly cookies for the staff web app. Refresh with `POST /api/auth/refresh/`; revoke a refresh token and clear cookies with `POST /api/auth/logout/`. `GET /api/auth/me/` returns the current user and token claims.

Administrators create invitations through `POST /api/users/`. Invitation links expire after 72 hours and can be accepted once at `/invite/accept/`; the invitee sets a password and is signed in. For Gmail delivery, configure a Google account with 2-Step Verification and use its Google App Password (not the account password):

```dotenv
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=operations@example.com
EMAIL_HOST_PASSWORD=google-app-password
DEFAULT_FROM_EMAIL=Transcitis Operations <operations@example.com>
SITE_URL=https://operations.example.com
```

When SMTP is not configured, development uses Django's console email backend; the invitation API returns the link in debug mode or when delivery fails. Configure production secrets through the hosting provider, not in source control.

## Category and parcel charge mapping

The initial catalog contains Documents, Clothing & accessories, Electronics, Food & perishables, Fragile goods, Household items, Auto parts, and Other. Starter category and default-route amounts are seeded for immediate trial use; they are provisional and editable in the superadmin Pricing screen. A superadmin can replace them with agreed business rates.

For a route with a configured tariff, the estimate is: base charge + charge for billable weight above the included weight + declared-value percentage + doorstep fee (when selected) + fee per additional unit, subject to the configured minimum charge. Billable weight is the greater of actual weight and volumetric weight (`length × width × height ÷ volumetric divisor`).

If a matching route tariff has not been configured, the editable default route settings are added to the category charge. If automatic pricing is switched off, only the category's flat charge is used, preserving the previous method. Parcels without a category charge cannot be registered.

`POST /api/pricing/estimate/` returns the estimated charge, a component breakdown, the weight used, and—when configured—a separately sourced item market-value suggestion. Parcel registration requests updated estimates from the same API as the route, category, item description, and parcel measurements are entered. The API never uses the suggested market value as the declared value without staff confirmation. `GET, PATCH /api/pricing/settings/` reads or updates the automatic-pricing switch and starter tariff values; only Django superusers can change them. `POST /api/pricing/rules/` creates a route/category/service tariff, and `PATCH` or `DELETE /api/pricing/rules/{id}/` updates or deactivates one.

To enable Google market-value suggestions, set `GOOGLE_GEMINI_API_KEY` in the environment. The old Google Custom Search JSON API is closed to new customers; this optional lookup uses Gemini's Google Search grounding instead. Google currently provides a limited free search allowance, then bills by search request; a single request can trigger multiple web searches. See [Google Search grounding pricing and limits](https://ai.google.dev/gemini-api/docs/google-search). If the key is absent or lookup fails, staff can enter the declared value manually and still receive a tariff estimate.

See [`docs/item-category-charges.md`](docs/item-category-charges.md) for the mapping register. CSV export is available from `/api/item-categories/export/` for active categories with configured charges.

## API modules

| Swagger module | Main routes |
| --- | --- |
| Authentication | `POST /api/auth/login/`, `POST /api/auth/refresh/`, `POST /api/auth/logout/`, `GET /api/auth/me/`, `POST /api/auth/invitations/accept/` |
| Overview | `GET /api/dashboard/` |
| Parcels | `GET, POST /api/parcels/`, `GET /api/parcels/{parcel_id}/`, `POST /api/parcels/{parcel_id}/status/` |
| Receipts | `POST /api/parcels/{parcel_id}/receipt/` |
| Trips | `GET, POST /api/trips/`, `POST /api/trips/{trip_id}/parcels/`, `POST /api/trips/{trip_id}/dispatch/`, `POST /api/trips/{trip_id}/manifest/`, `POST /api/trips/{trip_id}/arrive/` |
| Receiving | `POST /api/receiving/scan/` |
| Handover | `POST /api/parcels/{parcel_id}/ready-handover/`, `POST /api/parcels/{parcel_id}/assign-courier/`, `POST /api/parcels/{parcel_id}/handover/` |
| Exceptions | `GET, POST /api/exceptions/`, `POST /api/exceptions/{id}/resolve/` |
| User management | `GET, POST /api/users/`, `PATCH /api/users/{id}/`, `GET /api/users/drivers/`, `GET, PUT /api/roles/permissions/`, `GET /api/stations/` |
| Pricing | `GET, POST /api/item-categories/`, `PATCH /api/item-categories/{id}/`, `POST /api/pricing/estimate/`, `GET, PATCH /api/pricing/settings/`, `GET, POST /api/pricing/rules/`, `PATCH, DELETE /api/pricing/rules/{id}/`, `GET /api/item-categories/export/` |
| Reports | `GET /api/parcels/export/` |

## Printer setup

The receipt uses CSS `@page` at 80 mm width with two explicit page sections. Configure the browser/thermal printer for 80 mm paper and disable headers/footers in the print dialog. The receipt's second page includes the Code 128 parcel barcode, weight, route, and identifying details, but omits amount paid. The manifest is formatted for A4 paper and includes each parcel's category, description, quantity, weight, contact names, and barcode.

## Configuration and deployment

Local development uses SQLite whenever `DEBUG=True`, even if `DATABASE_URL` is present. With `DEBUG=False`, the app requires `DATABASE_URL` and uses PostgreSQL over SSL; it will stop with a clear error if the URL is missing or still contains a password placeholder. The local `.env` is ignored by Git. Replace `[YOUR-PASSWORD]` in the Supabase URL with the real database password before using it, and URL-encode reserved characters in that password. The supplied port `6543` is Supabase transaction-pooler mode; the app disables prepared statements and short-lived Django connections for this mode. For production, also set a strong `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`, and email credentials. Run `python manage.py migrate` with the target database selected before creating users or processing parcels. Supabase recommends a direct database connection for schema migrations; the supplied port `6543` URL is transaction-pooler mode, so use the project’s direct or session-mode URL if a migration needs a persistent database session. Django schema migrations do not copy existing SQLite records to PostgreSQL. The Render Blueprint applies migrations, collects static assets, and starts Gunicorn.
