from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.setup import get_main_db_dep, get_meta_db_dep

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Health check — all DBs")
async def health(
    main_session: AsyncSession = Depends(get_main_db_dep),
    meta_session: AsyncSession = Depends(get_meta_db_dep),
):
    results = {}
    for name, session in [("main_db", main_session), ("meta_db", meta_session)]:
        try:
            await session.execute(text("SELECT 1"))
            results[name] = "ok"
        except Exception as exc:
            results[name] = f"error: {exc}"

    all_ok = all(v == "ok" for v in results.values())
    return {"status": "healthy" if all_ok else "degraded", "databases": results}