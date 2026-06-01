from fastapi_lifespan_manager import LifespanManager
from common.lib.background_task.lifespan.async_workers_lifespan import service_workers_lifespan

manager = LifespanManager()


manager.add(service_workers_lifespan)


