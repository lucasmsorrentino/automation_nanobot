"""Gmail client for reading forwarded UFPR emails via IMAP.

Uses App Password authentication (no OAuth, no extra dependencies).
The Gmail account receives auto-forwarded emails from the UFPR Outlook
mailbox, so the system never needs to interact with OWA directly.

Usage:
    client = GmailClient()
    emails = client.list_unread()
    client.mark_read(emails[0].gmail_msg_id)
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from ufpr_automation.config import settings
from ufpr_automation.core.models import AttachmentData, EmailData
from ufpr_automation.utils.logging import logger

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

ALL_MAIL_FOLDER = '"[Gmail]/All Mail"'

_THRID_RE = re.compile(rb"X-GM-THRID (\d+)")


def _parse_address(raw: str) -> str:
    """Extract the bare lowercase email address from a 'Name <email>' string."""
    if not raw:
        return ""
    _name, addr = email.utils.parseaddr(raw)
    return addr.strip().lower()


def _decode_header(raw: str) -> str:
    """Decode RFC 2047 encoded email header into a plain string."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_text(msg: email.message.Message) -> str:
    """Extract the plain-text body from a MIME message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback: try text/html if no plain text found
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def _extract_attachments(msg: email.message.Message, email_stable_id: str) -> list[AttachmentData]:
    """Extract and save attachments from a MIME message.

    Saves files to ATTACHMENTS_DIR/{email_stable_id}_{filename}.
    Skips attachments larger than ATTACHMENT_MAX_SIZE_MB.
    """
    attachments: list[AttachmentData] = []
    max_bytes = settings.ATTACHMENT_MAX_SIZE_MB * 1024 * 1024

    if not msg.is_multipart():
        return attachments

    save_dir = settings.ATTACHMENTS_DIR
    save_dir.mkdir(parents=True, exist_ok=True)

    for part in msg.walk():
        content_disp = str(part.get("Content-Disposition", ""))
        filename = part.get_filename()

        if not filename and "attachment" not in content_disp:
            continue
        if not filename:
            continue

        # Decode RFC 2047 encoded filenames
        filename = _decode_header(filename)

        mime_type = part.get_content_type()
        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        size = len(payload)
        if size > max_bytes:
            logger.warning(
                "Gmail: anexo '%s' excede limite (%d MB) — ignorado",
                filename,
                settings.ATTACHMENT_MAX_SIZE_MB,
            )
            continue

        # Sanitize filename for filesystem
        safe_name = "".join(c if c.isalnum() or c in ".-_ " else "_" for c in filename)
        local_name = f"{email_stable_id}_{safe_name}"
        local_path = save_dir / local_name

        try:
            local_path.write_bytes(payload)
        except OSError as e:
            logger.warning("Gmail: falha ao salvar anexo '%s': %s", filename, e)
            continue

        att = AttachmentData(
            filename=filename,
            mime_type=mime_type,
            size_bytes=size,
            local_path=str(local_path),
        )
        attachments.append(att)
        logger.debug("Gmail: anexo salvo — %s (%d bytes, %s)", filename, size, mime_type)

    return attachments


class GmailClient:
    """Read and respond to emails via Gmail IMAP/SMTP with App Password."""

    def __init__(
        self,
        email_addr: Optional[str] = None,
        app_password: Optional[str] = None,
    ):
        self.email_addr = email_addr or settings.GMAIL_EMAIL
        self.app_password = app_password or settings.GMAIL_APP_PASSWORD
        if not self.email_addr or not self.app_password:
            raise ValueError(
                "Gmail credentials not configured. Set GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env"
            )

    # ------------------------------------------------------------------
    # IMAP connection
    # ------------------------------------------------------------------

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Open an authenticated IMAP connection."""
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        conn.login(self.email_addr, self.app_password)
        return conn

    # ------------------------------------------------------------------
    # Read emails
    # ------------------------------------------------------------------

    def list_unread(self, folder: str = "INBOX", limit: int = 20) -> list[EmailData]:
        """Fetch unread emails and return as EmailData objects.

        Args:
            folder: IMAP folder to read from.
            limit: Max number of unread emails to fetch.

        Returns:
            List of EmailData with body populated.
        """
        conn = self._connect_imap()
        try:
            conn.select(folder, readonly=True)
            _, data = conn.search(None, "UNSEEN")
            msg_ids = data[0].split() if data[0] else []

            if not msg_ids:
                logger.info("Gmail: nenhum e-mail não lido encontrado.")
                return []

            # Most recent first, respect limit
            msg_ids = msg_ids[-limit:][::-1]
            logger.info("Gmail: %d e-mail(s) não lido(s) encontrado(s).", len(msg_ids))

            emails: list[EmailData] = []
            for idx, msg_id in enumerate(msg_ids):
                _, msg_data = conn.fetch(msg_id, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                sender = _decode_header(msg.get("From", ""))
                subject = _decode_header(msg.get("Subject", ""))
                date_str = msg.get("Date", "")
                body = _extract_text(msg)
                message_id = msg.get("Message-ID", "")

                ed = EmailData(
                    sender=sender,
                    subject=subject,
                    preview=body[:200] if body else "",
                    body=body,
                    email_index=idx,
                    is_unread=True,
                    timestamp=date_str,
                    gmail_msg_id=msg_id.decode("utf-8"),
                    gmail_message_id=message_id,
                )
                ed.compute_stable_id()

                # Extract attachments
                atts = _extract_attachments(msg, ed.stable_id)
                if atts:
                    ed.attachments = atts
                    ed.has_attachments = True

                emails.append(ed)

                att_info = f", {len(atts)} anexo(s)" if atts else ""
                logger.info(
                    "  [%d/%d] %s (id: %s%s)",
                    idx + 1,
                    len(msg_ids),
                    subject[:60],
                    ed.stable_id[:8],
                    att_info,
                )

            return emails
        finally:
            conn.logout()

    # ------------------------------------------------------------------
    # Mark as read
    # ------------------------------------------------------------------

    def mark_read(self, gmail_msg_id: str, folder: str = "INBOX") -> bool:
        """Mark a specific email as read (Seen) by its IMAP message ID."""
        conn = self._connect_imap()
        try:
            conn.select(folder)
            conn.store(gmail_msg_id.encode(), "+FLAGS", "\\Seen")
            logger.debug("Gmail: marcou msg %s como lido.", gmail_msg_id)
            return True
        except Exception as e:
            logger.warning("Gmail: falha ao marcar msg %s como lido: %s", gmail_msg_id, e)
            return False
        finally:
            conn.logout()

    # ------------------------------------------------------------------
    # Send reply (save as draft or send directly)
    # ------------------------------------------------------------------

    def _default_cc(self, explicit_cc: str | None) -> str:
        """Resolve the Cc header: explicit param wins, otherwise use the
        settings default (``EMAIL_CC_DEFAULT``). Empty string disables Cc.
        """
        if explicit_cc is not None:
            return explicit_cc
        return getattr(settings, "EMAIL_CC_DEFAULT", "") or ""

    def send_reply(
        self,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
        cc_addr: str | None = None,
    ) -> bool:
        """Send a reply email via SMTP.

        For now this is used to save responses. In Marco II with confidence
        routing, high-confidence replies can be sent directly.

        Args:
            to_addr: Recipient email address.
            subject: Email subject (will prepend "Re: " if not present).
            body: Plain text body of the reply.
            in_reply_to: Message-ID of the original email for threading.
            cc_addr: Explicit Cc header. Pass ``""`` to disable the
                default Cc; omit to use ``settings.EMAIL_CC_DEFAULT``.

        Returns:
            True if sent successfully.
        """
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.email_addr
        msg["To"] = to_addr
        cc = self._default_cc(cc_addr)
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        recipients = [to_addr] + ([cc] if cc else [])
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(self.email_addr, self.app_password)
                server.send_message(msg, to_addrs=recipients)
            logger.info(
                "Gmail: resposta enviada para %s%s — %s",
                to_addr,
                f" (cc {cc})" if cc else "",
                subject[:50],
            )
            return True
        except Exception as e:
            logger.error("Gmail: falha ao enviar resposta: %s", e)
            return False

    def save_draft(
        self,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
        cc_addr: str | None = None,
    ) -> bool:
        """Save a reply as a draft in Gmail's Drafts folder via IMAP APPEND.

        Args:
            to_addr: Recipient email address.
            subject: Email subject.
            body: Plain text body.
            in_reply_to: Message-ID of the original email.
            cc_addr: Explicit Cc header. Pass ``""`` to disable the
                default Cc; omit to use ``settings.EMAIL_CC_DEFAULT``.

        Returns:
            True if draft saved successfully.
        """
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.email_addr
        msg["To"] = to_addr
        cc = self._default_cc(cc_addr)
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        conn = self._connect_imap()
        try:
            conn.append("[Gmail]/Drafts", "\\Draft", None, msg.as_bytes())
            logger.info(
                "Gmail: rascunho salvo para %s%s — %s",
                to_addr,
                f" (cc {cc})" if cc else "",
                subject[:50],
            )
            return True
        except Exception as e:
            logger.error("Gmail: falha ao salvar rascunho: %s", e)
            return False
        finally:
            conn.logout()

    # ------------------------------------------------------------------
    # Thread-aware helpers (Gmail X-GM-THRID extension)
    # ------------------------------------------------------------------

    def _resolve_thread(
        self, conn: imaplib.IMAP4_SSL, message_id: str
    ) -> tuple[str, list[bytes]]:
        """Given a SELECTed connection on [Gmail]/All Mail, resolve the
        Gmail thread containing ``message_id``. Returns (thread_id,
        sequence_numbers). Empty tuple if not found.
        """
        if not message_id:
            return "", []
        # Gmail's IMAP rejects Message-IDs with '+' / '@' / '<' / '>' unless
        # the value is explicitly quoted. ``imaplib`` only auto-quotes when
        # the arg contains whitespace, so we quote manually (escaping any
        # embedded double-quote or backslash). Use X-GM-RAW + rfc822msgid:
        # — Gmail's native and most forgiving Message-ID search operator.
        escaped = message_id.replace("\\", "\\\\").replace('"', '\\"')
        query = f'rfc822msgid:"{escaped}"'
        _, data = conn.search(None, "X-GM-RAW", f'"{query}"')
        msns = data[0].split() if data and data[0] else []
        if not msns:
            return "", []
        _, hdr = conn.fetch(msns[0], "(X-GM-THRID)")
        if not hdr or not hdr[0]:
            return "", []
        raw = hdr[0]
        if isinstance(raw, tuple):
            raw = raw[0]
        m = _THRID_RE.search(raw)
        if not m:
            return "", []
        thrid = m.group(1).decode("ascii")
        _, data = conn.search(None, "X-GM-THRID", thrid)
        thread_msns = data[0].split() if data and data[0] else []
        return thrid, thread_msns

    def thread_last_sender(self, message_id: str) -> str:
        """Return the lowercased bare email of the most recent sender in the
        Gmail thread that contains ``message_id`` (RFC Message-ID header).

        Searches [Gmail]/All Mail so the result includes Sent items — needed
        to detect when the human coordinator has already replied. Returns
        ``""`` if the thread cannot be resolved.
        """
        if not message_id:
            return ""
        try:
            conn = self._connect_imap()
        except Exception as e:
            logger.warning("Gmail: thread_last_sender — falha no IMAP: %s", e)
            return ""
        try:
            conn.select(ALL_MAIL_FOLDER, readonly=True)
            _thrid, msns = self._resolve_thread(conn, message_id)
            if not msns:
                return ""
            latest_ts = -1.0
            latest_sender = ""
            for msn in msns:
                _, hdr = conn.fetch(msn, "(BODY.PEEK[HEADER.FIELDS (FROM DATE)])")
                if not hdr or not hdr[0]:
                    continue
                payload = hdr[0][1] if isinstance(hdr[0], tuple) else hdr[0]
                msg = email.message_from_bytes(payload)
                try:
                    ts = email.utils.parsedate_to_datetime(msg.get("Date", "")).timestamp()
                except (TypeError, ValueError, AttributeError):
                    ts = 0.0
                if ts >= latest_ts:
                    latest_ts = ts
                    latest_sender = _parse_address(_decode_header(msg.get("From", "")))
            return latest_sender
        except Exception as e:
            logger.warning("Gmail: thread_last_sender — exceção (%s)", e)
            return ""
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def copy_thread_to_label(self, message_id: str, label: str) -> tuple[int, str]:
        """Copy every message in the Gmail thread to ``label``.

        Creates the label if missing (IMAP CREATE on an existing folder
        fails silently). Returns (count_copied, thread_id). Returns (0, "")
        if the thread can't be resolved or the copy fails. Idempotent from
        Gmail's perspective — copying a message already in the label just
        keeps the label applied.
        """
        if not message_id or not label:
            return 0, ""
        try:
            conn = self._connect_imap()
        except Exception as e:
            logger.warning("Gmail: copy_thread_to_label — falha no IMAP: %s", e)
            return 0, ""
        try:
            # Ensure label exists; ignore "already exists" errors.
            try:
                conn.create(f'"{label}"')
            except Exception:
                pass

            conn.select(ALL_MAIL_FOLDER, readonly=False)
            thrid, msns = self._resolve_thread(conn, message_id)
            if not msns:
                return 0, thrid

            uid_set = b",".join(msns)
            status, _ = conn.copy(uid_set, f'"{label}"')
            if status != "OK":
                logger.warning(
                    "Gmail: copy_thread_to_label — status %s para thread %s label '%s'",
                    status,
                    thrid,
                    label,
                )
                return 0, thrid
            logger.info(
                "Gmail: thread %s (%d msg) copiada para label '%s'",
                thrid,
                len(msns),
                label,
            )
            return len(msns), thrid
        except Exception as e:
            logger.warning(
                "Gmail: copy_thread_to_label — exceção (message_id=%s, label=%s): %s",
                message_id[:40],
                label,
                e,
            )
            return 0, ""
        finally:
            try:
                conn.logout()
            except Exception:
                pass
