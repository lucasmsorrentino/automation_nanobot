"""One-off: mark a specific Gmail Message-ID back as unread.

Used to re-process an email that was already seen+marked by a previous
pipeline run so the next run picks it up again.
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--message-id", required=True)
    args = p.parse_args()

    stripped = args.message_id.strip().strip("<>")
    escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')

    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    conn.login(settings.GMAIL_EMAIL, settings.GMAIL_APP_PASSWORD)
    try:
        conn.select("INBOX", readonly=False)
        _, data = conn.search(None, "X-GM-RAW", f'"rfc822msgid:{escaped}"')
        msns = data[0].split() if data and data[0] else []
        if not msns:
            print(f"Not found in INBOX: {args.message_id}")
            return 1
        for m in msns:
            conn.store(m, "-FLAGS", "\\Seen")
            print(f"Marked unread: msn={m.decode()} msg_id={args.message_id}")
        return 0
    finally:
        conn.logout()


if __name__ == "__main__":
    sys.exit(main())
