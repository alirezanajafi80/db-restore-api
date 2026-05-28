import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import backups, health, restore
from app.core.config import get_settings
from app.core.database import get_meta_engine
from app.models.meta_models import Base
from app.api import backup_create
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

settings = get_settings()

logging.basicConfig(
    # level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan: create meta DB tables on startup ────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create audit-trail tables in meta DB if they don't exist
    engine = get_meta_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Meta DB tables ready.")
    yield
    # Shutdown: nothing special needed (connection pools close automatically)
    logger.info("LMS Restore API shutting down.")


app = FastAPI(
    title = "Backup Restore API",
    description = """
    ## Overview

    Async FastAPI service for restoring deleted records from a PostgreSQL backup database
    back into the main production database — **in FK-dependency order**.
    
    ## Key concepts
    
    | Concept | Description |
    |---------|-------------|
    | **Main DB** | The live production database |
    | **Backup DB** | A backup PostgreSQL instance (name passed per-request or default from settings) |
    | **Meta DB** | Internal DB storing `BackupLog` and `RevertLog` audit trail |
    | **Ordered restore** | Restores FK parents before children to avoid constraint errors |
    
    ## Typical workflow
    
    1. `POST /restore/detect-missing` — preview what would be restored (safe, read-only)
    2. `POST /restore/ordered` — actually restore the missing records
    3. `GET /backups/revert-logs/all` — review the audit trail
    """,
    version     = "1.0.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
    lifespan    = lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Log body + errors so we can see exactly what failed
    try:
        body = await request.body()
        body_text = body.decode("utf-8")
    except Exception:
        body_text = "<could not read body>"

    logger.error(
        "URL   : %s %s\n"
        "Body  : %s\n"
        "Errors: %s",
        request.method,
        request.url,
        body_text,
        json.dumps(exc.errors(), indent=2, default=str),
    )

    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "body_received": body_text,
        },
    )



# ── CORS ──────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],   # tighten in production
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(restore.router)
app.include_router(backups.router)
app.include_router(backup_create.router)

