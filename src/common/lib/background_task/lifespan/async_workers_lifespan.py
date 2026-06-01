import asyncio
from typing import AsyncIterator, List

from fastapi import FastAPI
from fastapi_lifespan_manager import State

from common.lib.background_task.background_task_wrapper import BackgroundTaskWrapper
from common.lib.background_task.lifespan.lifespan_tasks import get_tasks
from database.run_migrations import run_migrations
import logging


logger = logging.getLogger(__name__)
state: dict = {"wrappers": [], "futures": []}
_state_lock = asyncio.Lock()


async def lifespan_add_task(task: BackgroundTaskWrapper) -> asyncio.Future:
    """
    Spawn a background task from an HTTP request.
    Holds strong references to both wrapper and future to prevent GC silent-kill.
    """
    future = asyncio.ensure_future(task.start())

    async with _state_lock:
        state["wrappers"].append(task)
        state["futures"].append(future)
        # Prune completed futures to prevent unbounded growth
        state["futures"] = [f for f in state["futures"] if not f.done()]
        state["wrappers"] = [
            w for w in state["wrappers"]
            if not (w.dt_last_executed is not None and w.is_periodic is False)
        ]

    logger.info(
        f"Task registered: {task.task_name}",
        extra=task.short_info_dict()
    )
    return future


async def service_workers_lifespan(app: FastAPI) -> AsyncIterator[State]:
    logger.info("Starting module worker tasks")
    # run_migrations()

    startup_tasks: List[BackgroundTaskWrapper] = await get_tasks()

    for task in startup_tasks:
        future = asyncio.ensure_future(task.start())
        state["wrappers"].append(task)
        state["futures"].append(future)

    yield state

    logger.info("Tearing down module worker tasks...")

    for task in startup_tasks:
        task.kill()

    async with _state_lock:
        for future in state["futures"]:
            if not future.done():
                future.cancel()

    state.clear()
    logger.info("All tasks torn down")