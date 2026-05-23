# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mercari is a **full-stack inventory and order management system** with deep integration to the Japanese Mercari marketplace. It's built as a Vue 3 frontend (Vite) with a Python FastAPI backend, featuring order synchronization, product listing automation, and local inventory management with support for barcode scanning and OCR.

## Technology Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| Frontend | Vue 3, Vite, Vue Router, Pinia, Element Plus | Dev: port 9600 (HTTPS), Prod: static SPA |
| Backend | Python 3.11+, FastAPI, Uvicorn | Port 9601, OpenAPI docs at /docs |
| Database | SQLite WAL mode | backend/mercariDB.db (auto-created) |
| Authentication | JWT (Bearer tokens) | 12-hour expiry by default |
| Image Storage | Local filesystem | backend/imges/ directory |
| Browser Automation | Playwright | For Mercari listing management |
| Request Inspection | mitmproxy | SSL/TLS interception (Windows) |
| ML/Vision | EasyOCR, OpenCV | For barcode/text recognition |

## Development Setup

### Quick Start

```powershell
start.bat
```

All-in-one: activates conda env, starts backend & frontend.

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Development (with auto-reload)
python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601
```

First startup auto-creates default admin: `admin / admin` — change immediately in System tab.

### Frontend

```powershell
cd webside
npm install
npm run dev
```

Frontend server: **https://localhost:9600** (self-signed HTTPS by default)
- HTTP only: set `MERCARI_DEV_HTTP=1` before `npm run dev`
- Remote/domain HMR: set `MERCARI_DEV_PUBLIC_HOST=yourhost` in `webside/.env.development`

### Production Build (Frontend)

```powershell
cd webside
npm run build  # Output to webside/dist/
```

The FastAPI backend can serve the SPA by mounting `webside/dist`. Override with `MERCARI_WEBSIDE_DIST` env var or disable with `MERCARI_NO_STATIC=1`.

## Project Structure

```
backend/
├── main.py                          # FastAPI entry point, app initialization
├── requirements.txt                 # Python dependencies
├── mercariDB.db                     # SQLite database (WAL mode)
├── imges/                           # Product image storage
└── src/
    ├── auth.py                      # JWT token generation & verification
    ├── app_paths.py                 # Development vs PyInstaller path handling
    ├── image_storage.py             # Base64/upload image handling
    ├── meilu_auto_fetch_loop.py     # Background task: periodic Mercari sync
    ├── system_service.py            # System utilities (restart, etc.)
    ├── order_goods_ratio.py         # Order-to-inventory analysis
    ├── db_manage/                   # Database layer
    │   ├── base_model.py            # Abstract BaseModel for all tables
    │   ├── database.py              # DatabaseManager singleton (SQLite connection pooling)
    │   ├── db_manager.py            # DBManager: coordinated table init & migrations
    │   └── models/                  # Table models (inventory.py, user.py, etc.)
    ├── routes/                      # REST API blueprints
    │   ├── auth.py                  # Login, token refresh
    │   ├── inventory.py             # Product inventory CRUD
    │   ├── orders.py                # Order management
    │   ├── meilu_accounts.py        # Mercari account config
    │   ├── on_sale_items.py         # Mercari listing sync display
    │   ├── warehouses.py            # Warehouse & shelf location management
    │   └── [other routes]
    ├── use_mercari/           # Mercari API & sync logic
    │   ├── API.py                   # FastAPI router for /api/mercari endpoints
    │   ├── sync_data.py             # Mercari API client wrapper
    │   ├── mercari_req_scheduling.py # Async request scheduling
    │   ├── on_sale_items_sync.py    # Fetch & sync item listings
    │   └── mgmt_id_cipher.py        # Encode/decode secret code from descriptions
    ├── web_drive/                   # Playwright browser automation
    │   ├── manager.py               # Browser manager singleton
    │   ├── interactive_browser.py   # Headed browser for user interaction
    │   ├── mitm_session.py          # Per-op headed minimized Edge for MITM ops
    │   └── account_serial_queue.py  # Serial task execution per account
    └── ssl_mitm_proxy/              # mitmproxy integration
        ├── runner.py                # Start/stop MITM proxy
        ├── mitm_addon.py            # Custom mitmproxy addon for request capture
        └── windows_trust.py         # Windows cert trust utilities

webside/
├── package.json
├── vite.config.js                   # Dev server: port 9600, /api & /imges proxy to 9601
├── dist/                            # Production build output
└── src/
    ├── main.js                      # Vue app initialization (Pinia, router, Element Plus)
    ├── api/index.js                 # Axios HTTP client with JWT interceptors
    ├── router/index.js              # Vue Router with auth guards
    ├── views/                       # Page components (Dashboard, Inventory, Orders, etc.)
    └── components/                  # Reusable components (Layout, dialogs, forms)
```

## Database Models & Core Tables

Key tables in `backend/src/db_manage/models/`:

- **users**: User accounts with bcrypt passwords
- **inventory**: Products with barcode, SKU, price, quantity, images (Base64)
- **warehouses**: Storage locations (shelf names duplicable per warehouse)
- **meilu_accounts**: Mercari account config (headers in value JSON field)
- **on_sale_items**: Mercari listing records synced from API
- **orders**: Mercari orders synced from API
- **order_outbound_lines**: Line items for outbound shipments
- **transactions**: In/out stock movements with warehouse tracking
- **cost_records**: Packaging material inventory
- **cost_expenses**: Packaging material usage per order

## Key Architectural Patterns

### Custom ORM Database Layer

1. **BaseModel** (`base_model.py`): Abstract base defining `get_table_name()` and `get_fields()`
2. **DatabaseManager** (singleton): Manages SQLite connection pooling with WAL mode
3. **DBManager** (`db_manager.py`): Coordinates all model registration, table creation, migrations
4. Migrations handled in `db_manager.py` (e.g., warehouses composite unique constraint)

### Authentication Flow

1. User logs in via `POST /api/auth/login` (username + password)
2. Backend verifies with bcrypt, creates JWT with `user_id` and `username`
3. Frontend stores token in `localStorage`
4. Axios interceptor adds `Authorization: Bearer <token>` to all requests
5. Backend `require_auth()` dependency verifies JWT, raises 401 if expired/invalid
6. Token expiry: `JWT_EXPIRE_HOURS` env var (default 12)

### Mercari Integration Pipeline

1. User adds Mercari account in Web UI → headers & cookies stored in `meilu_accounts.value` (JSON)
2. `meilu_auto_fetch_loop()` runs on startup, periodically syncs orders & items
3. `sync_data.py`: Wraps Mercari API calls (fetch orders, items, etc.)
4. `on_sale_items_sync.py`: Incremental sync with local DB
5. `mgmt_id_cipher.py`: Decodes secret codes embedded in item descriptions
6. Browser automation (`web_drive/`): Playwright for listing operations
7. SSL MITM proxy: Captures HTTP traffic for debugging/inspection

## Environment Variables

**Backend**:
- `JWT_SECRET`: Signing key (change in production)
- `JWT_EXPIRE_HOURS`: Token validity (default: 12)
- `SSL_MITM_AUTO_START`: Set to `0` to disable mitmproxy (default: 1)
- `INTERACTIVE_BROWSER_AUTO_START`: Set to `0` to disable headed browser auto-start at boot (default: 0)

**Frontend** (`webside/.env.development`):
- `MERCARI_DEV_HTTP`: Use HTTP instead of HTTPS (default: 0)
- `MERCARI_DEV_PUBLIC_HOST`: Hostname for remote HMR WebSocket
- `MERCARI_DEV_HMR_CLIENT_PORT`: Custom HMR port (default: 9600)

## Accessing the Application

**Development**:
- Frontend: https://localhost:9600 (self-signed cert)
- Backend API: http://localhost:9601
- OpenAPI docs: http://localhost:9601/docs
- Health check: http://localhost:9601/api/health

**Network Access**: Vite and uvicorn are both bound to `0.0.0.0` — LAN access via `https://<your-ip>:9600`.

## Adding a New API Route

1. Create `backend/src/routes/myfeature.py` with a FastAPI router
2. Import in `backend/main.py` and register with `app.include_router()`
3. If auth required, add `dependencies=auth_required`
4. Frontend: Add API calls in `webside/src/api/index.js`, add route in `webside/src/router/index.js`

## Adding a New Database Table

1. Create model in `backend/src/db_manage/models/mymodel.py` extending `BaseModel`
2. Define `get_table_name()`, `get_fields()`, optionally `get_indexes()`
3. Import & register in `backend/src/db_manage/db_manager.py`
4. Table auto-created on backend startup via `init_database()`

## Useful Commands

| Task | Command |
|------|---------|
| Backend dev (auto-reload) | `cd backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601` |
| Frontend dev | `cd webside && npm run dev` |
| Frontend build | `cd webside && npm run build` |
| Backend deps | `cd backend && pip install -r requirements.txt` |
| Frontend deps | `cd webside && npm install` |
| Disable heavy startup features | `SSL_MITM_AUTO_START=0 INTERACTIVE_BROWSER_AUTO_START=0 python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601` |
