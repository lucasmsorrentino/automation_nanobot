"""Resilient locator fallback chain for OWA Playwright selectors.

Provides a cascading locator strategy that tries multiple approaches
in order of resilience:
  1. Semantic (role, aria-label) — most resilient to UI changes
  2. Text-based (visible text content)
  3. ID-based (data-testid, id, data-convid)
  4. CSS class-based (fragile, last resort)

Each OWA element has a named LocatorChain that encapsulates all
strategies. If OWA updates its DOM, only the chain definitions
here need to change — not the calling code.

Usage:
    from ufpr_automation.outlook.locators import find_element, click_element

    el = await find_element(page, "reply_button")
    ok = await click_element(page, "reply_button")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Page

from ufpr_automation.utils.logging import logger


@dataclass
class LocatorStrategy:
    """A single locator strategy with a CSS selector and approach name."""

    selector: str
    approach: str  # "semantic", "text", "id", "css"
    description: str = ""


@dataclass
class LocatorChain:
    """Ordered list of locator strategies for a single UI element."""

    name: str
    strategies: list[LocatorStrategy] = field(default_factory=list)


# ===========================================================================
# Locator chain definitions for OWA elements
# ===========================================================================

CHAINS: dict[str, LocatorChain] = {
    # --- Inbox list container ---
    "inbox_list": LocatorChain(
        name="inbox_list",
        strategies=[
            LocatorStrategy('[role="list"]', "semantic", "ARIA list role"),
            LocatorStrategy('div[aria-label*="message list"]', "semantic", "aria-label EN"),
            LocatorStrategy('div[aria-label*="lista de mensagens"]', "semantic", "aria-label PT"),
            LocatorStrategy('#MailList', "id", "legacy ID"),
            LocatorStrategy('div[data-app-section="MailList"]', "id", "data-app-section"),
        ],
    ),
    # --- Email rows in inbox ---
    "email_row": LocatorChain(
        name="email_row",
        strategies=[
            LocatorStrategy('[role="listitem"]', "semantic", "ARIA listitem"),
            LocatorStrategy('[role="option"]', "semantic", "ARIA option"),
            LocatorStrategy('[data-convid]', "id", "conversation ID attribute"),
            LocatorStrategy('[data-mid]', "id", "message ID attribute"),
            LocatorStrategy('div[class*="customScrollBar"] > div > div > div', "css", "scroll container children"),
        ],
    ),
    # --- Sender element within email row ---
    "sender": LocatorChain(
        name="sender",
        strategies=[
            LocatorStrategy('[data-testid*="sender"]', "id", "testid sender"),
            LocatorStrategy('span[title]', "semantic", "span with title attr"),
            LocatorStrategy('[class*="sender"]', "css", "class contains sender"),
            LocatorStrategy('[class*="from"]', "css", "class contains from"),
        ],
    ),
    # --- Subject element within email row ---
    "subject": LocatorChain(
        name="subject",
        strategies=[
            LocatorStrategy('[data-testid*="subject"]', "id", "testid subject"),
            LocatorStrategy('[class*="subject"]', "css", "class contains subject"),
            LocatorStrategy('[class*="Subject"]', "css", "class contains Subject"),
        ],
    ),
    # --- Preview element within email row ---
    "preview": LocatorChain(
        name="preview",
        strategies=[
            LocatorStrategy('[class*="preview"]', "css", "class contains preview"),
            LocatorStrategy('[class*="Preview"]', "css", "class contains Preview"),
            LocatorStrategy('[class*="snippet"]', "css", "class contains snippet"),
        ],
    ),
    # --- Reading pane body ---
    "message_body": LocatorChain(
        name="message_body",
        strategies=[
            LocatorStrategy("div[aria-label='Message body']", "semantic", "aria-label EN"),
            LocatorStrategy("div[aria-label='Corpo da mensagem']", "semantic", "aria-label PT"),
            LocatorStrategy("div[class*='ReadingPane'] div[role='document']", "semantic", "reading pane document role"),
            LocatorStrategy("div[class*='readingPane'] div[role='document']", "semantic", "reading pane document role (lower)"),
            LocatorStrategy("div[id='UniqueMessageBody']", "id", "UniqueMessageBody"),
            LocatorStrategy("div[class*='messageBody']", "css", "class messageBody"),
            LocatorStrategy("div[class*='MessageBody']", "css", "class MessageBody"),
            LocatorStrategy("div[role='document']", "semantic", "generic document role"),
        ],
    ),
    # --- Reply button ---
    "reply_button": LocatorChain(
        name="reply_button",
        strategies=[
            LocatorStrategy("button[aria-label*='Responder']", "semantic", "aria-label PT"),
            LocatorStrategy("button[aria-label*='Reply']", "semantic", "aria-label EN"),
            LocatorStrategy("button[title*='Responder']", "text", "title PT"),
            LocatorStrategy("button[title*='Reply']", "text", "title EN"),
            LocatorStrategy("[data-testid='replyButton']", "id", "testid"),
            LocatorStrategy("span[aria-label*='Reply']", "semantic", "span aria-label"),
        ],
    ),
    # --- Compose area (contenteditable) ---
    "compose_area": LocatorChain(
        name="compose_area",
        strategies=[
            LocatorStrategy("div[aria-label='Corpo da mensagem'][contenteditable='true']", "semantic", "aria-label PT + contenteditable"),
            LocatorStrategy("div[aria-label='Message body'][contenteditable='true']", "semantic", "aria-label EN + contenteditable"),
            LocatorStrategy("div[role='textbox'][contenteditable='true']", "semantic", "textbox role"),
            LocatorStrategy("div[class*='compose'][contenteditable='true']", "css", "compose class"),
            LocatorStrategy("div[class*='editor'][contenteditable='true']", "css", "editor class"),
            LocatorStrategy("[contenteditable='true']", "semantic", "any contenteditable"),
        ],
    ),
    # --- Subject line in reading pane (for verification) ---
    "reading_pane_subject": LocatorChain(
        name="reading_pane_subject",
        strategies=[
            LocatorStrategy("div[class*='SubjectLine'] span", "css", "SubjectLine class"),
            LocatorStrategy("[aria-label*='Assunto'] span", "semantic", "aria-label Assunto"),
            LocatorStrategy("[aria-label*='Subject'] span", "semantic", "aria-label Subject"),
            LocatorStrategy("span[class*='subject']", "css", "class subject"),
            LocatorStrategy("span[class*='Subject']", "css", "class Subject"),
        ],
    ),
    # --- Unread indicator ---
    "unread_indicator": LocatorChain(
        name="unread_indicator",
        strategies=[
            LocatorStrategy("[aria-label*='Não lido']", "semantic", "aria-label PT"),
            LocatorStrategy("[aria-label*='Unread']", "semantic", "aria-label EN"),
            LocatorStrategy("[class*='unread']", "css", "class unread"),
            LocatorStrategy("[class*='Unread']", "css", "class Unread"),
        ],
    ),
    # --- Dialog containers ---
    "dialog": LocatorChain(
        name="dialog",
        strategies=[
            LocatorStrategy("div[role='dialog']", "semantic", "ARIA dialog"),
            LocatorStrategy("div[role='alertdialog']", "semantic", "ARIA alertdialog"),
            LocatorStrategy("div[class*='dialog']", "css", "class dialog"),
            LocatorStrategy("div[class*='Dialog']", "css", "class Dialog"),
            LocatorStrategy("div[class*='modal']", "css", "class modal"),
            LocatorStrategy("div[class*='Modal']", "css", "class Modal"),
            LocatorStrategy("div[class*='overlay']", "css", "class overlay"),
        ],
    ),
}


# ===========================================================================
# Public API
# ===========================================================================


async def find_element(
    page: Page,
    chain_name: str,
    *,
    parent=None,
    timeout: int = 0,
    visible_only: bool = True,
) -> Optional:
    """Find an element using the named locator chain.

    Args:
        page: Playwright page.
        chain_name: Key in CHAINS dict.
        parent: Optional parent element to scope the search.
        timeout: If > 0, wait up to this many ms for the first match.
        visible_only: Only return visible elements.

    Returns:
        The first matching element, or None.
    """
    chain = CHAINS.get(chain_name)
    if not chain:
        logger.warning("Unknown locator chain: %s", chain_name)
        return None

    context = parent or page

    for strategy in chain.strategies:
        try:
            if timeout > 0:
                try:
                    await page.wait_for_selector(
                        strategy.selector, state="visible", timeout=timeout
                    )
                except Exception:
                    pass

            el = await context.query_selector(strategy.selector)
            if el:
                if visible_only:
                    try:
                        if not await el.is_visible():
                            continue
                    except Exception:
                        pass
                logger.debug(
                    "Locator '%s': matched via %s (%s)",
                    chain_name, strategy.approach, strategy.description,
                )
                return el
        except Exception:
            continue

    logger.debug("Locator '%s': no match found", chain_name)
    return None


async def find_all_elements(
    page: Page,
    chain_name: str,
    *,
    parent=None,
) -> list:
    """Find all elements matching the first successful strategy in the chain.

    Args:
        page: Playwright page.
        chain_name: Key in CHAINS dict.
        parent: Optional parent element to scope the search.

    Returns:
        List of matching elements (may be empty).
    """
    chain = CHAINS.get(chain_name)
    if not chain:
        logger.warning("Unknown locator chain: %s", chain_name)
        return []

    context = parent or page

    for strategy in chain.strategies:
        try:
            elements = await context.query_selector_all(strategy.selector)
            if elements:
                logger.debug(
                    "Locator '%s': %d match(es) via %s (%s)",
                    chain_name, len(elements), strategy.approach, strategy.description,
                )
                return elements
        except Exception:
            continue

    return []


async def click_element(
    page: Page,
    chain_name: str,
    *,
    timeout: int = 5000,
) -> bool:
    """Find and click an element using the named locator chain.

    Args:
        page: Playwright page.
        chain_name: Key in CHAINS dict.
        timeout: Max wait time in ms.

    Returns:
        True if clicked successfully, False if not found.
    """
    el = await find_element(page, chain_name, timeout=timeout)
    if el:
        try:
            await el.click()
            return True
        except Exception as e:
            logger.warning("Click failed for '%s': %s", chain_name, e)
    return False


async def get_text(
    page: Page,
    chain_name: str,
    *,
    parent=None,
    timeout: int = 0,
) -> str:
    """Find an element and return its inner text.

    Returns empty string if not found.
    """
    el = await find_element(page, chain_name, parent=parent, timeout=timeout)
    if el:
        try:
            return (await el.inner_text()).strip()
        except Exception:
            pass
    return ""


async def wait_for_any(
    page: Page,
    chain_name: str,
    *,
    timeout: int = 15000,
) -> bool:
    """Wait for any selector in the chain to become visible.

    Args:
        page: Playwright page.
        chain_name: Key in CHAINS dict.
        timeout: Max wait per selector.

    Returns:
        True if any selector matched.
    """
    chain = CHAINS.get(chain_name)
    if not chain:
        return False

    per_selector_timeout = max(timeout // len(chain.strategies), 2000)

    for strategy in chain.strategies:
        try:
            await page.wait_for_selector(
                strategy.selector, state="visible", timeout=per_selector_timeout
            )
            logger.debug(
                "wait_for_any '%s': found via %s (%s)",
                chain_name, strategy.approach, strategy.description,
            )
            return True
        except Exception:
            continue

    return False
