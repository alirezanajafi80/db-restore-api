from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import asyncio
from src.module.backup.backup_scheduler import db_backup_cleanup, DB_BACKUP_CLEANUP_HOUR, DB_BACKUP_CLEANUP_MIN


scheduler = AsyncIOScheduler()

scheduler.add_job(
    db_backup_cleanup,
    trigger=CronTrigger(hour=DB_BACKUP_CLEANUP_HOUR, minute=DB_BACKUP_CLEANUP_MIN),  # 2:00 AM daily
    id="db_backup_cleanup"
)