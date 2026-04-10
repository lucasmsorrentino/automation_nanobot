"""Tests for :mod:`ufpr_automation.graph.browser_pool`."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ufpr_automation.graph.browser_pool import BrowserPagePool


@pytest.mark.asyncio
async def test_acquire_yields_page_and_closes():
    ctx = AsyncMock()
    page = AsyncMock()
    ctx.new_page.return_value = page

    pool = BrowserPagePool(ctx, size=2)
    async with pool.acquire() as p:
        assert p is page
        page.close.assert_not_called()
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_pool_limits_concurrency():
    ctx = AsyncMock()
    ctx.new_page.side_effect = lambda: AsyncMock()

    pool = BrowserPagePool(ctx, size=2)
    in_flight = 0
    max_in_flight = 0

    async def task():
        nonlocal in_flight, max_in_flight
        async with pool.acquire():
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

    await asyncio.gather(*[task() for _ in range(10)])
    assert max_in_flight <= 2


@pytest.mark.asyncio
async def test_pool_releases_on_exception():
    ctx = AsyncMock()
    page = AsyncMock()
    ctx.new_page.return_value = page

    pool = BrowserPagePool(ctx, size=1)
    with pytest.raises(ValueError):
        async with pool.acquire():
            raise ValueError("boom")

    # Pool should be available again — would hang forever if release was missing.
    async with pool.acquire():
        pass


def test_pool_exposes_size():
    ctx = AsyncMock()
    pool = BrowserPagePool(ctx, size=5)
    assert pool.size == 5
