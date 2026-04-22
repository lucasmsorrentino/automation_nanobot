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
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=1, help="How many latest drafts to show")
    p.add_argument("--filter-to", default=None, help="Only show drafts whose To contains this")
    args = p.parse_args()

    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    conn.login(settings.GMAIL_EMAIL, settings.GMAIL_APP_PASSWORD)
    try:
        conn.select('"[Gmail]/Drafts"', readonly=True)
        _, data = conn.search(None, "ALL")
        msns = data[0].split() if data and data[0] else []
        if not msns:
            print("No drafts.")
            return 0
        # Walk from newest to oldest
        shown = 0
        for m in reversed(msns):
            _, fetched = conn.fetch(m, "(RFC822)")
            raw = fetched[0][1] if isinstance(fetched[0], tuple) else fetched[0]
            msg = email_mod.message_from_bytes(raw)
            to = _decode_header(msg.get("To", ""))
            if args.filter_to and args.filter_to not in to:
                continue
            print(f"--- Draft msn={m.decode()} ---")
            print(f"Subject: {_decode_header(msg.get('Subject', ''))}")
            print(f"To:      {to}")
            print(f"Cc:      {_decode_header(msg.get('Cc', ''))}")
            print(f"--- body ---")
            print(_extract_text(msg))
            print()
            shown += 1
            if shown >= args.n:
                break
        return 0
    finally:
        conn.logout()


if __name__ == "__main__":
    sys.exit(main())
