"""CLI commands for the UFPR Automation system.

Usage:
    # First run (headed — manual login required):
    python -m ufpr_automation

    # Subsequent runs (headless, full pipeline):
    python -m ufpr_automation

    # Dry run (test Playwright setup, no login):
    python -m ufpr_automation --dry-run

    # Force headed mode (even with saved session):
    python -m ufpr_automation --headed

    # Debug mode (capture DOM + screenshot):
    python -m ufpr_automation --debug

    # Perceber-only (scrape + bodies, skip LLM + drafts):
    python -m ufpr_automation --perceber-only
"""

from __future__ import annotations

import argparse
import asyncio

from ufpr_automation.config import settings
from ufpr_automation.config.settings import OWA_INBOX_URL, OWA_URL
from ufpr_automation.orchestrator import print_summary, run_pipeline, run_pipeline_gmail
from ufpr_automation.outlook.browser import (
    auto_login,
    create_browser_context,
    has_credentials,
    has_saved_session,
    is_logged_in,
    launch_browser,
    save_session_state,
)
from ufpr_automation.utils.debug import capture_debug_info


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UFPR Bureaucratic Automation — Marco I (Multi-Agent Pipeline)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Launch browser and navigate to OWA without logging in.",
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
    parser.add_argument(
        "--perceber-only",
        action="store_true",
        help="Only run PerceberAgent (scrape + body extraction), skip LLM and drafts.",
    )
    parser.add_argument(
        "--channel",
        choices=["gmail", "owa"],
        default=None,
        help="Email channel to use. Overrides EMAIL_CHANNEL from .env. "
             "gmail = IMAP API (no MFA), owa = Playwright scraping.",
    )
    parser.add_argument(
        "--langgraph",
        action="store_true",
        help="Use LangGraph pipeline (Marco II) instead of sequential orchestrator.",
    )
    return parser.parse_args()


async def run_dry_run() -> None:
    """Launch browser, navigate to OWA, and exit."""
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
        await page.wait_for_timeout(5000)
    finally:
        await browser.close()
        await pw.stop()
    print("👋 Dry run concluído.")


async def run_main(headed: bool = False, debug: bool = False, perceber_only: bool = False) -> None:
    """Main execution flow — login, then run the multi-agent pipeline."""
    print("\n" + "=" * 60)
    print("🤖 UFPR Automation — Marco I — Pipeline Multi-Agente")
    print("    Perceber → Pensar (paralelo) → Agir")
    print("=" * 60)

    session_exists = has_saved_session()
    credentials_ok = has_credentials()

    # With credentials, we can always run headless (auto-login handles MFA via Telegram).
    # Without credentials, we need a visible window for manual login.
    use_headless = (session_exists or credentials_ok) and not headed

    if session_exists:
        print("🔑 Sessão salva detectada.")
        if headed:
            print("   (--headed: usando modo com janela visível)")
    elif credentials_ok:
        print("🤖 Credenciais configuradas — login automático disponível.")
    else:
        print("🆕 Primeira execução — login manual necessário.")
        use_headless = False

    print(f"🖥️  Modo: {'Headless (background)' if use_headless else 'Com janela visível'}\n")

    pw, browser = await launch_browser(headless=use_headless)

    try:
        context = await create_browser_context(browser, headless=use_headless)
        page = await context.new_page()

        print(f"📎 Navegando para: {OWA_INBOX_URL}")
        await page.goto(OWA_INBOX_URL, wait_until="domcontentloaded")

        logged_in = await is_logged_in(page)
        if not logged_in:
            if use_headless and session_exists:
                # Session expired — auto-retry with credentials instead of failing
                print("⚠️  Sessão expirada! Tentando login automático...")
            login_success = await auto_login(page)
            if not login_success:
                print("❌ Login não completado dentro do tempo limite.")
                return
            await save_session_state(context)
            print("✅ Sessão salva! Próximas execuções podem rodar em headless.")
        else:
            print("✅ Já logado via sessão salva!\n")

        if debug:
            await capture_debug_info(page)

        # ---------------------------------------------------------------- #
        # Run the multi-agent pipeline                                       #
        # ---------------------------------------------------------------- #
        if perceber_only:
            # Perceber-only mode: scrape + body extraction, no LLM calls
            from ufpr_automation.agents.perceber import PerceberAgent
            agent = PerceberAgent(page)
            emails = await agent.run()
            print(f"\n📊 Perceber-only: {len(emails)} e-mail(s) extraído(s) com corpo completo.")
        else:
            result = await run_pipeline(page)
            print_summary(result)

    finally:
        await browser.close()
        await pw.stop()

    print("\n👋 Execução finalizada.")


async def run_gmail_channel(use_langgraph: bool = False) -> None:
    """Run the pipeline using Gmail IMAP as the email source."""
    print("\n" + "=" * 60)
    if use_langgraph:
        print("🤖 UFPR Automation — Marco II — LangGraph Pipeline")
        print("    Perceber → RAG → Classificar → Rotear → Agir")
    else:
        print("🤖 UFPR Automation — Marco I — Canal Gmail (IMAP)")
        print("    Ler e-mails → Pensar (paralelo) → Salvar rascunho")
    print("=" * 60)

    if use_langgraph:
        from ufpr_automation.graph.builder import build_graph
        graph = build_graph(channel="gmail")
        result = graph.invoke({"channel": "gmail"})
        # Adapt LangGraph state to summary format
        emails = result.get("emails", [])
        classifications = result.get("classifications", {})
        drafts = result.get("drafts_saved", [])
        # Attach classifications to emails for print_summary
        for e in emails:
            if e.stable_id in classifications:
                e.classification = classifications[e.stable_id]
        summary = {
            "total_unread": len(emails),
            "classified": len(classifications),
            "drafts_saved": len(drafts),
            "emails": emails,
        }
        print_summary(summary)
    else:
        result = await run_pipeline_gmail()
        print_summary(result)

    print("\n👋 Execução finalizada.")


def main() -> None:
    """CLI entry point."""
    args = parse_args()

    # Determine channel: CLI flag overrides .env setting
    channel = args.channel or settings.EMAIL_CHANNEL

    if args.dry_run:
        asyncio.run(run_dry_run())
    elif channel == "gmail":
        asyncio.run(run_gmail_channel(use_langgraph=args.langgraph))
    else:
        asyncio.run(
            run_main(
                headed=args.headed,
                debug=args.debug,
                perceber_only=args.perceber_only,
            )
        )
