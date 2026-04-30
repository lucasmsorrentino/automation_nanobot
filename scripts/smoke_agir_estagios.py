"""Smoke test direto do agir_estagios contra um email real.

Bypassa Tier 0 lookup natural, ``already_replied_by_us`` e a fila do
Gmail, mas usa toda a cadeia real:
  1. fetch real do email + extracao de texto dos anexos
  2. cascade SEI (find_processes_by_grr filtrado por tipo)
  3. consult SIGA (matricula, integralizacao, reprovações)
  4. ``agir_estagios`` -> checker registry + gerador de draft

NAO salva draft no Gmail nem mexe no SEI live (o ``--once`` real faria
isso). So imprime o draft que SERIA salvo + sumario dos checkers.

Uso:
    python scripts/smoke_agir_estagios.py --message-id <MSG-ID>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ufpr_automation.attachments import extract_text_from_attachment  # noqa: E402
from ufpr_automation.config import settings  # noqa: E402
from ufpr_automation.core.models import EmailClassification  # noqa: E402
from ufpr_automation.gmail.client import GmailClient  # noqa: E402
from ufpr_automation.graph.nodes import (  # noqa: E402
    _consult_sei_for_email,
    _consult_siga_for_email,
    agir_estagios,
)


def fetch_email_by_msgid(msgid: str):
    """Reusa GmailClient.list_unread, filtra pelo Message-ID alvo,
    e roda ``extract_text_from_attachment`` em cada anexo.

    Espelha o que ``perceber_gmail`` (graph/nodes.py:60) faz na pipeline
    real: sem essa chamada, ``att.extracted_text`` fica vazio e o body
    enriquecido perde o conteudo do TCE — agir_estagios reporta falsos
    hard_blocks pq os campos do TCE nao foram extraidos.

    Pre-requisito: o email deve estar UNREAD e sem o label
    ``ufpr/processado`` (rode ``scripts/reprocess_one.py --message-id ...``
    antes se necessario).
    """
    client = GmailClient()
    emails = client.list_unread(limit=50)
    target_norm = msgid.strip().strip("<>").lower()
    for e in emails:
        eid = (e.gmail_message_id or "").strip().strip("<>").lower()
        if eid == target_norm:
            for att in e.attachments:
                extract_text_from_attachment(att)
            return e
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--message-id", required=True)
    args = p.parse_args()

    email = fetch_email_by_msgid(args.message_id)
    if not email:
        print(f"NOT FOUND: {args.message_id}")
        print("Rode primeiro: python scripts/reprocess_one.py --message-id <ID>")
        return 1

    print(f"=== EMAIL ===")
    print(f"  from:    {email.sender}")
    print(f"  subject: {email.subject}")
    print(f"  body:    {(email.body or '')[:200]!r}")
    print(f"  attachments: {len(email.attachments)} file(s)")
    for a in email.attachments:
        text_len = len(a.extracted_text or "")
        print(f"    - {a.filename} ({a.size_bytes} bytes, extracted_text={text_len} chars)")

    # Bypass already_replied_by_us pra forcar agir_estagios
    email.already_replied_by_us = False

    # Enrich body com subject + attachment text pra playbook.lookup matchar.
    # agir_estagios usa email.body como search text; se a aluna so escreveu
    # "Segue o anexo!" o lookup nao acha nada.
    enriched_parts: list[str] = []
    if email.subject:
        enriched_parts.append(email.subject)
    if email.body:
        enriched_parts.append(email.body)
    for a in email.attachments:
        if a.extracted_text:
            enriched_parts.append(a.extracted_text)
    email.body = "\n\n".join(enriched_parts)

    # Build classification (Estagios)
    cls = EmailClassification(
        categoria="Estágios",
        resumo=f"[smoke] {email.subject}",
        acao_necessaria="Abrir Processo SEI",
        sugestao_resposta="",
    )

    print()
    print("=== SEI consult ===")
    sei_data = _consult_sei_for_email(email, cls)
    print(json.dumps(sei_data or {}, indent=2, ensure_ascii=False, default=str)[:1500])

    print()
    print("=== SIGA consult ===")
    siga_data = _consult_siga_for_email(email, cls)
    print(json.dumps(siga_data or {}, indent=2, ensure_ascii=False, default=str)[:1500])

    state = {
        "emails": [email],
        "classifications": {email.stable_id: cls},
        "tier0_hits": [email.stable_id],
        "sei_contexts": {email.stable_id: sei_data or {}},
        "siga_contexts": {email.stable_id: siga_data or {}},
    }

    print()
    print("=== agir_estagios ===")
    result = agir_estagios(state)
    ops = result.get("sei_operations") or []
    for op in ops:
        print(f"  op={op.get('op')} reason={op.get('reason')!r}")
        for b in op.get("blocks", []) or []:
            kind = "[hard]" if b.get("severity") == "hard_block" else "[soft]"
            internal = " (interno)" if b.get("internal_only") else ""
            print(f"    {kind}{internal} {b.get('id')}: {b.get('reason')}")

    print()
    print("=== DRAFT BODY (que seria salvo pelo agir_gmail) ===")
    print(cls.sugestao_resposta or "(nenhum draft gerado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
