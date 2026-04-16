#!/usr/bin/env python
"""Smoke test: SEIWriter.create_process in LIVE mode.

Creates a test process with a clear sandbox marker. The resulting process
number is printed + persisted to sei_capture/_state/writer_smoke.json so
the follow-up attach_document + save_despacho_draft smokes can target it.

USAGE:
    .venv/Scripts/python.exe scripts/smoke_create_process_live.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Force live mode regardless of .env.
os.environ["SEI_WRITE_MODE"] = "live"


async def main() -> int:
    from ufpr_automation.config.settings import SEI_URL
    from ufpr_automation.sei.browser import (
        auto_login,
        create_browser_context,
        is_logged_in,
        launch_browser,
        save_session_state,
    )
    from ufpr_automation.sei.writer import SEIWriter

    pw, browser = await launch_browser(headless=False)
    try:
        context = await create_browser_context(browser, headless=False)
        page = await context.new_page()

        # Ensure logged in, reusing saved session if valid.
        await page.goto(SEI_URL, wait_until="domcontentloaded")
        if not await is_logged_in(page):
            ok = await auto_login(page)
            if not ok:
                print("auto_login failed", file=sys.stderr)
                return 2
            await save_session_state(context)

        # Instantiate writer in LIVE mode.
        writer = SEIWriter(page, dry_run=False)
        print(f"writer.dry_run={writer.dry_run} run_id={writer.run_id}")

        marker = f"SMOKE WRITER LIVE — {datetime.now():%Y-%m-%d %H:%M:%S}"
        result = await writer.create_process(
            tipo_processo="Graduação/Ensino Técnico: Estágios não Obrigatórios",
            especificacao=marker,
            interessado="",  # optional
            motivo="",
        )
        print("result.success =", result.success)
        print("result.processo_id =", result.processo_id)
        print("result.error =", result.error)
        print("artifacts:")
        for p in result.artifacts:
            print(f"  - {p}")

        # Persist for follow-up smokes.
        state_dir = Path("ufpr_automation/procedures_data/sei_capture/_state")
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "writer_smoke.json").write_text(
            json.dumps(
                {
                    "process_number": result.processo_id,
                    "especificacao": marker,
                    "created_at": datetime.now().isoformat(),
                    "run_id": writer.run_id,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 0 if result.success else 3
    finally:
        try:
            await browser.close()
        finally:
            await pw.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
