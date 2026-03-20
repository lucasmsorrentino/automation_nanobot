"""Extract the full body text of an email from the OWA reading pane.

After scrape_inbox() populates the inbox list, call extract_email_body() to
click on an individual email and pull out the complete body text (not just the
preview snippet).  The reading pane is left open after extraction so that
responder.py can immediately place the reply without a second click.
"""

from __future__ import annotations

from playwright.async_api import Page

from ufpr_automation.core.models import EmailData
from ufpr_automation.utils.logging import logger

# ---------------------------------------------------------------------------
# Reading-pane body selectors (in preference order)
# ---------------------------------------------------------------------------
_BODY_SELECTORS = [
    "div[aria-label='Message body']",
    "div[aria-label='Corpo da mensagem']",
    "div[class*='ReadingPane'] div[role='document']",
    "div[class*='readingPane'] div[role='document']",
    "div[id='UniqueMessageBody']",
    "div[class*='messageBody']",
    "div[class*='MessageBody']",
    "div[role='document']",
]

# Selectors for individual email rows in the inbox list
_ROW_SELECTORS = [
    "[data-convid]",
    "[role='listitem']",
    "[role='option']",
]


async def _click_email_at_index(page: Page, index: int) -> bool:
    """Click the email at position *index* (0-based) in the inbox list."""
    for row_selector in _ROW_SELECTORS:
        rows = await page.query_selector_all(row_selector)
        if rows and index < len(rows):
            await rows[index].click()
            # Wait for the reading pane to render
            try:
                await page.wait_for_selector(
                    ", ".join(_BODY_SELECTORS[:4]),
                    state="visible",
                    timeout=10_000,
                )
                return True
            except Exception:
                # Reading pane might already have been visible
                return True
    return False


async def extract_email_body(page: Page, email_index: int) -> str:
    """Click the email at *email_index* and extract the full body text.

    Returns the body as plain text, or an empty string if extraction fails.
    The reading pane stays open after this call so responder.py can use it.
    """
    clicked = await _click_email_at_index(page, email_index)
    if not clicked:
        logger.warning("Não foi possível clicar no e-mail %d", email_index)
        return ""

    # Wait for a body element to become visible instead of a fixed delay
    try:
        await page.wait_for_selector(
            ", ".join(_BODY_SELECTORS[:4]),
            state="visible",
            timeout=8_000,
        )
    except Exception:
        # Fallback: short wait if no body selector matched
        await page.wait_for_timeout(1_000)

    # Try each body selector
    for selector in _BODY_SELECTORS:
        try:
            el = await page.query_selector(selector)
            if el:
                text = (await el.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue

    # Last resort: JS extraction from the reading pane area
    try:
        text = await page.evaluate("""
            () => {
                const candidates = [
                    document.querySelector("div[aria-label='Message body']"),
                    document.querySelector("div[role='document']"),
                    document.querySelector("div[id='UniqueMessageBody']"),
                ];
                for (const el of candidates) {
                    if (el && el.innerText && el.innerText.trim().length > 10) {
                        return el.innerText.trim();
                    }
                }
                return '';
            }
        """)
        if text:
            return text
    except Exception as e:
        logger.warning("Erro na extração JS do corpo: %s", e)

    logger.warning("Corpo vazio para o e-mail %d — use --debug para inspecionar", email_index)
    return ""


# ---------------------------------------------------------------------------
# Reading-pane subject selectors (for identity verification)
# ---------------------------------------------------------------------------
_SUBJECT_SELECTORS = [
    "div[class*='SubjectLine'] span",
    "[aria-label*='Assunto'] span",
    "[aria-label*='Subject'] span",
    "span[class*='subject']",
    "span[class*='Subject']",
]


async def verify_opened_email(page: Page, expected: EmailData) -> bool:
    """Check that the email currently open in the reading pane matches *expected*.

    Compares the subject line visible in the reading pane against the expected
    email's subject. This guards against the inbox shifting between pipeline
    phases, which would cause the positional index to point to the wrong email.

    Returns True if the subject matches (or if verification cannot be performed),
    False if a definite mismatch is detected.
    """
    for selector in _SUBJECT_SELECTORS:
        try:
            el = await page.query_selector(selector)
            if el:
                visible_subject = (await el.inner_text()).strip()
                if visible_subject and expected.subject:
                    # Normalize: compare lowered, trimmed first 50 chars
                    if visible_subject[:50].lower() == expected.subject[:50].lower():
                        return True
                    # Definite mismatch
                    logger.warning(
                        "MISMATCH: esperado '%s' mas encontrou '%s'",
                        expected.subject[:50], visible_subject[:50],
                    )
                    return False
        except Exception:
            continue

    # Could not verify — allow to proceed (best-effort)
    return True
