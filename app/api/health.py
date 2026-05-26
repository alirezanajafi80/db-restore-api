from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_main_db, get_meta_db

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Health check — all DBs")
async def health(
    main: AsyncSession = Depends(get_main_db),
    meta: AsyncSession = Depends(get_meta_db),
):
    results = {}

    for name, session in [("main_db", main), ("meta_db", meta)]:
        try:
            await session.execute(text("SELECT 1"))
            results[name] = "ok"
        except Exception as exc:
            results[name] = f"error: {exc}"

    all_ok = all(v == "ok" for v in results.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "databases": results,
    }