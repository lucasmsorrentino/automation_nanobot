"""Browser lifecycle management for Outlook Web Access.

Handles:
- Creating Playwright browser contexts with optional saved state
- Saving session state (cookies + storage) after successful login
- Detecting whether the user is logged in
- Automated login with credential filling and MFA number-match via Telegram
"""

from __future__ import annotations

import json

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ufpr_automation.config.settings import (
    BROWSER_TIMEOUT_MS,
    LOGIN_TIMEOUT_MS,
    OWA_EMAIL,
    OWA_PASSWORD,
    OWA_URL,
    SESSION_DIR,
    SESSION_STATE_FILE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
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


async def _send_telegram_notification(text: str) -> None:
    """Send a notification message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Telegram não configurado — defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env")
        return
    try:
        from telegram import Bot

        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
        print("📲 Notificação enviada via Telegram.")
    except Exception as e:
        print(f"⚠️  Falha ao enviar Telegram: {e}")


def has_credentials() -> bool:
    """Check if OWA login credentials are configured."""
    return bool(OWA_EMAIL) and bool(OWA_PASSWORD)


async def auto_login(page: Page) -> bool:
    """Automated login: fill credentials, handle MFA number-match via Telegram.

    Flow:
    1. Navigate to OWA → Microsoft redirects to login page
    2. Fill email → click Next
    3. Fill password → click Sign In
    4. Detect MFA number-match screen → extract number → send via Telegram
    5. Wait for user to approve on Microsoft Authenticator
    6. Detect inbox URL → return success

    Falls back to wait_for_manual_login() if credentials are not configured.

    Returns:
        True if login was successful, False if timed out.
    """
    if not has_credentials():
        print("⚠️  Credenciais não configuradas — usando login manual.")
        return await wait_for_manual_login(page)

    print("\n" + "=" * 60)
    print("🤖 LOGIN AUTOMÁTICO — UFPR Outlook")
    print("=" * 60)
    print(f"📎 Navegando para: {OWA_URL}")

    await page.goto(OWA_URL, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)

    try:
        # --- Step 1: Email ---
        print(f"📧 Preenchendo e-mail: {OWA_EMAIL}")
        email_input = page.locator('input[type="email"], input[name="loginfmt"]')
        await email_input.wait_for(state="visible", timeout=30000)
        await email_input.fill(OWA_EMAIL)
        await page.locator('input[type="submit"], #idSIButton9').click()
        await page.wait_for_timeout(2000)

        # --- Step 2: Password ---
        print("🔑 Preenchendo senha...")
        password_input = page.locator('input[type="password"], input[name="passwd"]')
        await password_input.wait_for(state="visible", timeout=30000)
        await password_input.fill(OWA_PASSWORD)
        await page.locator('input[type="submit"], #idSIButton9').click()
        await page.wait_for_timeout(3000)

        # --- Step 3: MFA Number Match ---
        # Microsoft shows a 2-digit number the user must tap on Authenticator
        mfa_number = await _extract_mfa_number(page)
        if mfa_number:
            print(f"\n{'=' * 40}")
            print(f"   📱 NÚMERO MFA: {mfa_number}")
            print(f"{'=' * 40}")
            print("   Aprove no Microsoft Authenticator com este número.\n")
            await _send_telegram_notification(
                f"🔐 UFPR Login — Número MFA: {mfa_number}\n"
                f"Aprove no Microsoft Authenticator."
            )

        # --- Step 4: Wait for redirect to inbox ---
        print("⏳ Aguardando aprovação MFA...")
        await page.wait_for_url("**/mail/**", timeout=LOGIN_TIMEOUT_MS)
        print("✅ Login detectado! Redirecionado para a caixa de entrada.")

        # Handle "Stay signed in?" prompt if it appears
        try:
            stay_signed_in = page.locator('#idSIButton9, input[value="Yes"]')
            await stay_signed_in.click(timeout=5000)
        except Exception:
            pass

        await page.wait_for_timeout(3000)
        await _send_telegram_notification("✅ Login UFPR concluído com sucesso!")
        return True

    except Exception as e:
        print(f"❌ Falha no login automático: {e}")
        await _send_telegram_notification(f"❌ Falha no login UFPR: {e}")
        return False


async def _extract_mfa_number(page: Page) -> str | None:
    """Extract the MFA number-match code from Microsoft's login page.

    Microsoft Authenticator number matching shows a 2-digit number that the user
    must tap on their phone to approve the sign-in.
    """
    # Common selectors for the MFA number display
    selectors = ["#displaySign", ".display-sign", 'div[id="displaySign"]']
    for selector in selectors:
        try:
            element = page.locator(selector)
            await element.wait_for(state="visible", timeout=10000)
            text = await element.text_content()
            if text and text.strip().isdigit():
                return text.strip()
        except Exception:
            continue

    # Fallback: look for a prominent 2-digit number in the page
    try:
        # Microsoft sometimes uses different structures
        number_el = page.locator("div.display-sign-container, .number-match-display")
        await number_el.wait_for(state="visible", timeout=5000)
        text = await number_el.text_content()
        if text and text.strip().isdigit():
            return text.strip()
    except Exception:
        pass

    return None


async def wait_for_manual_login(page: Page) -> bool:
    """Wait for the user to complete manual login in headed mode.

    Navigates to OWA and waits until the inbox is detected or timeout is reached.

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
