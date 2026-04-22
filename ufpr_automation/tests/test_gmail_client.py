"""Tests for gmail/client.py — helper functions and GmailClient logic.

Covers the pure helper functions (_decode_header, _extract_text,
_extract_attachments) and the _default_cc method without hitting IMAP/SMTP.
"""

from __future__ import annotations

import email
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

import pytest

from ufpr_automation.gmail.client import (
    GmailClient,
    _decode_header,
    _extract_attachments,
    _extract_text,
)


# ---------------------------------------------------------------------------
# _decode_header
# ---------------------------------------------------------------------------


class TestDecodeHeader:
    def test_empty_string(self):
        assert _decode_header("") == ""

    def test_plain_ascii(self):
        assert _decode_header("Hello World") == "Hello World"

    def test_rfc2047_utf8(self):
        # Standard RFC 2047 encoded header
        raw = "=?utf-8?B?UHJlemFkbyBDb29yZGVuYWRvcg==?="
        assert "Prezado Coordenador" in _decode_header(raw)

    def test_rfc2047_iso8859(self):
        raw = "=?iso-8859-1?Q?Re:_Solicita=E7=E3o?="
        result = _decode_header(raw)
        assert "Solicita" in result

    def test_multi_part_header(self):
        raw = "=?utf-8?B?UGFydGUgMQ==?= =?utf-8?B?IFBhcnRlIDI=?="
        result = _decode_header(raw)
        assert "Parte 1" in result
        assert "Parte 2" in result

    def test_none_returns_empty(self):
        # _decode_header is called with msg.get() which returns None
        # but the function checks `not raw`, so "" is passed.
        assert _decode_header("") == ""


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_plain_text_message(self):
        msg = MIMEText("Corpo da mensagem em texto.", "plain", "utf-8")
        assert "Corpo da mensagem em texto" in _extract_text(msg)

    def test_multipart_with_plain_and_html(self):
        outer = MIMEMultipart("alternative")
        outer.attach(MIMEText("Texto simples", "plain", "utf-8"))
        outer.attach(MIMEText("<p>HTML bonito</p>", "html", "utf-8"))
        # Should prefer plain text
        result = _extract_text(outer)
        assert "Texto simples" in result

    def test_multipart_html_only_fallback(self):
        outer = MIMEMultipart("alternative")
        outer.attach(MIMEText("<p>Apenas HTML</p>", "html", "utf-8"))
        result = _extract_text(outer)
        assert "Apenas HTML" in result

    def test_multipart_with_attachment_skips_attachment(self):
        outer = MIMEMultipart("mixed")
        outer.attach(MIMEText("Corpo real", "plain", "utf-8"))
        att = MIMEText("conteudo do anexo", "plain", "utf-8")
        att.add_header("Content-Disposition", "attachment", filename="doc.txt")
        outer.attach(att)
        result = _extract_text(outer)
        assert "Corpo real" in result
        assert "conteudo do anexo" not in result

    def test_empty_payload(self):
        msg = email.message.Message()
        msg.set_payload(None)
        result = _extract_text(msg)
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_attachments
# ---------------------------------------------------------------------------


class TestExtractAttachments:
    def test_non_multipart_returns_empty(self):
        msg = MIMEText("simple", "plain")
        result = _extract_attachments(msg, "stable123")
        assert result == []

    def test_extracts_single_attachment(self, tmp_path):
        outer = MIMEMultipart("mixed")
        outer.attach(MIMEText("body", "plain"))

        att = MIMEBase("application", "pdf")
        att.set_payload(b"%PDF-1.4 fake content")
        att.add_header("Content-Disposition", "attachment", filename="tce.pdf")
        att.add_header("Content-Transfer-Encoding", "base64")
        # Encode properly for extraction
        from email.encoders import encode_base64

        encode_base64(att)
        outer.attach(att)

        with patch("ufpr_automation.gmail.client.settings") as mock_settings:
            mock_settings.ATTACHMENT_MAX_SIZE_MB = 10
            mock_settings.ATTACHMENTS_DIR = tmp_path
            result = _extract_attachments(outer, "stable123")

        assert len(result) == 1
        assert result[0].filename == "tce.pdf"
        assert result[0].mime_type == "application/pdf"
        assert result[0].size_bytes > 0

    def test_skips_oversized_attachment(self, tmp_path):
        outer = MIMEMultipart("mixed")
        outer.attach(MIMEText("body", "plain"))

        att = MIMEBase("application", "pdf")
        att.set_payload(b"x" * 1000)
        att.add_header("Content-Disposition", "attachment", filename="big.pdf")
        from email.encoders import encode_base64

        encode_base64(att)
        outer.attach(att)

        with patch("ufpr_automation.gmail.client.settings") as mock_settings:
            # Set max to something tiny (0.0001 MB = ~100 bytes)
            mock_settings.ATTACHMENT_MAX_SIZE_MB = 0.0001
            mock_settings.ATTACHMENTS_DIR = tmp_path
            result = _extract_attachments(outer, "stable123")

        assert result == []

    def test_no_filename_skips(self):
        outer = MIMEMultipart("mixed")
        outer.attach(MIMEText("body", "plain"))
        # Part without filename and without "attachment" in disposition
        part = MIMEText("inline text", "plain")
        outer.attach(part)

        result = _extract_attachments(outer, "stable123")
        assert result == []

    def test_multiple_attachments(self, tmp_path):
        outer = MIMEMultipart("mixed")
        outer.attach(MIMEText("body", "plain"))

        from email.encoders import encode_base64

        for name in ("doc1.pdf", "doc2.docx"):
            att = MIMEBase("application", "octet-stream")
            att.set_payload(b"fake content")
            att.add_header("Content-Disposition", "attachment", filename=name)
            encode_base64(att)
            outer.attach(att)

        with patch("ufpr_automation.gmail.client.settings") as mock_settings:
            mock_settings.ATTACHMENT_MAX_SIZE_MB = 10
            mock_settings.ATTACHMENTS_DIR = tmp_path
            result = _extract_attachments(outer, "stable123")

        assert len(result) == 2
        filenames = {r.filename for r in result}
        assert filenames == {"doc1.pdf", "doc2.docx"}


# ---------------------------------------------------------------------------
# GmailClient._default_cc
# ---------------------------------------------------------------------------


class TestDefaultCc:
    def _make_client(self, cc_default: str = ""):
        with patch("ufpr_automation.gmail.client.settings") as mock_settings:
            mock_settings.GMAIL_EMAIL = "test@gmail.com"
            mock_settings.GMAIL_APP_PASSWORD = "fakepass"
            client = GmailClient(email_addr="test@gmail.com", app_password="fakepass")
        return client, cc_default

    def test_explicit_cc_wins(self):
        client, _ = self._make_client()
        assert client._default_cc("explicit@ufpr.br") == "explicit@ufpr.br"

    def test_explicit_empty_disables_cc(self):
        client, _ = self._make_client()
        assert client._default_cc("") == ""

    def test_none_falls_back_to_settings(self):
        with patch("ufpr_automation.gmail.client.settings") as mock_settings:
            mock_settings.GMAIL_EMAIL = "test@gmail.com"
            mock_settings.GMAIL_APP_PASSWORD = "fakepass"
            mock_settings.EMAIL_CC_DEFAULT = "coord@ufpr.br"
            client = GmailClient(email_addr="test@gmail.com", app_password="fakepass")
            assert client._default_cc(None) == "coord@ufpr.br"

    def test_none_with_no_setting(self):
        with patch("ufpr_automation.gmail.client.settings") as mock_settings:
            mock_settings.GMAIL_EMAIL = "test@gmail.com"
            mock_settings.GMAIL_APP_PASSWORD = "fakepass"
            # Simulate missing attribute
            del mock_settings.EMAIL_CC_DEFAULT
            client = GmailClient(email_addr="test@gmail.com", app_password="fakepass")
            assert client._default_cc(None) == ""


# ---------------------------------------------------------------------------
# GmailClient constructor
# ---------------------------------------------------------------------------


class TestGmailClientInit:
    def test_raises_without_credentials(self):
        with patch("ufpr_automation.gmail.client.settings") as mock_settings:
            mock_settings.GMAIL_EMAIL = ""
            mock_settings.GMAIL_APP_PASSWORD = ""
            with pytest.raises(ValueError, match="credentials not configured"):
                GmailClient()

    def test_accepts_explicit_credentials(self):
        with patch("ufpr_automation.gmail.client.settings"):
            client = GmailClient(email_addr="a@b.com", app_password="pass123")
            assert client.email_addr == "a@b.com"


# ---------------------------------------------------------------------------
# Thread-aware helpers — FakeIMAP minimal harness
# ---------------------------------------------------------------------------


class _FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL used by thread helpers.

    Each test wires up which message IDs live in which thread via
    ``messages`` (dict keyed by MSN) and configures the search/fetch
    responses programmatically.
    """

    def __init__(self):
        self.messages: dict[bytes, dict] = {}
        self.thread_by_msn: dict[bytes, bytes] = {}
        self.create_calls: list[str] = []
        self.copy_calls: list[tuple[bytes, str]] = []
        self.selected_folder: str | None = None
        self.select_modes: list[tuple[str, bool]] = []
        self.create_raises: bool = False
        self.copy_status: str = "OK"
        self.logged_out: bool = False

    def select(self, folder, readonly=False):
        self.selected_folder = folder
        self.select_modes.append((folder, readonly))
        return ("OK", [b"1"])

    def search(self, _charset, *criteria):
        # Call shapes we need to support:
        #   search(None, "X-GM-RAW", '"rfc822msgid:\"<abc>\""')
        #   search(None, "X-GM-THRID", "12345")
        if criteria and criteria[0] == "X-GM-RAW":
            raw = criteria[1]
            stripped = raw.strip('"')
            if stripped.startswith("rfc822msgid:"):
                needle = stripped[len("rfc822msgid:"):]
                needle = needle.replace('\\"', '"').replace("\\\\", "\\")

                def _norm(s: str) -> str:
                    return s.strip().strip("<>")

                matches = [
                    msn
                    for msn, m in self.messages.items()
                    if _norm(m.get("message_id", "")) == _norm(needle)
                ]
                return ("OK", [b" ".join(matches) if matches else b""])
            return ("OK", [b""])
        if criteria and criteria[0] == "X-GM-THRID":
            thrid = criteria[1].encode() if isinstance(criteria[1], str) else criteria[1]
            matches = [msn for msn, tid in self.thread_by_msn.items() if tid == thrid]
            return ("OK", [b" ".join(matches) if matches else b""])
        return ("OK", [b""])

    def fetch(self, msn, spec):
        if isinstance(msn, str):
            msn = msn.encode()
        if spec == "(X-GM-THRID)":
            thrid = self.thread_by_msn.get(msn, b"0")
            return ("OK", [b"1 (X-GM-THRID " + thrid + b" UID 999)"])
        if "HEADER.FIELDS" in spec:
            m = self.messages.get(msn, {})
            payload = (
                f"From: {m.get('from', '')}\r\n"
                f"Date: {m.get('date', '')}\r\n\r\n"
            ).encode("utf-8")
            return ("OK", [(b"1 (BODY[HEADER.FIELDS (FROM DATE)] {%d}" % len(payload), payload), b")"])
        return ("OK", [b""])

    def create(self, label):
        if self.create_raises:
            raise Exception("already exists")
        self.create_calls.append(label)
        return ("OK", [b""])

    def copy(self, uid_set, dest):
        if isinstance(uid_set, bytes):
            self.copy_calls.append((uid_set, dest))
        else:
            self.copy_calls.append((uid_set.encode(), dest))
        return (self.copy_status, [b""])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b""])


def _make_client_with_fake(fake: _FakeIMAP):
    with patch("ufpr_automation.gmail.client.settings") as mock_settings:
        mock_settings.GMAIL_EMAIL = "test@gmail.com"
        mock_settings.GMAIL_APP_PASSWORD = "fakepass"
        client = GmailClient(email_addr="test@gmail.com", app_password="fakepass")
    client._connect_imap = lambda: fake  # type: ignore[method-assign]
    return client


class TestThreadLastSender:
    def test_returns_most_recent_sender_from_thread(self):
        fake = _FakeIMAP()
        # Thread of 3 messages — coordinator replied last.
        fake.messages = {
            b"10": {
                "message_id": "<student@example.com>",
                "from": "Aluno <aluno@ufpr.br>",
                "date": "Mon, 20 Apr 2026 09:00:00 +0000",
            },
            b"11": {
                "message_id": "<coord@example.com>",
                "from": "Secretaria DG <design.grafico@ufpr.br>",
                "date": "Wed, 22 Apr 2026 15:30:00 +0000",
            },
            b"12": {
                "message_id": "<student2@example.com>",
                "from": "Aluno <aluno@ufpr.br>",
                "date": "Tue, 21 Apr 2026 14:00:00 +0000",
            },
        }
        fake.thread_by_msn = {b"10": b"999", b"11": b"999", b"12": b"999"}
        client = _make_client_with_fake(fake)

        sender = client.thread_last_sender("<student@example.com>")
        assert sender == "design.grafico@ufpr.br"
        assert fake.logged_out is True

    def test_empty_message_id_returns_empty(self):
        fake = _FakeIMAP()
        client = _make_client_with_fake(fake)
        # Should not even connect.
        client._connect_imap = lambda: (_ for _ in ()).throw(AssertionError("should not connect"))  # type: ignore[method-assign]
        assert client.thread_last_sender("") == ""

    def test_unresolved_thread_returns_empty(self):
        fake = _FakeIMAP()
        # No messages match — search returns empty.
        client = _make_client_with_fake(fake)
        assert client.thread_last_sender("<unknown@example.com>") == ""

    def test_message_id_with_plus_and_at_is_quoted_safely(self):
        """Regression for Gmail IMAP 'BAD Could not parse command' when a
        Message-ID with '+' or '@' is passed unquoted. We wrap in
        X-GM-RAW rfc822msgid:"..." which handles special chars.
        """
        tricky_id = "<CAB+deadbeef-123@mail.gmail.com>"
        fake = _FakeIMAP()
        fake.messages = {
            b"7": {
                "message_id": tricky_id,
                "from": "design.grafico@ufpr.br",
                "date": "Tue, 22 Apr 2026 10:00:00 +0000",
            },
        }
        fake.thread_by_msn = {b"7": b"321"}
        client = _make_client_with_fake(fake)
        assert client.thread_last_sender(tricky_id) == "design.grafico@ufpr.br"

    def test_student_replied_last_returns_student(self):
        fake = _FakeIMAP()
        fake.messages = {
            b"1": {
                "message_id": "<m1@x>",
                "from": "design.grafico@ufpr.br",
                "date": "Mon, 20 Apr 2026 09:00:00 +0000",
            },
            b"2": {
                "message_id": "<m2@x>",
                "from": "Aluno <aluno@ufpr.br>",
                "date": "Tue, 21 Apr 2026 10:00:00 +0000",
            },
        }
        fake.thread_by_msn = {b"1": b"42", b"2": b"42"}
        client = _make_client_with_fake(fake)
        assert client.thread_last_sender("<m1@x>") == "aluno@ufpr.br"


class TestCopyThreadToLabel:
    def test_creates_label_and_copies_full_thread(self):
        fake = _FakeIMAP()
        fake.messages = {
            b"5": {"message_id": "<m5@x>", "from": "a@x", "date": ""},
            b"6": {"message_id": "<m6@x>", "from": "b@x", "date": ""},
        }
        fake.thread_by_msn = {b"5": b"777", b"6": b"777"}
        client = _make_client_with_fake(fake)

        count, thread_id = client.copy_thread_to_label(
            "<m5@x>", "aprendizado/interacoes-secretaria-humano"
        )
        assert count == 2
        assert thread_id == "777"
        assert fake.create_calls == ['"aprendizado/interacoes-secretaria-humano"']
        assert len(fake.copy_calls) == 1
        uid_set, dest = fake.copy_calls[0]
        # Order depends on dict iteration; check set equality on split bytes.
        assert set(uid_set.split(b",")) == {b"5", b"6"}
        assert dest == '"aprendizado/interacoes-secretaria-humano"'
        assert fake.logged_out is True

    def test_label_already_exists_is_non_fatal(self):
        fake = _FakeIMAP()
        fake.create_raises = True  # simulate "folder exists" error
        fake.messages = {b"1": {"message_id": "<m@x>", "from": "a@x", "date": ""}}
        fake.thread_by_msn = {b"1": b"4242"}
        client = _make_client_with_fake(fake)
        count, thread_id = client.copy_thread_to_label("<m@x>", "some/label")
        assert count == 1
        assert thread_id == "4242"

    def test_empty_args_return_zero(self):
        fake = _FakeIMAP()
        client = _make_client_with_fake(fake)
        assert client.copy_thread_to_label("", "label") == (0, "")
        assert client.copy_thread_to_label("<x>", "") == (0, "")

    def test_unresolved_thread_returns_zero(self):
        fake = _FakeIMAP()
        client = _make_client_with_fake(fake)
        count, thread_id = client.copy_thread_to_label("<missing@x>", "some/label")
        assert count == 0
        assert thread_id == ""
        assert fake.copy_calls == []

    def test_copy_status_failure_returns_zero(self):
        fake = _FakeIMAP()
        fake.copy_status = "NO"
        fake.messages = {b"1": {"message_id": "<m@x>", "from": "a@x", "date": ""}}
        fake.thread_by_msn = {b"1": b"5555"}
        client = _make_client_with_fake(fake)
        count, thread_id = client.copy_thread_to_label("<m@x>", "some/label")
        assert count == 0
        # thread_id is still returned so the caller can log it
        assert thread_id == "5555"
