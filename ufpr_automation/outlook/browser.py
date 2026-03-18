"""Browser lifecycle management for Outlook Web Access.

Handles:
- Creating Playwright browser contexts with optional saved state
- Saving session state (cookies + storage) after successful login
- Detecting whether the user is logged in
- Waiting for manual login in headed mode
"""

from __future__ import annotations

import json

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ufpr_automation.config.settings import (
    BROWSER_TIMEOUT_MS,
    LOGIN_TIMEOUT_MS,
    OWA_URL,
    SESSION_DIR,
    SESSION_STATE_FILE,
    USER_AGENT,
    VIEWPORT,
)


def has_saved_session() -> bool:
    """Check if a saved browser session state exists on disk."""
    return SESSION_STATE_FILE.exists() and SESSION_STATE_FILE.stat().st_size > 0


async def create_browser_context(
    browser: Browser,
    headless: bool = True,
) -> BrowserContext:
    """Create a browser context, loading saved state if available.

    Args:
        browser: The Playwright browser instance.
        headless: Whether to run in headless mode (ignored here, set at launch).

    Returns:
        A BrowserContext with session state applied (if available).
    """
    context_kwargs: dict = {
        "user_agent": USER_AGENT,
        "viewport": VIEWPORT,
        "locale": "pt-BR",
        "timezone_id": "America/Sao_Paulo",
    }

    # Load saved state if available
    if has_saved_session():
        context_kwargs["storage_state"] = str(SESSION_STATE_FILE)
        print("🔑 Sessão salva encontrada — carregando cookies e storage...")
    else:
        print("🆕 Nenhuma sessão salva — será necessário fazer login manual.")

    context = await browser.new_context(**context_kwargs)
    context.set_default_timeout(BROWSER_TIMEOUT_MS)

    return context


async def save_session_state(context: BrowserContext) -> None:
    """Save the current browser context state (cookies + storage) to disk.

    Creates the session_data directory if it doesn't exist.
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    state = await context.storage_state()

    with open(SESSION_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print(f"💾 Estado da sessão salvo em: {SESSION_STATE_FILE}")


async def is_logged_in(page: Page) -> bool:
    """Check if the current page shows the OWA inbox (i.e., user is logged in).

    This checks multiple indicators:
    1. URL contains '/mail/' (inbox route)
    2. Presence of inbox-related DOM elements
    """
    current_url = page.url.lower()

    # Check URL pattern
    if "/mail/" in current_url or (
        "outlook.office" in current_url and "login" not in current_url
    ):
        # Double-check by looking for inbox elements
        try:
            inbox_indicators = [
                '[aria-label="Caixa de Entrada"]',
                '[aria-label="Inbox"]',
                '[role="main"]',
                'div[class*="mailList"]',
                "#MailList",
            ]
            for selector in inbox_indicators:
                element = await page.query_selector(selector)
                if element:
                    return True
        except Exception:
            pass

    return False


async def wait_for_login(page: Page) -> bool:
    """Wait for the user to complete manual login in headed mode.

    Navigates to OWA and waits until the inbox is detected or timeout is reached.

    Args:
        page: The Playwright page to use.

    Returns:
        True if login was successful, False if timed out.
    """
    print("\n" + "=" * 60)
    print("🔐 FAÇA LOGIN NO OUTLOOK WEB DA UFPR")
    print("=" * 60)
    print(f"📎 Navegando para: {OWA_URL}")
    print("⏳ Aguardando login manual...")
    print("   (Você tem 5 minutos para completar o login)")
    print("=" * 60 + "\n")

    await page.goto(OWA_URL, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)

    try:
        await page.wait_for_url("**/mail/**", timeout=LOGIN_TIMEOUT_MS)
        print("✅ Login detectado! Redirecionado para a caixa de entrada.")

        # Give OWA a moment to fully load its dynamic content
        await page.wait_for_timeout(3000)
        return True

    except Exception as e:
        print(f"❌ Timeout aguardando login: {e}")
        return False


async def launch_browser(headless: bool = False):
    """Launch a Playwright Chromium browser.

    Args:
        headless: If True, run without a visible window.

    Returns:
        Tuple of (playwright instance, browser instance).
    """
    pw = await async_playwright().start()

    browser = await pw.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    mode = "headless 🖥️" if headless else "com janela visível 🪟"
    print(f"🚀 Navegador Chromium iniciado ({mode})")

    return pw, browser
