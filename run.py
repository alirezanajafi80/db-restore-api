import uvicorn
from app.core.config import get_settings

settings = get_settings()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host    = "0.0.0.0",
        port    = 8000,
        reload  =settings.APP_ENV == "development",
        workers = 1 if settings.APP_ENV == "development" else 4,
        log_level = settings.LOG_LEVEL.lower(),
    )