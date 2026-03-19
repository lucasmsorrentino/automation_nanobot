"""CLI commands for the UFPR Automation system.

Usage:
    # First run (headed — manual login required):
    python -m ufpr_automation

    # Subsequent runs (auto-detects saved session):
    python -m ufpr_automation

    # Dry run (test browser launch only, no login):
    python -m ufpr_automation --dry-run

    # Force headed mode (even with saved session):
    python -m ufpr_automation --headed

    # Debug mode (capture DOM + screenshot):
    python -m ufpr_automation --debug
"""

from __future__ import annotations

import argparse
import asyncio

from ufpr_automation.config.settings import OWA_INBOX_URL, OWA_URL
from ufpr_automation.outlook.browser import (
    create_browser_context,
    has_saved_session,
    is_logged_in,
    launch_browser,
    save_session_state,
    wait_for_login,
)
from ufpr_automation.outlook.scraper import scrape_inbox
from ufpr_automation.utils.debug import capture_debug_info


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="UFPR Bureaucratic Automation — Marco I (OWA Scraper)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Just launch the browser and navigate to OWA without logging in.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Force headed mode (visible browser window) even with saved session.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Capture DOM + screenshot for debugging selector issues.",
    )
    return parser.parse_args()


async def run_dry_run() -> None:
    """Launch browser, navigate to OWA, and exit — for testing Playwright setup."""
    print("\n🧪 DRY RUN — Testando configuração do Playwright")
    print("=" * 60)

    pw, browser = await launch_browser(headless=False)

    try:
        context = await create_browser_context(browser, headless=False)
        page = await context.new_page()

        print(f"📎 Navegando para: {OWA_URL}")
        await page.goto(OWA_URL, wait_until="domcontentloaded")

        title = await page.title()
        print(f"📄 Título da página: {title}")
        print(f"🔗 URL atual: {page.url}")
        print("\n✅ Playwright está funcionando corretamente!")
        print("   Feche o navegador ou pressione Ctrl+C para sair.")

        await page.wait_for_timeout(5000)

    finally:
        await browser.close()
        await pw.stop()

    print("👋 Dry run concluído.")


async def run_main(headed: bool = False, debug: bool = False) -> None:
    """Main execution flow for the OWA scraper.

    1. Check for saved session
    2. If no session → headed mode for manual login
    3. If session exists → headless mode for scraping
    4. Extract email subjects from inbox
    """
    print("\n" + "=" * 60)
    print("🤖 UFPR Automation — Marco I — OWA Scraper")
    print("=" * 60)

    session_exists = has_saved_session()
    use_headless = session_exists and not headed

    if session_exists:
        print("🔑 Sessão salva detectada.")
        if headed:
            print("   (--headed flag: usando modo com janela visível)")
    else:
        print("🆕 Primeira execução — login manual necessário.")
        use_headless = False

    print(
        f"🖥️  Modo: {'Headless (background)' if use_headless else 'Com janela visível'}"
    )
    print()

    pw, browser = await launch_browser(headless=use_headless)

    try:
        context = await create_browser_context(browser, headless=use_headless)
        page = await context.new_page()

        print(f"📎 Navegando para: {OWA_INBOX_URL}")
        await page.goto(OWA_INBOX_URL, wait_until="domcontentloaded")

        logged_in = await is_logged_in(page)

        if not logged_in:
            if use_headless:
                print(
                    "⚠️ Sessão expirada! Reinicie sem --headless para fazer login novamente."
                )
                print("   Dica: delete session_data/state.json e execute novamente.")
                return

            login_success = await wait_for_login(page)
            if not login_success:
                print("❌ Login não completado dentro do tempo limite.")
                return

            await save_session_state(context)
            print("✅ Sessão salva! Próximas execuções podem rodar em headless.")
        else:
            print("✅ Já logado via sessão salva!")

        # Scrape the inbox
        emails = await scrape_inbox(page)

        # Debug mode: capture DOM and screenshot
        if debug:
            await capture_debug_info(page)

        # Summary
        print(f"\n📊 Resumo:")
        print(f"   Total de e-mails visíveis: {len(emails)}")
        unread = [e for e in emails if e.is_unread]
        print(f"   E-mails não lidos: {len(unread)}")

        if unread:
            print("\n" + "=" * 60)
            print("🧠 Iniciando análise do Gemini (Marco I - Pensar)")
            print("=" * 60)
            
            from ufpr_automation.llm import GeminiClient
            try:
                llm = GeminiClient()
                
                print("\n📩 E-mails NÃO LIDOS analisados:")
                for i, email in enumerate(unread, 1):
                    print(f"   {i}. De: {email.sender}")
                    print(f"      Assunto: {email.subject}")
                    
                    print(f"      ⏳ Classificando no Gemini...")
                    classification = llm.classify_email(email)
                    email.classification = classification
                    
                    print(f"      [ {classification.categoria} ]")
                    print(f"      Resumo: {classification.resumo}")
                    print(f"      Ação sugerida: {classification.acao_necessaria}")
                    if classification.sugestao_resposta:
                        print(f"      Resposta Gerada:")
                        print(f"      {'-' * 40}")
                        draft_lines = classification.sugestao_resposta.split('\n')
                        for line in draft_lines:
                            print(f"      | {line}")
                        print(f"      {'-' * 40}")
                    print()
                    
            except Exception as e:
                print(f"❌ Erro ao inicializar Gemini: {e}")

        # Human-in-the-loop notification
        print("\n🔔 NOTIFICAÇÃO: Varredura concluída.")
        print("   Nenhuma ação automática foi tomada.")

    finally:
        await browser.close()
        await pw.stop()

    print("\n👋 Execução finalizada.")


def main() -> None:
    """CLI entry point."""
    args = parse_args()

    if args.dry_run:
        asyncio.run(run_dry_run())
    else:
        asyncio.run(run_main(headed=args.headed, debug=args.debug))
