"""Browser lifecycle management for SIGA (Sistema Integrado de Gestao Academica).

Handles Playwright browser context, session persistence, and automated login.
Low-level context/launch/save helpers live in
``ufpr_automation._session_browser`` and are shared with SEI; only the
SIGA-specific login form and logged-in detection are kept here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

from ufpr_automation import _session_browser
from ufpr_automation.config.settings import (
    SESSION_DIR,
    SIGA_PASSWORD,
    SIGA_URL,
    SIGA_USERNAME,
)
from ufpr_automation.utils.logging import logger

SIGA_SESSION_FILE = SESSION_DIR / "siga_state.json"


def has_credentials() -> bool:
    """Check if SIGA credentials are configured."""
    return bool(SIGA_USERNAME) and bool(SIGA_PASSWORD)


def has_saved_session() -> bool:
    """Check if a saved SIGA browser session exists."""
    return _session_browser.has_saved_session(SIGA_SESSION_FILE)


async def launch_browser(headless: bool = True):
    """Launch Playwright browser for SIGA access."""
    return await _session_browser.launch_browser(headless=headless)


async def create_browser_context(
    browser: Browser,
    headless: bool = True,
) -> BrowserContext:
    """Create a browser context with optional saved session state."""
    return await _session_browser.create_browser_context(
        browser, SIGA_SESSION_FILE, log_label="SIGA"
    )


async def save_session_state(context: BrowserContext) -> None:
    """Save browser session state (cookies + storage) to disk."""
    await _session_browser.save_session_state(
        context, SIGA_SESSION_FILE, log_label="SIGA"
    )


async def is_logged_in(page: Page) -> bool:
    """Check if the current page shows a logged-in SIGA session."""
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
        url = page.url
        if "login" in url.lower() or "autenticar" in url.lower():
            return False
        # SIGA main page indicators
        main_content = page.locator("#menu, #conteudo, .navbar, [class*='menu']")
        if await main_content.count() > 0:
            return True
        return False
    except Exception:
        return False


async def auto_login(page: Page) -> bool:
    """Perform automated login to SIGA using credentials from .env.

    Returns True if login succeeded, False otherwise.
    """
    if not has_credentials():
        logger.error("SIGA: credenciais nao configuradas no .env")
        return False

    try:
        logger.info("SIGA: iniciando login automatico em %s", SIGA_URL)
        await page.goto(SIGA_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Fill username
        username_input = page.locator(
            'input[name="login"], input[name="usuario"], '
            'input[type="text"][id*="login"], input[type="text"][id*="usuario"]'
        )
        await username_input.first.wait_for(state="visible", timeout=10000)
        await username_input.first.fill(SIGA_USERNAME)

        # Fill password
        password_input = page.locator(
            'input[name="senha"], input[name="password"], '
            'input[type="password"]'
        )
        await password_input.first.fill(SIGA_PASSWORD)

        # Click login button
        login_button = page.locator(
            'button[type="submit"], input[type="submit"], '
            'input[value="Entrar"], button:has-text("Entrar")'
        )
        await login_button.first.click()

        await page.wait_for_load_state("networkidle", timeout=30000)

        logged_in = await is_logged_in(page)
        if logged_in:
            logger.info("SIGA: login automatico concluido com sucesso")
        else:
            logger.warning("SIGA: login pode ter falhado — verificar manualmente")
        return logged_in

    except Exception as e:
        logger.error("SIGA: falha no login automatico: %s", e)
        return False
