"""OWA Inbox Scraper — extracts email metadata from Outlook Web Access.

Uses Playwright to navigate the OWA inbox and extract:
- Sender name/email
- Subject line
- Preview text
for all visible unread emails.

Employs three fallback strategies to handle different OWA versions:
1. Modern React-based selectors
2. Aria-label attribute parsing
3. JavaScript DOM extraction
"""

from __future__ import annotations

from playwright.async_api import Page

from ufpr_automation.config.settings import BROWSER_TIMEOUT_MS
from ufpr_automation.core.models import EmailData
from ufpr_automation.utils.logging import logger


async def wait_for_inbox_load(page: Page) -> bool:
    """Wait for the OWA inbox to fully load its dynamic content.

    OWA uses React and lazy-loading, so we need to wait for specific DOM elements.

    Returns:
        True if inbox loaded successfully, False otherwise.
    """
    try:
        selectors_to_try = [
            '[role="list"]',
            'div[aria-label*="message list"]',
            'div[aria-label*="lista de mensagens"]',
            "#MailList",
            'div[data-app-section="MailList"]',
        ]

        for selector in selectors_to_try:
            try:
                await page.wait_for_selector(
                    selector, state="visible", timeout=15_000
                )
                logger.info("Inbox carregada (selector: %s)", selector)
                return True
            except Exception:
                continue

        # Fallback: wait for any substantial content to load
        logger.warning("Nenhum selector padrão encontrado — tentando fallback genérico...")
        await page.wait_for_load_state("networkidle", timeout=BROWSER_TIMEOUT_MS)
        return True

    except Exception as e:
        logger.error("Erro ao aguardar carregamento da inbox: %s", e)
        return False


async def scrape_inbox(page: Page) -> list[EmailData]:
    """Scrape visible emails from the OWA inbox.

    Navigates through the DOM to extract email metadata for all visible messages.
    Uses three fallback strategies to handle different OWA versions.

    Args:
        page: A Playwright page that is already on the OWA inbox.

    Returns:
        List of EmailData objects with sender, subject, preview for each email.
    """
    emails: list[EmailData] = []

    logger.info("Iniciando varredura da caixa de entrada...")

    loaded = await wait_for_inbox_load(page)
    if not loaded:
        logger.error("Não foi possível carregar a caixa de entrada.")
        return emails

    # Wait for dynamic content to settle (network-based, with fixed fallback)
    try:
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        await page.wait_for_timeout(1_500)

    # Strategy 1: Modern OWA selectors (React-based)
    emails = await _scrape_modern_owa(page)

    # Strategy 2: Aria-label attribute parsing
    if not emails:
        logger.info("Tentando seletores alternativos...")
        emails = await _scrape_generic_owa(page)

    # Strategy 3: JavaScript DOM extraction
    if not emails:
        logger.info("Tentando extração via JavaScript...")
        emails = await _scrape_via_javascript(page)

    if emails:
        logger.info("%d e-mail(s) encontrado(s) na caixa de entrada", len(emails))
        for i, email in enumerate(emails, 1):
            logger.info("  %d. %s", i, email)
    else:
        logger.warning(
            "Nenhum e-mail encontrado. A caixa de entrada pode estar vazia "
            "ou os seletores do OWA podem ter mudado. Execute com --debug."
        )

    return emails


# ---------------------------------------------------------------------------
# Private scraping strategies
# ---------------------------------------------------------------------------


async def _scrape_modern_owa(page: Page) -> list[EmailData]:
    """Strategy 1: scrape using modern OWA (React) selectors."""
    emails: list[EmailData] = []

    try:
        items = await page.query_selector_all(
            '[role="listitem"], [role="option"], [data-convid], '
            'div[class*="customScrollBar"] > div > div > div'
        )

        if not items:
            return emails

        for item in items:
            email = EmailData()

            sender_el = await item.query_selector(
                '[class*="sender"], [class*="from"], span[title], '
                '[data-testid*="sender"]'
            )
            if sender_el:
                email.sender = (await sender_el.inner_text()).strip()

            subject_el = await item.query_selector(
                '[class*="subject"], [class*="Subject"], '
                '[data-testid*="subject"]'
            )
            if subject_el:
                email.subject = (await subject_el.inner_text()).strip()

            preview_el = await item.query_selector(
                '[class*="preview"], [class*="Preview"], [class*="snippet"]'
            )
            if preview_el:
                email.preview = (await preview_el.inner_text()).strip()

            # OWA marks unread emails via aria-label on the row itself
            # (e.g. "Não lidos Recolhido Tem anexos ...") — check that first.
            row_label = (await item.get_attribute("aria-label") or "").lower()
            if "não lido" in row_label or "unread" in row_label:
                email.is_unread = True
            else:
                unread_indicator = await item.query_selector(
                    '[class*="unread"], [class*="Unread"], '
                    '[aria-label*="Não lido"], [aria-label*="Unread"]'
                )
                email.is_unread = unread_indicator is not None

            if email.sender or email.subject:
                emails.append(email)

    except Exception as e:
        logger.warning("Erro na extração moderna: %s", e)

    return emails


async def _scrape_generic_owa(page: Page) -> list[EmailData]:
    """Strategy 2: generic scraping using aria attributes and common patterns."""
    emails: list[EmailData] = []

    try:
        items = await page.query_selector_all(
            '[aria-label*="mensagem"], [aria-label*="message"], '
            '[aria-label*="De:"], [aria-label*="From:"]'
        )

        for item in items:
            email = EmailData()
            label = await item.get_attribute("aria-label") or ""

            if label:
                parts = label.split(",")
                for part in parts:
                    part = part.strip()
                    if part.lower().startswith(("de:", "from:")):
                        email.sender = part.split(":", 1)[1].strip()
                    elif part.lower().startswith(("assunto:", "subject:")):
                        email.subject = part.split(":", 1)[1].strip()

                if not email.sender and not email.subject:
                    email.subject = label[:100]

                email.is_unread = (
                    "não lido" in label.lower() or "unread" in label.lower()
                )

            if email.sender or email.subject:
                emails.append(email)

    except Exception as e:
        logger.warning("Erro na extração genérica: %s", e)

    return emails


async def _scrape_via_javascript(page: Page) -> list[EmailData]:
    """Strategy 3: last-resort scraping using JavaScript DOM evaluation."""
    emails: list[EmailData] = []

    try:
        result = await page.evaluate("""
            () => {
                const emails = [];
                const rows = document.querySelectorAll(
                    '[data-convid], [data-mid], [role="listitem"], [role="option"]'
                );
                rows.forEach(row => {
                    const text = row.innerText || '';
                    const lines = text.split('\\n')
                        .map(l => l.trim())
                        .filter(l => l.length > 0);
                    if (lines.length >= 2) {
                        emails.push({
                            sender: lines[0] || '',
                            subject: lines[1] || '',
                            preview: lines.slice(2).join(' ').substring(0, 200) || '',
                            is_unread:
                                row.classList.toString().toLowerCase().includes('unread') ||
                                (row.getAttribute('aria-label') || '').toLowerCase().includes('unread') ||
                                (row.getAttribute('aria-label') || '').toLowerCase().includes('não lido') ||
                                false
                        });
                    }
                });
                return emails;
            }
        """)

        if result:
            for item in result:
                emails.append(
                    EmailData(
                        sender=item.get("sender", ""),
                        subject=item.get("subject", ""),
                        preview=item.get("preview", ""),
                        is_unread=item.get("is_unread", False),
                    )
                )

    except Exception as e:
        logger.warning("Erro na extração via JavaScript: %s", e)

    return emails
