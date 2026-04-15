"""Shared Playwright browser/session helpers for SEI and SIGA modules.

Both ``sei/browser.py`` and ``siga/browser.py`` need the same three
low-level pieces:

- launch a headless Chromium (identical kwargs),
- create a ``BrowserContext`` loading saved storage state if present,
- persist the current storage state to disk after login.

Only the session file path and log label differ. Historically the code
was copy-pasted into both modules; this helper centralizes it so bug
fixes (timeouts, UA tweaks, locale, etc.) apply to both at once.

The module intentionally exposes a thin, config-driven API rather than a
class hierarchy: ``sei/browser.py`` and ``siga/browser.py`` keep their
own ``launch_browser`` / ``create_browser_context`` / ``save_session_state``
/ ``has_saved_session`` top-level functions (so test @patch paths and
``from ufpr_automation.sei.browser import ...`` call sites keep working
unchanged) and simply delegate to the helpers below.

The login flow (``auto_login``) and logged-in detection (``is_logged_in``)
stay in the per-system modules because their DOM selectors are entirely
different between SEI and SIGA.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext

from ufpr_automation.config.settings import (
    BROWSER_TIMEOUT_MS,
    SESSION_DIR,
    USER_AGENT,
    VIEWPORT,
)
from ufpr_automation.utils.logging import logger


def has_saved_session(session_file: Path) -> bool:
    """Return True if a non-empty saved session state exists at ``session_file``."""
    return session_file.exists() and session_file.stat().st_size > 0


async def launch_browser(headless: bool = True):
    """Launch a Playwright Chromium instance. Returns ``(pw, browser)``."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    return pw, browser


async def create_browser_context(
    browser: Browser,
    session_file: Path,
    log_label: str,
) -> BrowserContext:
    """Create a browser context, loading saved state at ``session_file`` if present.

    ``log_label`` is the short system name used only in the info log
    (e.g. ``"SEI"``, ``"SIGA"``).
    """
    context_kwargs: dict = {
        "user_agent": USER_AGENT,
        "viewport": VIEWPORT,
        "locale": "pt-BR",
        "timezone_id": "America/Sao_Paulo",
    }

    if has_saved_session(session_file):
        context_kwargs["storage_state"] = str(session_file)
        logger.info("%s: sessao salva carregada", log_label)

    context = await browser.new_context(**context_kwargs)
    context.set_default_timeout(BROWSER_TIMEOUT_MS)
    return context


async def save_session_state(
    context: BrowserContext,
    session_file: Path,
    log_label: str,
) -> None:
    """Persist the context's storage state (cookies + localStorage) to disk."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    state = await context.storage_state()
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("%s: sessao salva em %s", log_label, session_file)
