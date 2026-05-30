from datetime import datetime


DB_BACKUP_CLEANUP_HOUR = 0
DB_BACKUP_CLEANUP_MIN = 0

async def db_backup_cleanup():
    print(f"Running backup cleanup at {datetime.now()}")


