import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.commen.settings import get_settings
from src.database import get_meta_engine
from src.models.meta_models import Base
from src.module.gateway.backup import backup_controller
from src.module.gateway.restore import restore_controller
from src.module.gateway.health import health_controller
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.commen.schedulers import scheduler

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
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

    scheduler.start()
    print("Scheduler started!!!")
    yield

    scheduler.shutdown()
    print("Scheduler shutdown")

    # Shutdown: nothing special needed (connection pools close automatically)
    logger.info("LMS Restore API shutting down.")


app = FastAPI(
    title="Backup Restore API",
    description="""
    ## Overview

    Async FastAPI service for restoring deleted records from a PostgreSQL backup database
    back into the main production database — **in FK-dependency order**.
    
    ## Key concepts
    
    | Concept | Description |
    |---------|-------------|
    | **Main DB** | The live production database |
    | **Backup DB** | A backup PostgreSQL instance (name passed per-request or default from settings) |
    | **Meta DB** | Internal DB storing `BackupLog` and `RevertLog` audit trail |
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
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
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(health_controller.router)
app.include_router(restore_controller.router)
app.include_router(backup_controller.router)
