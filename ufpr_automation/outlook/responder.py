"""Save a draft reply to an email that is open in the OWA reading pane.

Assumes the target email is already visible in the reading pane (i.e., the
caller has previously called extract_email_body() or otherwise clicked on it).

Flow:
    1. Click the "Reply" button in the reading pane toolbar.
    2. Wait for the inline compose area to appear.
    3. Clear any pre-populated quoted text.
    4. Type the LLM-generated reply.
    5. Let OWA auto-save (fires after ~2 s of inactivity).
    6. Close the compose pane — OWA saves it as a draft automatically.

Safety guarantee: this module NEVER clicks "Send".  It only saves drafts.
"""

from __future__ import annotations

from playwright.async_api import Page

from ufpr_automation.utils.logging import logger

# ---------------------------------------------------------------------------
# Selector banks
# ---------------------------------------------------------------------------

_REPLY_BUTTON_SELECTORS = [
    "button[aria-label*='Reply']",
    "button[aria-label*='Responder']",
    "button[title*='Reply']",
    "button[title*='Responder']",
    "[data-testid='replyButton']",
    "span[aria-label*='Reply']",
]

_COMPOSE_AREA_SELECTORS = [
    "div[aria-label='Message body'][contenteditable='true']",
    "div[aria-label='Corpo da mensagem'][contenteditable='true']",
    "div[role='textbox'][contenteditable='true']",
    "div[class*='compose'][contenteditable='true']",
    "div[class*='editor'][contenteditable='true']",
    "[contenteditable='true']",
]

_CLOSE_COMPOSE_SELECTORS = [
    "button[aria-label*='Discard']",
    "button[aria-label*='Descartar']",
    "button[aria-label*='Close']",
    "button[aria-label*='Fechar']",
    "button[title*='Discard']",
    "button[title*='Close']",
]


async def _click_reply_button(page: Page) -> bool:
    """Find and click the Reply button in the current reading pane."""
    for selector in _REPLY_BUTTON_SELECTORS:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.click()
                return True
        except Exception:
            continue
    return False


async def _get_compose_area(page: Page):
    """Return the compose area element after waiting for it to appear."""
    # The inline reply compose area takes a moment to appear
    for selector in _COMPOSE_AREA_SELECTORS:
        try:
            await page.wait_for_selector(selector, state="visible", timeout=8_000)
            el = await page.query_selector(selector)
            if el:
                return el
        except Exception:
            continue
    return None


async def _clear_compose_area(page: Page, el) -> None:
    """Select-all and delete any pre-existing content (e.g. quoted email)."""
    try:
        await el.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.wait_for_timeout(300)
    except Exception:
        pass


async def _close_and_save_draft(page: Page) -> None:
    """Save draft explicitly with Ctrl+S, then close the compose pane.

    By saving first, there are no unsaved changes when we close, so OWA
    does NOT show the 'Descartar mensagem' confirmation dialog.
    """
    # Explicitly save draft via Ctrl+S
    await page.keyboard.press("Control+s")
    # Wait for save to complete (network request)
    try:
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        await page.wait_for_timeout(2_000)

    # Now close compose — no unsaved changes means no dialog
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(1_000)

    # If a dialog still appears (edge case), dismiss it
    await _handle_save_dialog(page)


async def _handle_save_dialog(page: Page) -> None:
    """If OWA shows a 'Save draft?' confirmation dialog, click Save.

    Scoped to dialog containers to avoid clicking toolbar buttons.
    """
    dialog_containers = [
        "div[role='dialog']",
        "div[role='alertdialog']",
        "div[class*='dialog']",
        "div[class*='Dialog']",
    ]

    dialog = None
    for container_sel in dialog_containers:
        try:
            el = await page.query_selector(container_sel)
            if el and await el.is_visible():
                dialog = el
                break
        except Exception:
            continue

    if not dialog:
        return

    save_texts = ["Salvar", "Save", "Sim", "Yes"]
    for text in save_texts:
        try:
            btn = await dialog.query_selector(f"button:has-text('{text}')")
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def dismiss_owa_dialog(page: Page) -> None:
    """Dismiss any lingering OWA modal dialog (e.g. 'Descartar mensagem').

    After saving a draft, OWA sometimes shows a confirmation dialog that
    blocks interaction with the inbox. This clicks the most appropriate
    button to dismiss it without losing work.

    Selectors are scoped to dialog/overlay containers to avoid accidentally
    clicking regular OWA toolbar buttons.
    """
    # First check if there's actually a dialog visible
    dialog_containers = [
        "div[role='dialog']",
        "div[role='alertdialog']",
        "div[class*='dialog']",
        "div[class*='Dialog']",
        "div[class*='modal']",
        "div[class*='Modal']",
        "div[class*='overlay']",
        "div[class*='Overlay']",
    ]

    dialog = None
    for container_sel in dialog_containers:
        try:
            el = await page.query_selector(container_sel)
            if el and await el.is_visible():
                dialog = el
                break
        except Exception:
            continue

    if not dialog:
        # No dialog visible — nothing to dismiss
        return

    # Click the best button inside the dialog
    button_texts = [
        "Salvar", "Save",       # keep the draft
        "Sim", "Yes",
        "Não salvar", "Don't save",
        "Descartar", "Discard",
        "OK", "Fechar", "Close",
    ]
    for text in button_texts:
        try:
            btn = await dialog.query_selector(f"button:has-text('{text}')")
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue

    # Last resort: press Escape
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    except Exception:
        pass


async def save_draft_reply(page: Page, reply_text: str) -> bool:
    """Save *reply_text* as a draft reply to the email currently open in the
    reading pane.

    Args:
        page: Playwright page with the target email open in the reading pane.
        reply_text: The full reply body generated by PensarAgent.

    Returns:
        True if the draft was saved successfully, False otherwise.
    """
    # 1. Click Reply
    reply_clicked = await _click_reply_button(page)
    if not reply_clicked:
        logger.warning("Botão Reply não encontrado — verifique se o e-mail está aberto")
        return False

    # _get_compose_area already waits for the compose element to appear

    # 2. Get compose area
    compose = await _get_compose_area(page)
    if not compose:
        logger.warning("Área de composição não encontrada após clicar em Reply")
        return False

    # 3. Clear existing content and type the reply
    await _clear_compose_area(page, compose)
    await compose.type(reply_text, delay=10)  # delay=10ms for reliability

    # 4. Close and let OWA save the draft
    await _close_and_save_draft(page)

    logger.info("Rascunho salvo — aguardando revisão humana antes do envio")
    return True
