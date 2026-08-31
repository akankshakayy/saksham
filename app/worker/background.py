"""Background task management for async document processing.

Provides bounded, tracked background execution for CPU-bound work
(OCR, PDF processing) and full workflow orchestration.

Lifecycle:
    1. Task created via asyncio.create_task()
    2. Reference stored in _tasks dict
    3. Done callback removes reference and logs errors
    4. shutdown() cancels all pending tasks and waits for completion
    5. reset_worker() clears the global singleton
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_ocr_lock = threading.Lock()
_ocr_thread_local = threading.local()


def _get_thread_ocr_engine():
    """Get a thread-local RapidOCR instance for thread safety."""
    if not hasattr(_ocr_thread_local, "engine"):
        from rapidocr_onnxruntime import RapidOCR
        _ocr_thread_local.engine = RapidOCR()
    return _ocr_thread_local.engine


class BackgroundWorker:
    """Manages bounded background task execution.

    Provides:
    - Semaphore-limited concurrency for CPU-bound work
    - Task tracking and lifecycle management
    - Safe exception handling
    - Graceful shutdown with task cancellation
    """

    def __init__(
        self,
        max_ocr_concurrency: int = 2,
        max_workflow_concurrency: int = 3,
    ) -> None:
        self._ocr_semaphore = asyncio.Semaphore(max_ocr_concurrency)
        self._workflow_semaphore = asyncio.Semaphore(max_workflow_concurrency)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def _on_task_done(self, key: str, task: asyncio.Task[None], coro: Any = None) -> None:
        """Synchronous done callback - removes completed task from tracking dict.

        Runs on the event loop thread. dict.pop() is atomic in CPython.
        Closes the inner coroutine if it was never started (cancelled before body ran).
        """
        self._tasks.pop(key, None)
        if coro is not None and getattr(coro, "cr_frame", None) is not None:
            coro.close()
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Background task %s completed with error: %s", key, exc)

    async def submit_ocr_task(
        self,
        key: str,
        coro: Any,
    ) -> None:
        """Submit a CPU-bound OCR task for background execution.

        Args:
            key: Unique identifier for deduplication (e.g., document_id)
            coro: Coroutine to execute (will be wrapped in to_thread)
        """
        async with self._lock:
            if key in self._tasks and not self._tasks[key].done():
                logger.info("OCR task %s already running, skipping", key)
                coro.close()
                return

        task = asyncio.create_task(self._run_with_semaphore(
            self._ocr_semaphore, key, coro
        ))
        async with self._lock:
            self._tasks[key] = task
        task.add_done_callback(lambda t: self._on_task_done(key, t, coro))

    async def submit_workflow_task(
        self,
        key: str,
        coro: Any,
    ) -> None:
        """Submit a workflow orchestration task for background execution."""
        async with self._lock:
            if key in self._tasks and not self._tasks[key].done():
                logger.info("Workflow task %s already running, skipping", key)
                coro.close()
                return

        task = asyncio.create_task(self._run_with_semaphore(
            self._workflow_semaphore, key, coro
        ))
        async with self._lock:
            self._tasks[key] = task
        task.add_done_callback(lambda t: self._on_task_done(key, t, coro))

    async def _run_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        key: str,
        coro: Any,
    ) -> None:
        """Run a coroutine bounded by a semaphore."""
        try:
            async with semaphore:
                try:
                    await coro
                except asyncio.CancelledError:
                    logger.info("Task %s cancelled", key)
                    raise
                except Exception:
                    logger.exception("Task %s failed with exception", key)
        finally:
            coro.close()

    async def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel all pending tasks and wait for completion.

        Called during application shutdown to ensure no dangling tasks.
        After the timeout, waits without a timeout for tasks to finish
        processing their cancellation so coroutines are properly closed.
        """
        tasks = [t for t in self._tasks.values() if not t.done()]
        if not tasks:
            return

        logger.info("Shutting down %d background task(s)", len(tasks))
        for task in tasks:
            task.cancel()

        _, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            logger.warning(
                "Background task shutdown timed out after %.1fs "
                "(%d tasks still pending)",
                timeout,
                len(pending),
            )
            await asyncio.gather(*pending, return_exceptions=True)

        self._tasks.clear()

    def is_task_running(self, key: str) -> bool:
        """Check if a task with the given key is currently running."""
        task = self._tasks.get(key)
        return task is not None and not task.done()

    @property
    def active_task_count(self) -> int:
        """Number of currently running tasks."""
        return sum(1 for t in self._tasks.values() if not t.done())


_worker: BackgroundWorker | None = None


def get_worker() -> BackgroundWorker:
    """Get the global background worker instance."""
    global _worker
    if _worker is None:
        _worker = BackgroundWorker()
    return _worker


def reset_worker() -> None:
    """Reset the global worker reference.

    Used in test teardown to ensure each test starts with a clean worker.
    Call shutdown() first if there are pending tasks.
    """
    global _worker
    _worker = None
