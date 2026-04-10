"""Shared Playwright page pool for Fleet sub-agents.

Each Fleet sub-agent that needs to consult SEI or SIGA acquires a Page from
the corresponding pool. The pool wraps a single :class:`BrowserContext` so
all pages share cookies / storage state, and an :class:`asyncio.Semaphore`
caps concurrency to avoid overwhelming the upstream system with too many
parallel Playwright tabs.

Usage::

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
