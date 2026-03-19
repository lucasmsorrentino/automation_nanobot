"""Extract the full body text of an email from the OWA reading pane.

After scrape_inbox() populates the inbox list, call extract_email_body() to
click on an individual email and pull out the complete body text (not just the
preview snippet).  The reading pane is left open after extraction so that
responder.py can immediately place the reply without a second click.
"""

from __future__ import annotations

from playwright.async_api import Page


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
        print(f"  ⚠️  Não foi possível clicar no e-mail {email_index}")
        return ""

    # Give OWA a moment to fully render the body
    await page.wait_for_timeout(1_500)

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
        print(f"  ⚠️  Erro na extração JS do corpo: {e}")

    print(f"  ⚠️  Corpo vazio para o e-mail {email_index} — use --debug para inspecionar")
    return ""
