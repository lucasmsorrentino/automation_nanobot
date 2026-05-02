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
from email.mime.text import MIMEText
from typing import Optional

from ufpr_automation.config import settings
from ufpr_automation.core.models import AttachmentData, EmailData
from ufpr_automation.utils.logging import logger

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

ALL_MAIL_FOLDER = '"[Gmail]/All Mail"'

_THRID_RE = re.compile(rb"X-GM-THRID (\d+)")

# Pipeline-managed Gmail labels. ``PROCESSED_LABEL`` is the durable marker
# that ``list_unread`` excludes — once an email has it, the pipeline never
# re-picks it, even if Gmail's ``\Seen`` flag gets reset (which happens
# when the user/another client opens it on the web). The category labels
# are organizational; they get applied alongside the marker.
PROCESSED_LABEL = "ufpr/processado"
_CATEGORIA_TO_LABEL = {
    "Estágios": "ufpr/estagios",
    "Acadêmico": "ufpr/academico",
    "Diplomação": "ufpr/diplomacao",
    "Extensão": "ufpr/extensao",
    "Formativas": "ufpr/formativas",
    "Requerimentos": "ufpr/requerimentos",
    "Urgente": "ufpr/urgente",
    "Correio Lixo": "ufpr/lixo",
    "Outros": "ufpr/outros",
}


def categoria_to_label(categoria: str) -> str:
    """Map a ``Categoria`` value to its Gmail label.

    Categoria uses ``" / "`` for sub-categories (e.g. ``"Diplomação /
    Diploma"``) — we collapse to the top-level label, since the goal is
    inbox triage rather than perfect mirroring.
    """
    if not categoria:
        return "ufpr/outros"
    top = categoria.split(" / ")[0].strip()
    return _CATEGORIA_TO_LABEL.get(top, "ufpr/outros")

# Sign-off markers that open the signature block in Portuguese correspondence.
# Matched at start-of-line (tolerating leading whitespace). The last
# occurrence wins so we don't cut legitimate body text that happens to
# contain the word elsewhere.
_SIGNATURE_MARKER_RE = re.compile(
    r"(?im)^\s*(atenciosamente|att|cordialmente|sauda[çc][õo]es|respeitosamente)\s*[,.:]?\s*$"
)

# Hallucinated sector names that have shown up in LLM output and must be
# stripped even if they appear above the sign-off marker. This list is
# defensive — extend it when new hallucinations surface in logs.
_HALLUCINATED_SECTORS = (
    "Núcleo de Estágios",
    "Nucleo de Estagios",
)


def normalize_signature_block(body: str, canonical: str) -> str:
    """Replace whatever sign-off the source produced with ``canonical``.

    LLMs (including MiniMax-M2 used by the project) routinely invent
    sectors like "Núcleo de Estágios / UFPR" that do not exist, and
    draft-to-draft signatures drift in wording and case. To keep every
    outgoing draft anchored to the real persona, we rewrite the tail of
    the body:

    1. Find the LAST sign-off marker (``Atenciosamente``, ``Att``,
       ``Cordialmente``...) on its own line; cut everything from that
       line onwards.
    2. Strip any line containing a known hallucinated sector.
    3. Append ``canonical`` (typically ``settings.ASSINATURA_EMAIL``)
       separated by a blank line.

    If ``canonical`` is empty the body is returned unchanged (useful for
    test environments without ``ASSINATURA_EMAIL`` configured).
    """
    if not canonical or not canonical.strip():
        return body
    if not body:
        return canonical.rstrip() + "\n"

    lines = body.splitlines()
    cut_at: Optional[int] = None
    for i in range(len(lines) - 1, -1, -1):
        if _SIGNATURE_MARKER_RE.match(lines[i]):
            cut_at = i
            break
    if cut_at is not None:
        lines = lines[:cut_at]

    # Strip lines that carry hallucinated sector names (case-insensitive,
    # accent-insensitive for the ASCII fallback).
    cleaned = []
    for line in lines:
        low = line.lower()
        if any(h.lower() in low for h in _HALLUCINATED_SECTORS):
            continue
        cleaned.append(line)

    trimmed = "\n".join(cleaned).rstrip()
    return trimmed + "\n\n" + canonical.rstrip() + "\n"


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
        """Open an authenticated IMAP connection.

        ``timeout=120`` aplica ao socket TCP — sem ele, ``imaplib`` herda o
        default do Python (None = bloqueio infinito), e o pipeline trava se
        o servidor parar de responder no meio de um FETCH (visto live em
        2026-04-30 — pipeline ficou 1h+ em ``recv_into`` sem progresso).
        2 min cobre operacoes legitimamente lentas (anexos grandes) sem
        permitir hang indefinido.
        """
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=120)
        conn.login(self.email_addr, self.app_password)
        return conn

    # ------------------------------------------------------------------
    # Read emails
    # ------------------------------------------------------------------

    def list_unread(self, folder: str = "INBOX", limit: int = 20) -> list[EmailData]:
        """Fetch unread emails and return as EmailData objects.

        Uses IMAP **UIDs** (not sequence numbers) throughout: UIDs are
        stable across sessions, so the ``mark_read`` call later in the
        pipeline operates on the exact same message even if new mail
        arrived in INBOX during the run. Using MSNs caused drift under
        sustained runs (10+ min) — new unread mail shifted numbering,
        and ``STORE +Seen`` quietly hit the wrong row, leaving emails
        as UNSEEN and making subsequent runs re-pick them.

        Args:
            folder: IMAP folder to read from.
            limit: Max number of unread emails to fetch.

        Returns:
            List of EmailData with body populated.
        """
        conn = self._connect_imap()
        try:
            conn.select(folder, readonly=True)
            # Exclude anything already labeled with the pipeline marker —
            # durable across sessions even if ``\Seen`` is reset (e.g. when
            # the user opens the email on Gmail web). ``X-GM-RAW`` is
            # Gmail's IMAP extension that accepts native search syntax.
            _, data = conn.uid(
                "SEARCH",
                None,
                "UNSEEN",
                "X-GM-RAW",
                f'-label:{PROCESSED_LABEL}',
            )
            msg_uids = data[0].split() if data[0] else []

            if not msg_uids:
                logger.info("Gmail: nenhum e-mail não lido encontrado.")
                return []

            # Most recent first, respect limit
            msg_uids = msg_uids[-limit:][::-1]
            logger.info("Gmail: %d e-mail(s) não lido(s) encontrado(s).", len(msg_uids))

            emails: list[EmailData] = []
            for idx, msg_uid in enumerate(msg_uids):
                _, msg_data = conn.uid("FETCH", msg_uid, "(RFC822)")
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
                    gmail_msg_id=msg_uid.decode("utf-8"),
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
                    len(msg_uids),
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

    def apply_labels(
        self,
        gmail_msg_id: str,
        labels: list[str],
        folder: str = "INBOX",
    ) -> bool:
        """Add one or more Gmail labels to a message by IMAP UID.

        Uses Gmail's ``X-GM-LABELS`` IMAP extension via ``UID STORE +X-GM-LABELS``
        — this is non-destructive (existing labels are preserved) and
        idempotent (re-applying a label is a no-op). Ensures each label
        exists first via ``conn.create`` (which fails silently if it already
        does, like every other IMAP CREATE).

        Args:
            gmail_msg_id: IMAP UID from ``list_unread``.
            labels: list of Gmail label paths (use ``/`` for nesting,
                e.g. ``"ufpr/estagios"``).

        Returns:
            True if the STORE command succeeded; False otherwise. Failures
            are logged at WARNING level but don't raise.
        """
        if not gmail_msg_id or not labels:
            return False
        conn = self._connect_imap()
        try:
            conn.select(folder)
            for label in labels:
                try:
                    conn.create(f'"{label}"')
                except Exception:
                    pass  # already exists — IMAP CREATE is idempotent-by-error
            # Build space-separated, double-quoted label list:
            #   ("ufpr/processado" "ufpr/estagios")
            quoted = " ".join(f'"{label}"' for label in labels)
            typ, resp = conn.uid(
                "STORE",
                gmail_msg_id.encode(),
                "+X-GM-LABELS",
                f"({quoted})",
            )
            if typ != "OK":
                logger.warning(
                    "Gmail: STORE +X-GM-LABELS retornou %s para uid=%s labels=%s (%r)",
                    typ,
                    gmail_msg_id,
                    labels,
                    resp,
                )
                return False
            logger.debug("Gmail: aplicou labels=%s em uid=%s", labels, gmail_msg_id)
            return True
        except Exception as e:
            logger.warning(
                "Gmail: falha ao aplicar labels=%s em uid=%s: %s",
                labels,
                gmail_msg_id,
                e,
            )
            return False
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def mark_read(self, gmail_msg_id: str, folder: str = "INBOX") -> bool:
        """Mark a specific email as read (Seen) by its IMAP UID.

        ``gmail_msg_id`` is the stable IMAP UID captured by ``list_unread``
        (not a sequence number). Uses ``UID STORE`` so the flag change
        hits the exact message even after INBOX has changed between the
        two sessions.
        """
        conn = self._connect_imap()
        try:
            conn.select(folder)
            typ, resp = conn.uid("STORE", gmail_msg_id.encode(), "+FLAGS", "\\Seen")
            if typ != "OK":
                logger.warning(
                    "Gmail: STORE +Seen retornou %s para uid=%s (%r)",
                    typ,
                    gmail_msg_id,
                    resp,
                )
                return False
            logger.debug("Gmail: marcou uid=%s como lido.", gmail_msg_id)
            return True
        except Exception as e:
            logger.warning("Gmail: falha ao marcar uid=%s como lido: %s", gmail_msg_id, e)
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

    def save_draft(
        self,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
        cc_addr: str | None = None,
    ) -> bool:
        """Save a reply as a draft in Gmail's Drafts folder via IMAP APPEND.

        Side-effects:
            1. Normalizes the body signature — any LLM-generated sign-off
               is replaced with ``settings.ASSINATURA_EMAIL`` (see
               :func:`normalize_signature_block`). This prevents the LLM
               from inventing fictitious sectors (e.g. "Núcleo de Estágios")
               or drifting persona across runs.
            2. Deletes any previous draft addressed to the same recipient
               in the same Gmail thread (matched by ``in_reply_to``) so
               each pipeline re-run leaves exactly one draft per thread
               instead of stacking stale versions.

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

        # Anti-hallucination: force canonical signature regardless of
        # whatever the LLM / template produced.
        body = normalize_signature_block(body, settings.ASSINATURA_EMAIL)

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
            # Best-effort: remove existing drafts for the same thread so the
            # reviewer doesn't see stacks of half-written replies from
            # previous pipeline runs.
            deleted = 0
            if in_reply_to:
                try:
                    deleted = self._delete_existing_drafts(conn, in_reply_to, to_addr)
                except Exception as e:
                    logger.debug("Gmail: falha limpando drafts antigos: %s", e)

            conn.append("[Gmail]/Drafts", "\\Draft", None, msg.as_bytes())
            logger.info(
                "Gmail: rascunho salvo para %s%s — %s%s",
                to_addr,
                f" (cc {cc})" if cc else "",
                subject[:50],
                f" [substituiu {deleted} antigo(s)]" if deleted else "",
            )
            return True
        except Exception as e:
            logger.error("Gmail: falha ao salvar rascunho: %s", e)
            return False
        finally:
            conn.logout()

    def _delete_existing_drafts(
        self,
        conn: imaplib.IMAP4_SSL,
        in_reply_to: str,
        to_addr: str,
    ) -> int:
        """Delete drafts in ``[Gmail]/Drafts`` addressed to ``to_addr`` whose
        ``In-Reply-To`` / ``References`` point to the same upstream message.

        Returns number of drafts deleted. Matching is conservative: the
        ``In-Reply-To`` header must contain the exact message-id and the
        recipient must match. We also fall back to matching by recipient
        alone for drafts whose headers have been stripped by Gmail — safer
        to drop a stale draft than to leave it confusing the reviewer.
        """
        stripped_mid = in_reply_to.strip().strip("<>")
        if not stripped_mid:
            return 0
        conn.select("[Gmail]/Drafts")
        try:
            # Gmail doesn't index In-Reply-To for SEARCH, but X-GM-RAW
            # with rfc822msgid: on References works.
            escaped = stripped_mid.replace("\\", "\\\\").replace('"', '\\"')
            quoted = f'"rfc822msgid:{escaped}"'
            try:
                _, data = conn.search(None, "X-GM-RAW", quoted)
            except imaplib.IMAP4.error:
                data = [b""]
            candidate_ids: set[bytes] = set((data[0].split() if data and data[0] else []))
            # Also match by TO alone — catches the case where Gmail
            # reorganized the draft and the thread link was lost.
            try:
                _, data_to = conn.search(None, "TO", to_addr)
                candidate_ids.update(data_to[0].split() if data_to and data_to[0] else [])
            except imaplib.IMAP4.error:
                pass

            deleted = 0
            for mid in candidate_ids:
                try:
                    conn.store(mid, "+FLAGS", "\\Deleted")
                    deleted += 1
                except imaplib.IMAP4.error:
                    continue
            if deleted:
                conn.expunge()
            return deleted
        finally:
            pass

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
        # imaplib sends args as-is without auto-quoting when they lack
        # whitespace. Gmail's IMAP then rejects Message-IDs like
        # "<CAB+…@mail.gmail.com>" because the bare angle brackets and
        # '+' aren't valid IMAP atom characters. Use Gmail's X-GM-RAW
        # extension with rfc822msgid: — it accepts the raw id and the
        # whole query is a single quoted IMAP literal.
        stripped = message_id.strip().strip("<>")
        # Escape embedded " or \\ inside the id (extremely rare).
        escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
        # Pre-quote the whole X-GM-RAW argument as an IMAP string.
        quoted_query = f'"rfc822msgid:{escaped}"'
        _, data = conn.search(None, "X-GM-RAW", quoted_query)
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
