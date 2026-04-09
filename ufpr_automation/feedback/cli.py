"""CLI for reviewing and recording human feedback on email classifications.

Usage:
    python -m ufpr_automation.feedback stats      # show feedback statistics
    python -m ufpr_automation.feedback export      # export as JSON for DSPy
    python -m ufpr_automation.feedback review      # interactive review of recent drafts
    python -m ufpr_automation.feedback add         # manually add a correction
"""

from __future__ import annotations

import argparse
import json
import sys

from ufpr_automation.core.models import EmailClassification
from ufpr_automation.feedback.store import FeedbackStore

# Valid categories (kept in sync with core/models.py Categoria literal)
_VALID_CATEGORIES = [
    "Estágios",
    "Acadêmico / Matrícula",
    "Acadêmico / Equivalência de Disciplinas",
    "Acadêmico / Aproveitamento de Disciplinas",
    "Acadêmico / Ajuste de Disciplinas",
    "Diplomação / Diploma",
    "Diplomação / Colação de Grau",
    "Extensão",
    "Formativas",
    "Requerimentos",
    "Urgente",
    "Correio Lixo",
    "Outros",
]


def cmd_stats(store: FeedbackStore) -> None:
    """Print feedback statistics."""
    records = store.list_all()
    if not records:
        print("Nenhum registro de feedback encontrado.")
        print(f"Arquivo: {store.path}")
        return

    print(f"Total de correções: {len(records)}")
    print(f"Arquivo: {store.path}")
    print()

    # Category distribution
    cat_changes: dict[str, int] = {}
    for r in records:
        key = f"{r.original.categoria} → {r.corrected.categoria}"
        cat_changes[key] = cat_changes.get(key, 0) + 1

    print("Mudanças de categoria:")
    for change, count in sorted(cat_changes.items(), key=lambda x: -x[1]):
        print(f"  {change}: {count}")

    # Time range
    timestamps = [r.timestamp for r in records]
    print(f"\nPeríodo: {min(timestamps)[:10]} a {max(timestamps)[:10]}")


def cmd_export(store: FeedbackStore) -> None:
    """Export feedback records as JSON (for DSPy training data)."""
    records = store.list_all()
    if not records:
        print("Nenhum registro de feedback para exportar.", file=sys.stderr)
        sys.exit(1)

    data = [r.model_dump() for r in records]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _load_last_run_entries(store: FeedbackStore) -> list[dict]:
    """Load classification entries from the last pipeline run.

    Returns:
        List of entry dicts from last_run.jsonl.
    """
    results_file = store.path.parent / "last_run.jsonl"

    if not results_file.exists():
        return []

    entries = []
    with open(results_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _print_entry(i: int, total: int, entry: dict) -> None:
    """Print a single classification entry for review."""
    cls_data = entry.get("classification", {})
    print(f"--- [{i}/{total}] ---")
    print(f"De: {entry.get('sender', '?')}")
    print(f"Assunto: {entry.get('subject', '?')}")
    print(f"Categoria: {cls_data.get('categoria', '?')}")
    print(f"Confianca: {cls_data.get('confianca', '?')}")
    print(f"Resumo: {cls_data.get('resumo', '?')}")
    print(f"Acao: {cls_data.get('acao_necessaria', '?')}")
    resposta = cls_data.get("sugestao_resposta", "")
    if resposta:
        print(f"Resposta: {resposta[:200]}{'...' if len(resposta) > 200 else ''}")
    print()


def _record_correction(
    store: FeedbackStore,
    entry: dict,
    cls_data: dict,
    corrected_data: dict,
    notes: str = "",
) -> None:
    """Save a correction to the FeedbackStore and generate Reflexion if needed."""
    original = EmailClassification(**cls_data)
    corrected = EmailClassification(**corrected_data)
    email_hash = entry.get("email_hash", "unknown")
    sender = entry.get("sender", "?")
    subject = entry.get("subject", "?")

    store.add(
        email_hash=email_hash,
        original=original,
        corrected=corrected,
        email_sender=sender,
        email_subject=subject,
        notes=notes,
    )

    # Generate Reflexion if categories differ
    if original.categoria != corrected.categoria:
        try:
            from ufpr_automation.feedback.reflexion import ReflexionMemory

            memory = ReflexionMemory()
            memory.add_reflection(
                email_subject=subject,
                email_body=entry.get("body", entry.get("preview", "")),
                original=original,
                corrected=corrected,
            )
            print("  + Reflexion gerada e armazenada")
        except Exception as e:
            print(f"  ! Reflexion falhou: {e}")


def cmd_review(store: FeedbackStore, approve_all: bool = False) -> None:
    """Interactive review of recent email classifications.

    Reads the latest pipeline results from the log file and lets the
    reviewer accept or correct each classification.

    Args:
        approve_all: If True, auto-accept all classifications without prompting.
            Records each as feedback (original == corrected) so DSPy sees
            confirmed-correct examples. Useful for CI or batch workflows.
    """
    entries = _load_last_run_entries(store)

    if not entries:
        print("Nenhum resultado de pipeline encontrado para revisao.")
        print("Execute o pipeline primeiro: python -m ufpr_automation --channel gmail")
        print(
            "\nOu use 'python -m ufpr_automation.feedback add' "
            "para adicionar correcoes manualmente."
        )
        return

    print(f"=== Revisao de {len(entries)} classificacao(oes) ===\n")
    reviewed = 0

    for i, entry in enumerate(entries, 1):
        email_hash = entry.get("email_hash", "unknown")
        sender = entry.get("sender", "?")
        subject = entry.get("subject", "?")
        cls_data = entry.get("classification", {})

        _print_entry(i, len(entries), entry)

        if approve_all:
            # Auto-accept: record as confirmed-correct feedback
            original = EmailClassification(**cls_data)
            store.add(
                email_hash=email_hash,
                original=original,
                corrected=original,
                email_sender=sender,
                email_subject=subject,
                notes="auto-approved via --approve-all",
            )
            print("  + Aceito automaticamente (--approve-all)\n")
            reviewed += 1
            continue

        while True:
            choice = input("[a]ceitar / [c]orrigir / [p]ular / [q]uit? ").strip().lower()
            if choice in ("a", "c", "p", "q"):
                break
            print("Opcao invalida. Use: a, c, p, q")

        if choice == "q":
            break
        if choice == "p":
            continue
        if choice == "a":
            # Record acceptance as confirmed-correct feedback
            original = EmailClassification(**cls_data)
            store.add(
                email_hash=email_hash,
                original=original,
                corrected=original,
                email_sender=sender,
                email_subject=subject,
                notes="accepted by reviewer",
            )
            print("  + Aceito (confirmado como correto)\n")
            reviewed += 1
            continue

        # Correction flow
        corrected_data = dict(cls_data)

        print(f"\nCategorias validas: {', '.join(_VALID_CATEGORIES)}")
        new_cat = input(f"  Nova categoria [{cls_data.get('categoria')}]: ").strip()
        if new_cat and new_cat in _VALID_CATEGORIES:
            corrected_data["categoria"] = new_cat

        new_resumo = input(
            f"  Novo resumo [{cls_data.get('resumo', '')[:60]}]: "
        ).strip()
        if new_resumo:
            corrected_data["resumo"] = new_resumo

        new_acao = input(
            f"  Nova acao [{cls_data.get('acao_necessaria', '')}]: "
        ).strip()
        if new_acao:
            corrected_data["acao_necessaria"] = new_acao

        new_resposta = input("  Nova resposta (Enter para manter): ").strip()
        if new_resposta:
            corrected_data["sugestao_resposta"] = new_resposta

        notes = input("  Notas (opcional): ").strip()

        _record_correction(store, entry, cls_data, corrected_data, notes)

        orig_cat = cls_data.get("categoria", "?")
        corr_cat = corrected_data.get("categoria", orig_cat)
        print(f"  + Correcao salva ({orig_cat} -> {corr_cat})\n")
        reviewed += 1

    print(f"\nRevisao concluida. {reviewed} registro(s) processado(s).")
    print(f"Total acumulado: {store.count()} registros")


def cmd_add(store: FeedbackStore) -> None:
    """Manually add a feedback correction via prompts."""
    print("=== Adicionar correção manual ===\n")

    email_hash = input("Email hash (stable_id): ").strip() or "manual"
    sender = input("Remetente: ").strip()
    subject = input("Assunto: ").strip()

    print(f"\nCategorias: {', '.join(_VALID_CATEGORIES)}")
    orig_cat = input("Categoria original (errada): ").strip()
    corr_cat = input("Categoria correta: ").strip()

    if orig_cat not in _VALID_CATEGORIES or corr_cat not in _VALID_CATEGORIES:
        print("Categoria inválida.", file=sys.stderr)
        sys.exit(1)

    orig_resumo = input("Resumo original: ").strip()
    corr_resumo = input("Resumo correto: ").strip()
    notes = input("Notas (opcional): ").strip()

    original = EmailClassification(
        categoria=orig_cat,
        resumo=orig_resumo,
        acao_necessaria="",
        sugestao_resposta="",
    )
    corrected = EmailClassification(
        categoria=corr_cat,
        resumo=corr_resumo or orig_resumo,
        acao_necessaria="",
        sugestao_resposta="",
    )

    store.add(
        email_hash=email_hash,
        original=original,
        corrected=corrected,
        email_sender=sender,
        email_subject=subject,
        notes=notes,
    )
    print(f"\n✓ Correção salva. Total: {store.count()} registros.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Feedback CLI — UFPR Automation")
    parser.add_argument(
        "command",
        choices=["stats", "export", "review", "add"],
        help="Command: stats | export | review | add",
    )
    parser.add_argument(
        "--approve-all",
        action="store_true",
        default=False,
        help="(review only) Auto-accept all classifications without prompting.",
    )
    args = parser.parse_args()

    store = FeedbackStore()

    if args.command == "stats":
        cmd_stats(store)
    elif args.command == "export":
        cmd_export(store)
    elif args.command == "review":
        cmd_review(store, approve_all=args.approve_all)
    elif args.command == "add":
        cmd_add(store)


if __name__ == "__main__":
    main()
