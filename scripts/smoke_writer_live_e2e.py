#!/usr/bin/env python
"""End-to-end live smoke for SEIWriter — create + attach + despacho.

Exercises all 3 write ops in sequence against the real SEI:
    1. create_process → returns a new process number
    2. attach_document → uploads dummy_tce.pdf as Restrito/Termo
    3. save_despacho_draft → creates a draft Despacho with a short body

Intended to leave the resulting process as a full MVP sample in CCDG
(with Termo anexado + Despacho rascunho), which the human can inspect
and then delete/annul.

USAGE:
    .venv/Scripts/python.exe scripts/smoke_writer_live_e2e.py
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

os.environ["SEI_WRITE_MODE"] = "live"

DUMMY_PDF = Path("ufpr_automation/procedures_data/sei_capture/dummy_tce.pdf")


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
    from ufpr_automation.sei.writer_models import SEIDocClassification

    pw, browser = await launch_browser(headless=False)
    try:
        context = await create_browser_context(browser, headless=False)
        page = await context.new_page()

        await page.goto(SEI_URL, wait_until="domcontentloaded")
        if not await is_logged_in(page):
            ok = await auto_login(page)
            if not ok:
                print("auto_login failed", file=sys.stderr)
                return 2
            await save_session_state(context)

        writer = SEIWriter(page, dry_run=False)
        print(f"writer.run_id={writer.run_id}")

        # 1) Create process
        marker = f"SMOKE E2E — {datetime.now():%Y-%m-%d %H:%M:%S}"
        print("\n=== 1/3 create_process ===")
        cr = await writer.create_process(
            tipo_processo="Graduação/Ensino Técnico: Estágios não Obrigatórios",
            especificacao=marker,
            interessado="",
        )
        print(f"  success={cr.success} processo_id={cr.processo_id} error={cr.error}")
        if not cr.success:
            return 3
        proc_id = cr.processo_id

        # 2) Attach document
        print("\n=== 2/3 attach_document ===")
        classification = SEIDocClassification(
            sei_tipo="Externo",
            sei_subtipo="Termo",
            sei_classificacao="Inicial",
            sigiloso=True,  # Restrito with Hipótese Legal 34
            motivo_sigilo="Informação Pessoal",
            data_documento=datetime.now().strftime("%Y-%m-%d"),
        )
        at = await writer.attach_document(proc_id, DUMMY_PDF, classification)
        print(f"  success={at.success} error={at.error}")
        for p in at.artifacts:
            print(f"    artifact: {p}")

        # 3) Save despacho draft
        print("\n=== 3/3 save_despacho_draft ===")
        body = (
            "Prezados,\n\n"
            "Acusamos o recebimento do TCE e encaminhamos para análise.\n\n"
            "Atenciosamente,\nCoordenação CCDG (smoke test — IGNORE)\n"
        )
        dr = await writer.save_despacho_draft(
            proc_id,
            tipo="tce_acuse_smoke",
            body_override=body,
        )
        print(f"  success={dr.success} error={dr.error}")
        for p in dr.artifacts:
            print(f"    artifact: {p}")

        # Persist result.
        state_dir = Path("ufpr_automation/procedures_data/sei_capture/_state")
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "writer_e2e_smoke.json").write_text(
            json.dumps(
                {
                    "processo_id": proc_id,
                    "especificacao": marker,
                    "created_at": datetime.now().isoformat(),
                    "run_id": writer.run_id,
                    "create": {"success": cr.success, "error": cr.error},
                    "attach": {"success": at.success, "error": at.error},
                    "draft": {"success": dr.success, "error": dr.error},
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(
            f"\n--- e2e smoke complete ---\n"
            f"Process created in CCDG: {proc_id}\n"
            f"Delete/annul this after inspection."
        )
        return 0 if (cr.success and at.success and dr.success) else 4
    finally:
        try:
            await browser.close()
        finally:
            await pw.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
