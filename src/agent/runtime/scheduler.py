from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.tasks_repo import TasksRepository
from agent.runtime.semaphore import ExecutionSemaphore

if TYPE_CHECKING:
    from agent.runtime.task_runner import TaskRunner

logger = logging.getLogger(__name__)


class Scheduler:
    """
    5-second tick loop. Generates due weather tasks and picks up any
    pending task for execution via TaskRunner (injected after construction).
    Skips the tick entirely when the semaphore is held.
    """

    def __init__(self, config: Config, db: Database, semaphore: ExecutionSemaphore) -> None:
        self._config = config
        self._db = db
        self._semaphore = semaphore
        self._task_runner: object | None = None  # set after construction to avoid circular import
        self._last_weather_hour: int | None = None

    def set_task_runner(self, runner: "TaskRunner") -> None:
        self._task_runner = runner

    async def run(self) -> None:
        interval = self._config.scheduler.tick_interval_seconds
        logger.info("Scheduler started — tick every %ss", interval)
        while True:
            await asyncio.sleep(interval)
            await self._tick()

    async def _tick(self) -> None:
        if not self._semaphore.is_idle:
            return

        tasks_repo = TasksRepository(self._db)
        await self._generate_due_tasks(tasks_repo)

        task = await tasks_repo.claim_next()
        if task is None:
            return

        if self._task_runner is None:
            logger.warning("Scheduler: no task runner set, releasing task %s", task["id"])
            await tasks_repo.fail(task["id"], "no task runner configured")
            return

        await self._semaphore.acquire_task()
        try:
            await self._task_runner.execute(task)  # type: ignore[union-attr]
        except Exception as exc:
            logger.exception("Task %s failed: %s", task["id"], exc)
            await tasks_repo.fail(task["id"], str(exc))
        finally:
            self._semaphore.release()

    async def _generate_due_tasks(self, tasks_repo: TasksRepository) -> None:
        """Insert a fetch_weather task if we're in a scheduled hour and haven't done it yet."""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        schedule_hours = self._config.weather.schedule_hours

        if current_hour in schedule_hours and current_hour != self._last_weather_hour:
            self._last_weather_hour = current_hour
            await tasks_repo.insert("fetch_weather", {})
            logger.info("Scheduler: queued fetch_weather for hour %s", current_hour)
