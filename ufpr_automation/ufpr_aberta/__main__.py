"""CLI: python -m ufpr_automation.ufpr_aberta [--headed] [--course-id 9].

Fluxo:
  1. login Moodle (headed na 1a vez; depois headless se sessao salva)
  2. scrape_course -> dump cru em G:/.../ainda_n_ingeridos/ufpr_aberta/bloco_N_*
  3. escreve resumo JSON da estrutura em RAW_ROOT/_structure.json
     (authoring dos .md BLOCO 1/3 e do Mermaid fica em passo manual seguinte,
      feito com o material ja capturado)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from ufpr_automation.ufpr_aberta.browser import (
    auto_login,
    create_context,
    has_saved_session,
    is_logged_in,
    launch_browser,
    save_session,
)
from ufpr_automation.ufpr_aberta.scraper import RAW_ROOT, DEFAULT_COURSE_ID, scrape_course
from ufpr_automation.utils.logging import logger


async def _run(headed: bool, course_id: int) -> int:
    pw, browser = await launch_browser(headless=not headed)
    try:
        context = await create_context(browser)
        page = await context.new_page()

        if not has_saved_session():
            ok = await auto_login(page)
            if not ok:
                logger.error("Login falhou — abortando.")
                return 2
            await save_session(context)
        else:
            from ufpr_automation.config.settings import UFPR_ABERTA_URL
            await page.goto(UFPR_ABERTA_URL, wait_until="domcontentloaded")
            if not await is_logged_in(page):
                logger.info("Sessão expirada; refazendo login.")
                if not await auto_login(page):
                    return 2
                await save_session(context)

        blocks = await scrape_course(page, course_id=course_id)

        RAW_ROOT.mkdir(parents=True, exist_ok=True)
        structure = [
            {
                "index": b.index,
                "title": b.title,
                "activities": [
                    {"name": a.name, "url": a.url, "mod_type": a.mod_type,
                     "html_path": a.html_path, "resources": [asdict(r) for r in a.resources]}
                    for a in b.activities
                ],
            }
            for b in blocks
        ]
        (RAW_ROOT / "_structure.json").write_text(
            json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("UFPR Aberta: estrutura salva em %s/_structure.json", RAW_ROOT)
        logger.info("Cru dos blocos em %s", RAW_ROOT)
        return 0
    finally:
        await browser.close()
        await pw.stop()


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m ufpr_automation.ufpr_aberta")
    p.add_argument("--headed", action="store_true",
                   help="Abre navegador visível (recomendado na 1ª vez)")
    p.add_argument("--course-id", type=int, default=DEFAULT_COURSE_ID,
                   help=f"ID do curso Moodle (default: {DEFAULT_COURSE_ID} — 'Conheça o SIGA!')")
    args = p.parse_args()
    code = asyncio.run(_run(headed=args.headed, course_id=args.course_id))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
