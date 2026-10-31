# AgroStock MVP

AgroStock is a mobile-friendly stock ledger for Nigerian agribusinesses. The repository contains a Next.js frontend and a FastAPI backend using SQLAlchemy with Supabase PostgreSQL.

## Stack

- **Frontend:** Next.js App Router, React, TypeScript, plain CSS/CSS Modules approach; manual browser-side form validation (no validation package).
- **Backend:** FastAPI, Pydantic v2, SQLAlchemy 2, PyJWT, standard-library `hashlib.scrypt` password hashing.
- **Database:** Supabase PostgreSQL. SQLAlchemy transactions persist users, inventory items, movements and durable idempotency responses.
- **Shared request infrastructure:** Upstash Redis REST via `upstash-redis` for distributed rate limiting, request-ID metadata, idempotency reservations and cached responses. No in-memory rate-limit fallback.

## Configuration

### Backend

```bash
cd backend
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Set these values in `backend/.env`:

- `DATABASE_URL`: SQLAlchemy-compatible Supabase PostgreSQL URL, such as `postgresql+psycopg://...`. Use the Supabase pooler URL when appropriate for your deployment environment.
- `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`: from the Upstash Redis database's REST API page.
- `JWT_SECRET`: a random secret with at least 32 characters.
- `FRONTEND_ORIGIN`: frontend origin, comma-separated if multiple origins are required.

Run the API:

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`; health: `http://localhost:8000/health`.

**Upstash is required for application requests.** If its credentials are missing or Redis is unavailable, the API fails closed with HTTP 503 rather than silently using a process-local rate limiter. The health endpoint remains available for liveness checks.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local`. Open `http://localhost:3000`.

## Database ownership migration

At startup, `initialize_database()` creates missing tables and checks existing `inventory_items` and `stock_movements` tables for missing `user_id` ownership columns. It adds missing columns and indexes, derives movement ownership from its inventory item, and backfills ownerless inventory rows only when there is exactly one user in the database. On PostgreSQL it then enforces `NOT NULL` for ownership columns.

If legacy inventory rows exist and ownership cannot be inferred safely (for example, several users exist or there are no users), startup fails with a clear error instead of assigning private records to the wrong account. Back up the database before the first migration. This targeted startup migration covers ownership columns only; use versioned Alembic migrations for future schema changes.

## Security and consistency

- Authenticated frontend requests attach `Authorization: Bearer <JWT>` and an `X-Request-ID` header.
- FastAPI validates request bodies with Pydantic v2; frontend forms also use manual validation without validation packages.
- Request IDs and rate-limit counters are stored in Upstash with TTLs. Request IDs are returned in the `X-Request-ID` response header.
- Rate limiting uses an atomic Redis Lua script and a shared fixed-window counter, so limits apply across multiple API workers.
- Idempotency uses an Upstash reservation/cache keyed by user, operation and client `Idempotency-Key`; the request payload hash prevents key reuse for a different payload. A durable SQLAlchemy idempotency row is committed in the same PostgreSQL transaction as the stock mutation and cached response, protecting against duplicate mutations if the API process stops between database commit and Redis cache update.
- Stock movement updates lock the owned inventory row with `SELECT ... FOR UPDATE` on PostgreSQL. The stock balance update, movement record and durable idempotency response commit in one transaction.
- All inventory and movement queries are scoped to the authenticated user.

## Notes

- `SELECT ... FOR UPDATE` provides row-level concurrency control on PostgreSQL. SQLite is suitable only for local experiments and does not reproduce PostgreSQL row-lock behaviour.
- The current authentication design returns bearer JWTs. The browser stores the token in `localStorage` for this MVP; before production use, consider a same-site secure HttpOnly cookie strategy and add refresh/revocation policies if needed.
- Configure trusted proxy handling carefully before using client IPs for rate limits behind a reverse proxy. Do not blindly trust arbitrary forwarded IP headers.
- Run migrations on a backed-up database and validate the ownership mapping before using real farm data.
