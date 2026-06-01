import asyncio
import datetime
import logging
from typing import Optional, Callable, Coroutine, Dict, Any
from common.settings import EnvironmentEnum


logger = logging.getLogger(__name__)


class BackgroundTaskWrapper:

    def __init__(
        self,
        is_periodic: bool,
        frequency_execute_seconds: float,
        coroutine_generator: Callable[[], Coroutine],
        task_name: str = "",  # always pass this explicitly
    ) -> None:
        self.is_periodic = is_periodic
        self.frequency_execute_seconds = frequency_execute_seconds
        self.coroutine_generator = coroutine_generator
        self.dt_last_executed: Optional[datetime.datetime] = None
        self._latest_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        if task_name:
            self.task_name = task_name
        else:
            # safe fallback: inspect without calling
            self.task_name = getattr(
                coroutine_generator,
                "__qualname__",
                repr(coroutine_generator)
            )

    def short_info_dict(self) -> Dict[str, Any]:
        info = {
            "is_periodic": self.is_periodic,
            "frequency_execute_seconds": self.frequency_execute_seconds,
            "dt_last_executed": self.dt_last_executed,
            "task_name": self.task_name,
        }
        if self.dt_last_executed is not None:
            info["seconds_since_last_execution"] = (
                datetime.datetime.now() - self.dt_last_executed
            ).total_seconds()
        return info

    async def start(self):
        logger.info(f"Starting task: {self.task_name}")

        if not self.is_periodic:
            try:
                self._latest_task = asyncio.ensure_future(self.coroutine_generator())
                await self._latest_task
            except asyncio.CancelledError:
                logger.info(f"One-shot task cancelled: {self.task_name}")
            except Exception as exc:
                logger.error(
                    f"Error in one-shot task: {self.task_name}",
                    extra={"error": exc},
                    exc_info=True,  # captures full traceback
                )
            finally:
                self.dt_last_executed = datetime.datetime.now()
            return

        if self.frequency_execute_seconds < 0:
            raise ValueError(
                f"frequency_execute_seconds must be >= 0, got: {self.frequency_execute_seconds}"
            )

        while not self._stop_event.is_set():
            try:
                self._latest_task = asyncio.ensure_future(self.coroutine_generator())
                await self._latest_task
            except asyncio.CancelledError:
                logger.info(f"Periodic task cancelled: {self.task_name}")
                break
            except Exception as exc:
                logger.error(
                    f"Error in periodic task: {self.task_name}",
                    extra={"error": exc},
                    exc_info=True,
                )
            finally:
                self.dt_last_executed = datetime.datetime.now()

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.frequency_execute_seconds,
                )
                break  # stop_event fired → clean exit
            except asyncio.TimeoutError:
                pass   # normal: interval elapsed, loop again

    def stop(self):
        """Graceful: let current iteration finish, then exit."""
        self._stop_event.set()

    def kill(self):
        """Immediate: cancel running coroutine and exit."""
        self._stop_event.set()
        if self._latest_task and not self._latest_task.done():
            self._latest_task.cancel()
