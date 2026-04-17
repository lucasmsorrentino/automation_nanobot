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
            assert client.app_password == "pass123"
