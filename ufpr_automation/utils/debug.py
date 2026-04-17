"""Debug utilities — DOM capture, screenshots, and page inspection.

Used when running with --debug flag to diagnose selector failures
when OWA changes its layout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.config.settings import DEBUG_OUTPUT_DIR


async def capture_debug_info(page: "Page", output_dir: str | Path | None = None) -> None:
    """Capture a screenshot and the full DOM for debugging selector issues.

    Args:
        page: The Playwright page.
        output_dir: Directory to save debug files (defaults to debug_output/).
    """
    debug_path = Path(output_dir) if output_dir else DEBUG_OUTPUT_DIR
    debug_path.mkdir(parents=True, exist_ok=True)

    # Screenshot
    screenshot_path = debug_path / "inbox_screenshot.png"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    print(f"📸 Screenshot salvo: {screenshot_path}")

    # DOM HTML
    html_path = debug_path / "inbox_dom.html"
    html = await page.content()
    html_path.write_text(html, encoding="utf-8")
    print(f"📄 DOM HTML salvo: {html_path}")

    # Page info
    info_path = debug_path / "page_info.json"
    info = {
        "url": page.url,
        "title": await page.title(),
    }
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"ℹ️  Info da página salvo: {info_path}")
