"""Outlook Web Access integration package.

Provides browser lifecycle management and inbox scraping via Playwright.
"""

from ufpr_automation.outlook.browser import (  # noqa: F401
    auto_login,
    create_browser_context,
    has_credentials,
    has_saved_session,
    is_logged_in,
    launch_browser,
    save_session_state,
    wait_for_manual_login,
)
from ufpr_automation.outlook.scraper import scrape_inbox  # noqa: F401
