#!/usr/bin/env python
"""Read-only SIGA DOM capture for internship eligibility selectors.

Flow: Portal de Sistemas (SSO) → select role → Discentes → Consultar →
      search student → tabs Histórico / Integralização / Estágio.
Captures screenshots + innerHTML dumps for each step.
NEVER clicks write actions (Salvar, Editar, etc.).

USAGE:
    python scripts/siga_capture_estagios.py [--grr GRR20XXXXXX]
    python scripts/siga_capture_estagios.py --nome "MARIO CASTELLO"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

CAPTURE_DIR = _REPO_ROOT / "ufpr_automation" / "docs" / "ss_SIGA" / "capture"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
PORTAL_URL = "https://sistemas.ufpr.br"
SIGA_ROLE_TEXT = "Coordenação / Secretaria - Graduação"


async def wait_for_content(page, timeout: int = 60000) -> None:
    """Wait for Vue.js async content to load inside the active tab-pane."""
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    # Wait for the active tab-pane to have real content (not just "Carregando...")
    # Poll until the active tab has a table or the spinner text is gone
    active_tab = page.locator(".tab-pane.active")
    spinner_in_tab = active_tab.locator("text=Carregando")
    import time
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        # Check if spinner is gone from the active tab
        if await spinner_in_tab.count() == 0:
            break
        # Check if spinner is still visible
        try:
            visible = await spinner_in_tab.first.is_visible()
            if not visible:
                break
        except Exception:
            break
        await asyncio.sleep(2)
    await asyncio.sleep(1)


async def save(page, name: str, out_dir: Path) -> None:
    """Screenshot + innerHTML dump."""
    await wait_for_content(page)
    ss = out_dir / f"{name}.png"
    await page.screenshot(path=str(ss), full_page=True)
    print(f"  screenshot: {ss.name}")

    html = out_dir / f"{name}.html"
    content = await page.content()
    html.write_text(content, encoding="utf-8")
    print(f"  DOM dump:   {html.name}")


async def dump_links(page, label: str, limit: int = 30) -> None:
    """Print all links visible on the page for debugging."""
    links = await page.query_selector_all("a")
    print(f"  [{label}] Found {len(links)} links:")
    for el in links[:limit]:
        txt = (await el.text_content() or "").strip().replace("\n", " ")[:60]
        href = await el.get_attribute("href") or ""
        if txt or href:
            print(f"    [{txt}] → {href[:80]}")


async def main(grr: str | None, nome: str | None) -> int:
    from playwright.async_api import async_playwright

    from ufpr_automation.config.settings import SIGA_PASSWORD, SIGA_USERNAME

    if not SIGA_USERNAME or not SIGA_PASSWORD:
        print("ERROR: SIGA_USERNAME / SIGA_PASSWORD not set in .env", file=sys.stderr)
        return 2

    out_dir = CAPTURE_DIR / TIMESTAMP
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Capture dir: {out_dir}")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context(
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
    )
    context.set_default_timeout(30000)
    page = await context.new_page()

    try:
        # --- Step 1: Portal de Sistemas login ---
        print("\n[1/8] Portal de Sistemas login...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await save(page, "00_portal_landing", out_dir)

        # Check if we need to login (look for login form or redirect)
        url = page.url.lower()
        if "login" in url or "autenticacao" in url or "auth" in url:
            print("  Login form detected, filling credentials...")
            # Try common SSO login field patterns
            user_field = page.locator(
                "input[name='username'], input[name='login'], input[name='usuario'], "
                "input[id='username'], input[id='login'], input[type='text']:visible"
            ).first
            await user_field.fill(SIGA_USERNAME)

            pass_field = page.locator("input[type='password']:visible").first
            await pass_field.fill(SIGA_PASSWORD)

            submit = page.locator(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Entrar'), button:has-text('Login')"
            ).first
            await submit.click()
            await page.wait_for_load_state("networkidle", timeout=20000)
            await save(page, "01_portal_post_login", out_dir)
        else:
            # Maybe SSO cookie is still valid
            print(f"  URL: {page.url} — might already be logged in")
            await save(page, "01_portal_post_login", out_dir)

        # --- Step 2: Select role "Coordenação / Secretaria - Graduação" ---
        print("\n[2/8] Selecting role...")
        # The portal shows cards for each system. Look for the right one.
        role_card = page.locator(f"text={SIGA_ROLE_TEXT}").first
        try:
            await role_card.wait_for(state="visible", timeout=15000)
            await role_card.click()
        except Exception:
            # Maybe it's inside a specific section, try broader search
            print("  Direct text match failed, trying card/link...")
            all_cards = page.locator("a, button, [role='button'], .card")
            count = await all_cards.count()
            for i in range(count):
                txt = (await all_cards.nth(i).text_content() or "").strip()
                if "Coordena" in txt and "Gradua" in txt:
                    print(f"  Found card: {txt[:60]}")
                    await all_cards.nth(i).click()
                    break
            else:
                print("  Could not find role card. Dumping available options...")
                await dump_links(page, "portal")
                return 3

        await page.wait_for_load_state("networkidle", timeout=20000)
        await asyncio.sleep(2)
        await save(page, "02_siga_home", out_dir)
        print(f"  Now at: {page.url}")

        # --- Step 3: Navigate to Discentes → Consultar ---
        print("\n[3/8] Discentes → Consultar...")
        await save(page, "02b_menu_debug", out_dir)

        # From screenshots: left sidebar has "Discentes" as expandable menu
        discentes = page.locator("a:has-text('Discentes'), span:has-text('Discentes')").first
        try:
            await discentes.click(timeout=10000)
        except Exception:
            print("  'Discentes' text not found, dumping sidebar...")
            await dump_links(page, "sidebar")
            return 3
        await asyncio.sleep(1)

        consultar = page.locator(
            "a:has-text('Consultar'), a:has-text('Consulta')"
        ).first
        await consultar.click(timeout=10000)
        await page.wait_for_load_state("networkidle", timeout=20000)
        await save(page, "03_lista_discentes", out_dir)

        # --- Step 4: Search for student ---
        print("\n[4/8] Searching student...")
        search_term = grr or nome or ""
        if search_term:
            # Label "Pesquisar" with input placeholder="Matrícula, Nome ou Documento"
            search_field = page.locator(
                "input[placeholder*='Nome ou Documento'], "
                "input[placeholder*='Documento']"
            ).first
            await search_field.fill(search_term)
            await asyncio.sleep(2)
            await save(page, "04_search_results", out_dir)

        # --- Step 5: Click first student row ---
        print("\n[5/8] Selecting student...")
        first_row_link = page.locator("table tbody tr a").first
        student_name = await first_row_link.text_content()
        print(f"  Selecting: {(student_name or '').strip()[:60]}")
        await first_row_link.click()
        await page.wait_for_load_state("networkidle", timeout=20000)
        await save(page, "05_student_detail", out_dir)

        # Dump all tab names for reference
        tabs = page.locator("a[role='tab'], .nav-tabs a, .nav-link, ul.nav a")
        tab_count = await tabs.count()
        if tab_count > 0:
            tab_texts = await tabs.all_text_contents()
            print(f"  Tabs found ({tab_count}): {tab_texts}")
        else:
            # Try broader: any link in the tab area
            all_links = page.locator("a")
            link_count = await all_links.count()
            tab_candidates = []
            for i in range(link_count):
                txt = (await all_links.nth(i).text_content() or "").strip()
                if txt in (
                    "Informações Gerais", "Dados Complementares", "Currículos",
                    "Histórico", "Integralização", "Grade Horária",
                    "Atividades Formativas", "Componentes Flexíveis",
                    "Trancamento", "Exames", "Equivalências", "Log Histórico",
                    "Estágio", "Evasão", "Desempenho", "Observações",
                    "Documentos", "Documentos Pessoais", "Comprovante de vacinação",
                ):
                    tab_candidates.append(txt)
            print(f"  Tab candidates: {tab_candidates}")

        # --- Step 6: Histórico tab ---
        print("\n[6/8] Tab: Histórico...")
        hist_tab = page.locator("a:has-text('Histórico')").first
        await hist_tab.click()
        await wait_for_content(page, timeout=45000)
        await save(page, "06_historico", out_dir)

        # Extract table structure
        hist_tables = page.locator("table")
        table_count = await hist_tables.count()
        print(f"  Found {table_count} table(s)")
        for i in range(min(table_count, 5)):
            headers = await hist_tables.nth(i).locator("th").all_text_contents()
            row_count = await hist_tables.nth(i).locator("tbody tr").count()
            print(f"  Table {i}: {row_count} rows, headers={headers[:12]}")

        # Try to find reprovação indicators
        reprov = page.locator("text=Reprovad, td:has-text('Reprovad')")
        reprov_count = await reprov.count()
        print(f"  'Reprovad*' matches on page: {reprov_count}")

        # --- Step 7: Integralização tab ---
        print("\n[7/8] Tab: Integralização...")
        integ_tab = page.locator("a:has-text('Integralização')").first
        await integ_tab.click()
        await wait_for_content(page, timeout=45000)
        await save(page, "07_integralizacao", out_dir)

        integ_tables = page.locator("table")
        integ_count = await integ_tables.count()
        print(f"  Found {integ_count} table(s)")
        for i in range(min(integ_count, 5)):
            headers = await integ_tables.nth(i).locator("th").all_text_contents()
            row_count = await integ_tables.nth(i).locator("tbody tr").count()
            print(f"  Table {i}: {row_count} rows, headers={headers[:12]}")

        # Look for OD501 and ODDA6 specifically
        for code in ("OD501", "ODDA6"):
            matches = page.locator(f"td:has-text('{code}')")
            c = await matches.count()
            if c > 0:
                row_text = await matches.first.locator("..").text_content()
                print(f"  {code}: found! Row text = {(row_text or '').strip()[:100]}")
            else:
                print(f"  {code}: not found on page")

        # --- Step 8: Estágio tab ---
        print("\n[8/8] Tab: Estágio...")
        estagio_tab = page.locator("a:has-text('Estágio')").first
        if await estagio_tab.count() > 0:
            await estagio_tab.click()
            await wait_for_content(page, timeout=45000)
            await save(page, "08_estagio", out_dir)

            est_tables = page.locator("table")
            est_count = await est_tables.count()
            print(f"  Found {est_count} table(s)")
            for i in range(min(est_count, 5)):
                headers = await est_tables.nth(i).locator("th").all_text_contents()
                row_count = await est_tables.nth(i).locator("tbody tr").count()
                print(f"  Table {i}: {row_count} rows, headers={headers[:12]}")

        print(f"\n✓ Capture complete → {out_dir}")
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        # Save final state for debugging
        try:
            await save(page, "99_error_state", out_dir)
        except Exception:
            pass
        return 1

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIGA read-only DOM capture")
    parser.add_argument("--grr", help="GRR to search (e.g. GRR20191234)")
    parser.add_argument("--nome", help="Student name to search")
    args = parser.parse_args()

    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main(grr=args.grr, nome=args.nome)))
