"""Peek the most recent Gmail Drafts item (readonly).

Used to inspect what agir_estagios wrote when blocking a request.
"""
from __future__ import annotations

import email as email_mod
import imaplib
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ufpr_automation.config import settings  # noqa: E402
from ufpr_automation.gmail.client import _decode_header, _extract_text  # noqa: E402


def main() -> int:
    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    conn.login(settings.GMAIL_EMAIL, settings.GMAIL_APP_PASSWORD)
    try:
        conn.select('"[Gmail]/Drafts"', readonly=True)
        _, data = conn.search(None, "ALL")
        msns = data[0].split() if data and data[0] else []
        if not msns:
            print("No drafts.")
            return 0
        last = msns[-1]
        _, fetched = conn.fetch(last, "(RFC822)")
        raw = fetched[0][1] if isinstance(fetched[0], tuple) else fetched[0]
        msg = email_mod.message_from_bytes(raw)
        print(f"--- Latest draft msn={last.decode()} ---")
        print(f"Subject: {_decode_header(msg.get('Subject', ''))}")
        print(f"To:      {_decode_header(msg.get('To', ''))}")
        print(f"Cc:      {_decode_header(msg.get('Cc', ''))}")
        print(f"Date:    {msg.get('Date', '')}")
        print(f"--- body ---")
        print(_extract_text(msg))
        return 0
    finally:
        conn.logout()


if __name__ == "__main__":
    sys.exit(main())
