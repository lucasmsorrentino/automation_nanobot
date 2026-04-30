"""One-off: marca um email como nao-processado para o pipeline pegar de novo.

Remove a flag ``\\Seen`` E o label ``ufpr/processado`` do email com o
``Message-ID`` informado, fazendo com que ``GmailClient.list_unread``
selecione ele no proximo run.

Uso:
    python scripts/reprocess_one.py --message-id <ID>
"""
from __future__ import annotations

import argparse
import imaplib
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ufpr_automation.config import settings  # noqa: E402
from ufpr_automation.gmail.client import PROCESSED_LABEL  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--message-id", required=True)
    args = p.parse_args()

    msgid = args.message_id.strip().strip("<>")
    escaped = msgid.replace("\\", "\\\\").replace('"', '\\"')

    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=60)
    conn.login(settings.GMAIL_EMAIL, settings.GMAIL_APP_PASSWORD)
    try:
        conn.select("INBOX", readonly=False)
        _, data = conn.uid("SEARCH", None, "X-GM-RAW", f'"rfc822msgid:{escaped}"')
        uids = data[0].split() if data and data[0] else []
        if not uids:
            print(f"NOT FOUND in INBOX: {msgid}")
            return 1
        print(f"UIDs: {[u.decode() for u in uids]}")
        for u in uids:
            r1 = conn.uid("STORE", u, "-X-GM-LABELS", f"({PROCESSED_LABEL})")
            print(f"  uid={u.decode()} STORE -X-GM-LABELS {PROCESSED_LABEL!r} -> {r1[0]}")
            r2 = conn.uid("STORE", u, "-FLAGS", "(\\Seen)")
            print(f"  uid={u.decode()} STORE -FLAGS \\Seen -> {r2[0]}")
        return 0
    finally:
        conn.logout()


if __name__ == "__main__":
    sys.exit(main())
