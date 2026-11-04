# Horilla CRM

Free and open source CRM software. Leads, opportunities, accounts, contacts, campaigns, forecasting, calling and meeting scheduling in one Django application.

- **Source:** https://github.com/horilla/horilla-crm
- **Docs:** https://docs.horilla.com
- **Website:** https://www.horilla.com
- **License:** LGPL-2.1

__NOTICE__

---

## Supported tags

| Tag | Meaning |
|---|---|
| `latest` | Newest stable release. |
| `X.Y.Z` | Exact release, immutable once published. Pin this in production. |
| `X.Y` | Newest patch within a minor line. |

**Architectures:** `linux/amd64`, `linux/arm64` (single multi-arch manifest — Docker picks the right one).

```bash
docker pull horilla/horilla-crm:latest
```

---

## Quick start

Horilla CRM needs **PostgreSQL and Redis**. Redis is not optional: the app uses Django Channels for real-time updates and Celery for background work, and reads `REDIS_URL` at startup.

```yaml
# compose.yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: horilla_db
      POSTGRES_USER: horilla_user
      POSTGRES_PASSWORD: change-me-db-password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U horilla_user -d horilla_db"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass change-me-redis-password

  web:
    image: horilla/horilla-crm:latest
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"
    environment:
      DEBUG: "0"
      SECRET_KEY: "replace-with-50-plus-random-characters"
      ALLOWED_HOSTS: "localhost,127.0.0.1"
      CSRF_TRUSTED_ORIGINS: "http://localhost:8000"
      DATABASE_URL: "postgres://horilla_user:change-me-db-password@db:5432/horilla_db"
      REDIS_URL: "redis://:change-me-redis-password@redis:6379/0"
      CELERY_BROKER_URL: "redis://:change-me-redis-password@redis:6379/0"
      CELERY_RESULT_BACKEND: "redis://:change-me-redis-password@redis:6379/0"
    volumes:
      - media:/app/media
      - staticfiles:/app/staticfiles

volumes:
  postgres_data:
  media:
  staticfiles:
```

```bash
docker compose up -d
```

Then open http://localhost:8000.

> **The startup script waits for the database host and port in `DATABASE_URL`** (or `DB_HOST`/`DB_PORT`) before running migrations, so the PostgreSQL service does not have to be named `db` and can run outside this Compose file.

**First boot takes a few minutes.** The container applies the full migration set against the empty database before the web server binds. Watch with `docker compose logs -f web`; the app is ready when `/health/` responds.

Generate a real `SECRET_KEY`:

```bash
docker run --rm --entrypoint python horilla/horilla-crm:latest \
  -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

(`--entrypoint python` is needed because the default entrypoint waits for a database before running anything.)

---

## Environment variables

### Required

`SECRET_KEY` may be omitted; the other variables still have to be set. The container will not start without them.

| Variable | Notes |
|---|---|
| `SECRET_KEY` | Django signing key. Set a unique 50+ character value and keep it stable, or leave it unset. A shipped placeholder is rejected. When unset, a key is written to `SECRET_KEY_FILE` (Compose mounts one volume for web and Celery). |
| `DEBUG` | `0` in production. `1` exposes tracebacks. |
| `ALLOWED_HOSTS` | Comma-separated hostnames. Do not use `*` in production. |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated, **must include the scheme** (`https://crm.example.com`). |

### Database

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `postgres://user:pass@db:5432/dbname`. |

### Redis, Channels and Celery

| Variable | Default | Notes |
|---|---|---|
| `REDIS_URL` | — | Channels layer and cache. |
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/0` | Background task broker. Set it explicitly in containers. |
| `CELERY_RESULT_BACKEND` | — | Task results. |

The web container does not run Celery workers itself. For background jobs — scheduled cadences, bulk email, imports — run additional containers from the same image:

```yaml
  celery-worker:
    image: horilla/horilla-crm:latest
    entrypoint: []
    command: celery -A horilla worker --concurrency=2
    environment: *same-as-web

  celery-beat:
    image: horilla/horilla-crm:latest
    entrypoint: []
    command: celery -A horilla beat
    environment: *same-as-web
```

`entrypoint: []` is required — the default entrypoint runs migrations and starts the web server, which is not what a worker should do.

---

## What the container does at startup

1. Waits for `db:5432` (30 attempts, 1s apart)
2. Runs `migrate --noinput`
3. Runs `collectstatic --noinput`
4. Starts uvicorn (ASGI) on port 8000

Uvicorn rather than gunicorn: CRM serves WebSocket connections through Django Channels, which needs an ASGI server.

---

## Volumes

| Path | Contents |
|---|---|
| `/app/media` | User uploads and attachments. **Back this up.** |
| `/app/staticfiles` | Collected static assets. Rebuilt on every start; safe to discard. |

---

## Health check

| Endpoint | Returns |
|---|---|
| `/health/` | `{"status": "ok"}` once the web server is serving |

The image ships a `HEALTHCHECK` that polls `/health/` every 30s with a 60s start period. On a first boot the container may report `starting` for several minutes while migrations run — expected, not a failure.

---

## Creating the first user

```bash
docker compose exec web python manage.py createsuperuser
```

---

## Production notes

- **Run behind a reverse proxy** that terminates TLS, and make sure it forwards WebSocket upgrade headers — real-time updates break silently without them.
- **Pin an exact version** (`horilla/horilla-crm:__VERSION__`), not `latest`, so a deploy cannot pick up a new release unattended.
- **Set `SECRET_KEY` from a secret store** and keep it stable. If it is unset, the first start writes one to `SECRET_KEY_FILE`; a later change logs everyone out and invalidates API tokens. A shipped placeholder is never used.
- **Migrations run on every container start.** With more than one replica, start one first and let it finish before scaling up — nothing coordinates concurrent migrations.
- The image runs as a **non-root user** (`appuser`, uid 1000). Mounted volumes must be writable by uid 1000.

---

## Image details

- Base: `python:3.13-slim` (Debian), multi-stage build
- Python dependencies installed into `/opt/venv`; build toolchain is not present in the final image
- Runs as `appuser` (uid 1000), never root
- Exposes port 8000
- Serves ASGI via uvicorn with WebSocket keepalive configured

Each image carries OCI labels — `org.opencontainers.image.version`, `.revision`, `.source` — so any published image traces back to the exact commit it was built from:

```bash
docker inspect horilla/horilla-crm:latest \
  --format '{{json .Config.Labels}}' | python3 -m json.tool
```

---

## How these images are built

Built and published by GitHub Actions from [horilla/horilla-crm](https://github.com/horilla/horilla-crm) on every release. Before any image is pushed, the pipeline:

1. Asserts the code's `__version__` matches the release version
2. Builds for amd64 and arm64
3. Boots the built image against a real PostgreSQL and Redis and waits for `/health/`
4. Fails the release on any CRITICAL vulnerability found by Trivy

An image that builds but does not run cannot be published.

---

## Support

- Issues: https://github.com/horilla/horilla-crm/issues
- Documentation: https://docs.horilla.com
