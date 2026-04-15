"""Browser lifecycle management for SEI (Sistema Eletronico de Informacoes).

Handles Playwright browser context, session persistence, and automated login.
Low-level context/launch/save helpers live in
``ufpr_automation._session_browser`` and are shared with SIGA; only the
SEI-specific login form and logged-in detection are kept here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

from ufpr_automation import _session_browser
from ufpr_automation.config.settings import (
    SEI_PASSWORD,
    SEI_URL,
    SEI_USERNAME,
    SESSION_DIR,
)
from ufpr_automation.utils.logging import logger

SEI_SESSION_FILE = SESSION_DIR / "sei_state.json"


def has_credentials() -> bool:
    """Check if SEI credentials are configured."""
    return bool(SEI_USERNAME) and bool(SEI_PASSWORD)


def has_saved_session() -> bool:
    """Check if a saved SEI browser session exists."""
    return _session_browser.has_saved_session(SEI_SESSION_FILE)


async def launch_browser(headless: bool = True):
    """Launch Playwright browser for SEI access."""
    return await _session_browser.launch_browser(headless=headless)


async def create_browser_context(
    browser: Browser,
    headless: bool = True,
) -> BrowserContext:
    """Create a browser context with optional saved session state."""
    return await _session_browser.create_browser_context(
        browser, SEI_SESSION_FILE, log_label="SEI"
    )


async def save_session_state(context: BrowserContext) -> None:
    """Save browser session state (cookies + storage) to disk."""
    await _session_browser.save_session_state(
        context, SEI_SESSION_FILE, log_label="SEI"
    )


async def is_logged_in(page: Page) -> bool:
    """Check if the current page shows a logged-in SEI session."""
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
        url = page.url
        # SEI login page typically has /sei/controlador.php?acao=login
        if "acao=login" in url or "login" in url.lower():
            return False
        # Check for the main SEI interface elements
        main_frame = page.locator("#divInfraBarraSistema, #divArvore, #divConteudo")
        if await main_frame.count() > 0:
            return True
        return False
    except Exception:
        return False


async def auto_login(page: Page) -> bool:
    """Perform automated login to SEI using credentials from .env.

    Returns True if login succeeded, False otherwise.
    """
    if not has_credentials():
        logger.error("SEI: credenciais nao configuradas no .env")
        return False

    try:
        logger.info("SEI: iniciando login automatico em %s", SEI_URL)
        await page.goto(SEI_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Fill username
        username_input = page.locator(
            'input#txtUsuario, input[name="txtUsuario"], '
            'input[type="text"][id*="usuario"], input[type="text"][id*="login"]'
        )
        await username_input.first.wait_for(state="visible", timeout=10000)
        await username_input.first.fill(SEI_USERNAME)

        # Fill password
        password_input = page.locator(
            'input#pwdSenha, input[name="pwdSenha"], '
            'input[type="password"]'
        )
        await password_input.first.fill(SEI_PASSWORD)

        # Click login button
        login_button = page.locator(
            'button#sbmLogin, input#sbmLogin, '
            'button[type="submit"], input[type="submit"]'
        )
        await login_button.first.click()

        # Wait for navigation to complete
        await page.wait_for_load_state("networkidle", timeout=30000)

        logged_in = await is_logged_in(page)
        if logged_in:
            logger.info("SEI: login automatico concluido com sucesso")
        else:
            logger.warning("SEI: login pode ter falhado — verificar manualmente")
        return logged_in

    except Exception as e:
        logger.error("SEI: falha no login automatico: %s", e)
        return False
