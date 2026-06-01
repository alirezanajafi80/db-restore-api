import json
import logging
from fastapi import FastAPI, Request
from common.settings import get_settings
from module.gateway.backup import backup_controller
from module.gateway.restore import restore_controller
from module.gateway.health import health_controller
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from common.lib.background_task.lifespan.lifespan_manager import manager


settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
    lifespan=manager,
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
