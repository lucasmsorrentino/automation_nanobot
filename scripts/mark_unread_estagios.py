"""One-shot: marca como não-lidos os 3 emails de Estágios do smoke run
ca2ba9e251f2 para permitir rerun após fix dos intents PROCEDURES.md.

Busca por Message-ID seria ideal, mas só temos subject do log. Usa IMAP
SEARCH com SUBJECT match (case-insensitive, prefix match) e remove flag
\\Seen somente se o match for único no inbox.
"""

from __future__ import annotations

import imaplib
import sys

from ufpr_automation.config import settings

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

TARGETS = [
    "Cadastro na Central",
    "Termo Aditivo",
    "Re: Assinatura de",
]


def main() -> int:
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(settings.GMAIL_EMAIL, settings.GMAIL_APP_PASSWORD)
    conn.select("INBOX")

    errors = 0
    for subj in TARGETS:
        typ, data = conn.search("UTF-8", "SUBJECT", f'"{subj}"')
        if typ != "OK":
            print(f"[ERR] SEARCH falhou para: {subj}")
            errors += 1
            continue

        ids = data[0].split()
        if not ids:
            print(f"[WARN] Não encontrado: {subj}")
            errors += 1
            continue

        latest = ids[-1]  # pega o mais recente se houver duplicatas
        conn.store(latest, "-FLAGS", "\\Seen")
        print(f"[OK] Marcado UNSEEN (id={latest.decode()}): {subj}")

    conn.logout()
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
