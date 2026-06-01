from common.settings import get_settings, EnvironmentEnum


async def get_tasks():
    settings = get_settings()
    if settings.ENV != EnvironmentEnum.BG_TASK:
        return []

    from module.backup.backup_service import BackupService

    tasks = [
        *await BackupService().get_background_tasks(),
    ]
    return tasks