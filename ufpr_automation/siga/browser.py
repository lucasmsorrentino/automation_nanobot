"""Browser lifecycle management for SIGA (Sistema Integrado de Gestao Academica).

Handles Playwright browser context, session persistence, and automated login.
Low-level context/launch/save helpers live in
``ufpr_automation._session_browser`` and are shared with SEI; only the
SIGA-specific login form and logged-in detection are kept here.

Login goes through Portal de Sistemas (Keycloak SSO at sistemas.ufpr.br),
then selects the "Coordenação / Secretaria - Graduação" role card.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

from ufpr_automation import _session_browser
from ufpr_automation.config.settings import (
    SESSION_DIR,
    SIGA_PASSWORD,
    SIGA_USERNAME,
)
from ufpr_automation.utils.logging import logger

SIGA_SESSION_FILE = SESSION_DIR / "siga_state.json"

PORTAL_URL = "https://sistemas.ufpr.br"
SIGA_ROLE_TEXT = "Coordenação / Secretaria - Graduação"


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
    """Check if the current page shows a logged-in SIGA session.

    Positive indicators: "Sair" link present AND sidebar menu with
    "Discentes" visible (rules out the public/visitante page).
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
        sair = page.locator("text=Sair")
        discentes = page.locator("a:has-text('Discentes')")
        if await sair.count() > 0 and await discentes.count() > 0:
            return True
        return False
    except Exception:
        return False


async def _wait_for_spinner(page: Page, timeout: int = 60000) -> None:
    """Wait for Vue.js async content to finish loading."""
    try:
        spinner = page.locator(".tab-pane.active >> text=Carregando")
        if await spinner.count() > 0:
            await spinner.first.wait_for(state="hidden", timeout=timeout)
    except Exception:
        pass
    await asyncio.sleep(0.5)


async def auto_login(page: Page) -> bool:
    """Perform automated login via Portal de Sistemas (Keycloak SSO).

    Flow: Portal → Keycloak credentials → role selection → SIGA home.
    Returns True if login succeeded, False otherwise.
    """
    if not has_credentials():
        logger.error("SIGA: credenciais nao configuradas no .env")
        return False

    try:
        logger.info("SIGA: login via Portal de Sistemas %s", PORTAL_URL)
        await page.goto(PORTAL_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20000)

        url = page.url.lower()
        if "login" in url or "auth" in url or "autenticacao" in url:
            logger.info("SIGA: preenchendo credenciais Keycloak")
            user_field = page.locator("input#username").first
            await user_field.wait_for(state="visible", timeout=10000)
            await user_field.fill(SIGA_USERNAME)

            pass_field = page.locator("input#password").first
            await pass_field.fill(SIGA_PASSWORD)

            submit = page.locator("input#kc-login").first
            await submit.click()
            await page.wait_for_load_state("networkidle", timeout=20000)

        # Select the Coordenação role card
        logger.info("SIGA: selecionando papel '%s'", SIGA_ROLE_TEXT)
        role_card = page.locator(f"text={SIGA_ROLE_TEXT}").first
        try:
            await role_card.wait_for(state="visible", timeout=15000)
            await role_card.click()
        except Exception:
            all_cards = page.locator("a, button, [role='button'], .card")
            count = await all_cards.count()
            for i in range(count):
                txt = (await all_cards.nth(i).text_content() or "").strip()
                if "Coordena" in txt and "Gradua" in txt:
                    await all_cards.nth(i).click()
                    break
            else:
                logger.error("SIGA: papel '%s' nao encontrado no portal", SIGA_ROLE_TEXT)
                return False

        await page.wait_for_load_state("networkidle", timeout=20000)
        await asyncio.sleep(2)

        logged_in = await is_logged_in(page)
        if logged_in:
            logger.info("SIGA: login automatico concluido com sucesso")
        else:
            logger.warning("SIGA: login pode ter falhado — verificar manualmente")
        return logged_in

    except Exception as e:
        logger.error("SIGA: falha no login automatico: %s", e)
        return False
