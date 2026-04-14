"""Shared Playwright page pool for Fleet sub-agents.

Status: **parked pending Fleet async refactor** (see TASKS.md).
`process_one_email` is sync and LangGraph dispatches sub-agents in a
thread pool, so each sub-agent has its own event loop. A Playwright
`BrowserContext` is bound to the loop that created it and cannot be
shared across threads — making this pool unusable until the Fleet
path is converted to async. Current production flow relies on
`storage_state` reuse in `sei/browser.py`/`siga/browser.py` instead
(0 logins in steady state; one login per sub-agent only on first
run / expired session).

Usage (target shape, once Fleet is async)::

    pool = BrowserPagePool(context, size=3)
    async with pool.acquire() as page:
        await page.goto("https://sei.ufpr.br/...")

The pool never re-uses pages — each ``acquire()`` opens a fresh tab and
closes it on exit. The semaphore is what limits parallelism; the context
itself is reused across the whole Fleet run.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

POOL_SIZE = int(os.getenv("FLEET_BROWSER_POOL_SIZE", "3"))


class BrowserPagePool:
    """Acquire / release Playwright pages from a shared BrowserContext.

    Args:
        context: A Playwright ``BrowserContext`` shared across all sub-agents.
        size: Maximum number of concurrent pages. Defaults to
            ``FLEET_BROWSER_POOL_SIZE`` env var (or 3).
    """

    def __init__(self, context: "BrowserContext", size: int = POOL_SIZE):
        self._context = context
        self._semaphore = asyncio.Semaphore(size)
        self._size = size

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator["Page"]:
        """Acquire a page from the pool.

        Releases the semaphore slot automatically on exit, even if the
        caller raised. The page is closed before the slot is released so
        the next waiter sees a fresh tab.
        """
        await self._semaphore.acquire()
        page = None
        try:
            page = await self._context.new_page()
            yield page
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception as e:  # pragma: no cover - defensive
                    logger.warning("Failed to close pooled page: %s", e)
            self._semaphore.release()

    @property
    def size(self) -> int:
        return self._size
