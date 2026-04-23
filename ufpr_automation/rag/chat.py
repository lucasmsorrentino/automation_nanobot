"""Interactive CLI for querying the UFPR RAG vector store.

Usage:
    python -m ufpr_automation.rag.chat
    python -m ufpr_automation.rag.chat --conselho cepe
    python -m ufpr_automation.rag.chat --top-k 3
"""

from __future__ import annotations

import argparse
import sys

# Force UTF-8 stdout on Windows so documents containing characters outside
# cp1252 (e.g. ligatures like "fi" = \ufb01) don't crash the REPL mid-query.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # older Python without reconfigure()

from ufpr_automation.rag.retriever import Retriever

# ANSI colors for terminal output
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

CONSELHOS = ("cepe", "coun", "coplad", "concur", "estagio")
TIPOS = ("atas", "resolucoes", "instrucoes-normativas", "estagio")

HELP_TEXT = f"""
{BOLD}Comandos especiais:{RESET}
  {CYAN}/conselho <nome>{RESET}  — Filtrar por conselho ({", ".join(CONSELHOS)}) ou 'todos'
  {CYAN}/tipo <nome>{RESET}      — Filtrar por tipo ({", ".join(TIPOS)}) ou 'todos'
  {CYAN}/top <n>{RESET}          — Alterar quantidade de resultados (padrão: 5)
  {CYAN}/filtros{RESET}          — Mostrar filtros ativos
  {CYAN}/ajuda{RESET}            — Mostrar esta mensagem
  {CYAN}/sair{RESET}             — Sair (ou Ctrl+C)
"""


def print_results(results: list, query: str) -> None:
    """Pretty-print search results to the terminal."""
    if not results:
        print(f"\n  {DIM}Nenhum resultado encontrado.{RESET}\n")
        return

    print(f"\n  {BOLD}{len(results)} resultado(s) para:{RESET} {CYAN}{query}{RESET}\n")

    for i, r in enumerate(results, 1):
        score_color = GREEN if r.score < 0.3 else YELLOW
        print(f"  {BOLD}[{i}]{RESET} {score_color}{r.score:.4f}{RESET}  {DIM}{r.caminho}{RESET}")
        # Show text preview (first 300 chars, indented)
        preview = r.text.strip().replace("\n", "\n      ")
        if len(preview) > 300:
            preview = preview[:300] + "..."
        print(f"      {preview}")
        print()


def run_chat(
    conselho: str | None = None,
    tipo: str | None = None,
    top_k: int = 5,
) -> None:
    """Main interactive loop."""
    print(f"\n{BOLD}=== UFPR RAG — Consulta Interativa ==={RESET}")
    print(f"{DIM}Carregando modelo de embeddings...{RESET}")

    retriever = Retriever()
    # Force model load on startup so the user doesn't wait on first query
    retriever._ensure_loaded()

    print(f"{GREEN}Pronto!{RESET} Base vetorial carregada.")
    print(f"Digite sua consulta em linguagem natural. {DIM}/ajuda para comandos.{RESET}\n")

    # Active filters
    active_conselho = conselho
    active_tipo = tipo
    active_top_k = top_k

    while True:
        try:
            # Show active filters in prompt
            filter_hint = ""
            if active_conselho or active_tipo:
                parts = []
                if active_conselho:
                    parts.append(active_conselho)
                if active_tipo:
                    parts.append(active_tipo)
                filter_hint = f" {DIM}[{'/'.join(parts)}]{RESET}"

            query = input(f"{BOLD}>{RESET}{filter_hint} ").strip()

        except (KeyboardInterrupt, EOFError):
            print(f"\n{DIM}Saindo...{RESET}")
            break

        if not query:
            continue

        # Handle commands
        if query.startswith("/"):
            cmd = query.lower().split()
            command = cmd[0]

            if command in ("/sair", "/quit", "/exit", "/q"):
                print(f"{DIM}Saindo...{RESET}")
                break

            elif command in ("/ajuda", "/help", "/h"):
                print(HELP_TEXT)

            elif command == "/conselho":
                if len(cmd) < 2:
                    print(f"  {DIM}Uso: /conselho <nome> ou /conselho todos{RESET}")
                elif cmd[1] == "todos":
                    active_conselho = None
                    print(f"  {GREEN}Filtro de conselho removido.{RESET}")
                elif cmd[1] in CONSELHOS:
                    active_conselho = cmd[1]
                    print(f"  {GREEN}Filtrando por conselho: {active_conselho}{RESET}")
                else:
                    print(f"  {YELLOW}Conselho inválido. Opções: {', '.join(CONSELHOS)}{RESET}")

            elif command == "/tipo":
                if len(cmd) < 2:
                    print(f"  {DIM}Uso: /tipo <nome> ou /tipo todos{RESET}")
                elif cmd[1] == "todos":
                    active_tipo = None
                    print(f"  {GREEN}Filtro de tipo removido.{RESET}")
                elif cmd[1] in TIPOS:
                    active_tipo = cmd[1]
                    print(f"  {GREEN}Filtrando por tipo: {active_tipo}{RESET}")
                else:
                    print(f"  {YELLOW}Tipo inválido. Opções: {', '.join(TIPOS)}{RESET}")

            elif command == "/top":
                if len(cmd) < 2 or not cmd[1].isdigit():
                    print(f"  {DIM}Uso: /top <número>{RESET}")
                else:
                    active_top_k = int(cmd[1])
                    print(f"  {GREEN}Mostrando top {active_top_k} resultados.{RESET}")

            elif command == "/filtros":
                print(f"  Conselho: {active_conselho or 'todos'}")
                print(f"  Tipo: {active_tipo or 'todos'}")
                print(f"  Top-K: {active_top_k}")

            else:
                print(f"  {YELLOW}Comando desconhecido. /ajuda para ver opções.{RESET}")

            continue

        # Execute search
        results = retriever.search(
            query,
            conselho=active_conselho,
            tipo=active_tipo,
            top_k=active_top_k,
        )
        print_results(results, query)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive RAG query CLI")
    parser.add_argument(
        "--conselho", type=str, default=None, help=f"Pre-filter by council ({', '.join(CONSELHOS)})"
    )
    parser.add_argument(
        "--tipo", type=str, default=None, help=f"Pre-filter by doc type ({', '.join(TIPOS)})"
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of results per query (default: 5)"
    )
    args = parser.parse_args()

    run_chat(conselho=args.conselho, tipo=args.tipo, top_k=args.top_k)


if __name__ == "__main__":
    main()
