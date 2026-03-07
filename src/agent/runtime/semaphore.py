from __future__ import annotations

import asyncio
from enum import Enum


class SemaphoreState(str, Enum):
    idle = "idle"
    user_typing = "user_typing"
    llm_running = "llm_running"
    task_running = "task_running"


class ExecutionSemaphore:
    """
    Single asyncio lock shared by the CLI, scheduler, and runtime.

    The lock is held continuously from the moment the CLI shows the input
    prompt (user_typing) through the entire LLM reply (llm_running).
    Background tasks (task_running) also hold the lock, so the CLI cannot
    show a new prompt while a task is executing.

    The HTTP server never touches this semaphore.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state = SemaphoreState.idle

    @property
    def state(self) -> SemaphoreState:
        return self._state

    @property
    def is_idle(self) -> bool:
        return self._state == SemaphoreState.idle

    async def acquire_typing(self) -> None:
        """Acquire the lock before showing the input prompt."""
        await self._lock.acquire()
        self._state = SemaphoreState.user_typing

    def transition_to_llm(self) -> None:
        """Called on Enter — keeps the lock, changes state to llm_running."""
        assert self._state == SemaphoreState.user_typing, (
            f"transition_to_llm() called in state {self._state}"
        )
        self._state = SemaphoreState.llm_running

    async def acquire_task(self) -> None:
        """Acquire the lock for background task execution."""
        await self._lock.acquire()
        self._state = SemaphoreState.task_running

    def release(self) -> None:
        """Release the lock — returns to idle."""
        self._state = SemaphoreState.idle
        self._lock.release()
