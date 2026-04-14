"""Browser lifecycle + login automático para UFPR Aberta (Moodle).

Moodle nativo (sem SSO/CAS) — form em /login/index.php.
Sessão salva em session_data/ufpr_aberta_state.json.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

from ufpr_automation.config.settings import (
    BROWSER_TIMEOUT_MS,
    SESSION_DIR,
    UFPR_ABERTA_PASSWORD,
    UFPR_ABERTA_URL,
    UFPR_ABERTA_USERNAME,
    USER_AGENT,
    VIEWPORT,
)
from ufpr_automation.utils.logging import logger

SESSION_FILE = SESSION_DIR / "ufpr_aberta_state.json"
LOGIN_URL = f"{UFPR_ABERTA_URL.rstrip('/')}/login/index.php"


def has_credentials() -> bool:
    return bool(UFPR_ABERTA_USERNAME) and bool(UFPR_ABERTA_PASSWORD)


def has_saved_session() -> bool:
    return SESSION_FILE.exists() and SESSION_FILE.stat().st_size > 0


async def launch_browser(headless: bool = True):
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    return pw, browser


async def create_context(browser: Browser) -> BrowserContext:
    kwargs: dict = {
        "user_agent": USER_AGENT,
        "viewport": VIEWPORT,
        "locale": "pt-BR",
        "timezone_id": "America/Sao_Paulo",
        "accept_downloads": True,
    }
    if has_saved_session():
        kwargs["storage_state"] = str(SESSION_FILE)
        logger.info("UFPR Aberta: sessao salva carregada")
    context = await browser.new_context(**kwargs)
    context.set_default_timeout(BROWSER_TIMEOUT_MS)
    return context


async def save_session(context: BrowserContext) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    state = await context.storage_state()
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("UFPR Aberta: sessao salva em %s", SESSION_FILE)


async def is_logged_in(page: Page) -> bool:
    try:
        # Moodle mostra "loginbox" quando deslogado; "usermenu"/"userinitials"
        # quando logado. Cobrimos os dois.
        if await page.locator(".usermenu, .userinitials, .logininfo a.menu-action").count() > 0:
            return True
        if await page.locator("#loginbox, form[action*='login/index.php'] input[name='password']").count() > 0:
            return False
        # fallback: URL não contém /login/
        return "/login/" not in page.url
    except Exception:
        return False


async def auto_login(page: Page) -> bool:
    if not has_credentials():
        logger.error("UFPR Aberta: LOGING_UFPR_ABERTA/SENHA_UFPR_ABERTA ausentes no .env")
        return False
    try:
        logger.info("UFPR Aberta: login em %s", LOGIN_URL)
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)

        user_input = page.locator("input#username, input[name='username']").first
        await user_input.wait_for(state="visible", timeout=10000)
        await user_input.fill(UFPR_ABERTA_USERNAME)

        pass_input = page.locator("input#password, input[name='password']").first
        await pass_input.fill(UFPR_ABERTA_PASSWORD)

        submit = page.locator(
            "button#loginbtn, input#loginbtn, button[type='submit'], input[type='submit']"
        ).first
        await submit.click()
        await page.wait_for_load_state("networkidle", timeout=30000)

        ok = await is_logged_in(page)
        if ok:
            logger.info("UFPR Aberta: login OK")
        else:
            # debug: salva screenshot + HTML + mensagem de erro do Moodle
            from ufpr_automation.config.settings import DEBUG_OUTPUT_DIR
            DEBUG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            shot = DEBUG_OUTPUT_DIR / "ufpr_aberta_login_fail.png"
            html = DEBUG_OUTPUT_DIR / "ufpr_aberta_login_fail.html"
            try:
                await page.screenshot(path=str(shot), full_page=True)
                html.write_text(await page.content(), encoding="utf-8")
            except Exception:
                pass
            err_loc = page.locator(".loginerrors, .alert-danger, #loginerrormessage")
            err_txt = ""
            if await err_loc.count():
                err_txt = (await err_loc.first.inner_text()).strip()
            logger.warning(
                "UFPR Aberta: login falhou (URL=%s) | erro='%s' | debug=%s",
                page.url, err_txt, shot,
            )
        return ok
    except Exception as e:
        logger.error("UFPR Aberta: falha no login: %s", e)
        return False
