"""Tests for gmail/thread.py — split_reply_and_quoted helper."""

from __future__ import annotations

from ufpr_automation.gmail.thread import (
    SplitBody,
    format_for_prompt,
    split_reply_and_quoted,
)


class TestSplitReplyAndQuoted:
    def test_empty_body(self):
        s = split_reply_and_quoted("")
        assert s.new_reply == ""
        assert s.quoted_history == ""
        assert s.has_history is False

    def test_no_history_plain_reply(self):
        body = "Bom dia, gostaria de saber o prazo para emissão de diploma.\nObrigado."
        s = split_reply_and_quoted(body)
        assert s.new_reply == body
        assert s.quoted_history == ""
        assert s.has_history is False

    def test_gmail_ptbr_attribution_single_line(self):
        body = (
            "Obrigado pela resposta!\n\n"
            "Em seg., 7 de abr. de 2026 às 10:00, Secretaria <a@b.com> escreveu:\n"
            "> Mensagem original do atendente."
        )
        s = split_reply_and_quoted(body)
        assert s.new_reply == "Obrigado pela resposta!"
        assert "escreveu:" in s.quoted_history
        assert "> Mensagem original" in s.quoted_history
        assert s.has_history is True

    def test_gmail_ptbr_attribution_wraps_at_angle_bracket(self):
        # Gmail commonly wraps long attribution lines at the angle bracket
        # of the email address. The attribution "Em ... escreveu:" then
        # spans two physical lines.
        body = (
            "Eu não pretendo participar da colação.\n\n"
            "Em qui., 9 de abr. de 2026 às 09:01, Secretaria do Curso <\n"
            "design@ufpr.br> escreveu:\n\n"
            "> Prezados, assinem a ATA."
        )
        s = split_reply_and_quoted(body)
        assert s.new_reply == "Eu não pretendo participar da colação."
        assert "escreveu:" in s.quoted_history
        assert "> Prezados" in s.quoted_history
        assert s.has_history is True

    def test_gmail_en_on_wrote(self):
        body = (
            "Thanks for the update.\n\n"
            "On Thu, Apr 9, 2026 at 8:44 AM, Registrar <x@y.edu> wrote:\n"
            "> Please sign the attached document."
        )
        s = split_reply_and_quoted(body)
        assert s.new_reply == "Thanks for the update."
        assert "wrote:" in s.quoted_history

    def test_rfc_quoted_only_no_attribution(self):
        body = (
            "Perfeito, muito obrigado!\n\n> Segue anexo o documento solicitado.\n> Atenciosamente,"
        )
        s = split_reply_and_quoted(body)
        assert s.new_reply == "Perfeito, muito obrigado!"
        assert "> Segue anexo" in s.quoted_history

    def test_outlook_original_message_marker(self):
        body = (
            "Reencaminho para análise.\n\n"
            "-----Mensagem Original-----\n"
            "De: aluno@ufpr.br\n"
            "Para: secretaria@ufpr.br\n"
            "Corpo do histórico."
        )
        s = split_reply_and_quoted(body)
        assert s.new_reply == "Reencaminho para análise."
        assert "Mensagem Original" in s.quoted_history

    def test_entirely_quoted_body(self):
        # Edge case: whole body is quoted (forwarded email with no new text)
        body = "> Nada do aluno, só o original.\n> Segunda linha citada."
        s = split_reply_and_quoted(body)
        assert s.new_reply == ""
        assert "> Nada do aluno" in s.quoted_history

    def test_stripped_trailing_whitespace(self):
        body = "Mensagem nova.   \n\n\n\n\nEm ter. a@b.com escreveu:\n> antigo"
        s = split_reply_and_quoted(body)
        assert s.new_reply == "Mensagem nova."


class TestFormatForPrompt:
    def test_no_history_returns_reply_only(self):
        split = SplitBody(new_reply="Olá!", quoted_history="")
        assert format_for_prompt(split) == "Olá!"

    def test_with_history_includes_both_sections(self):
        split = SplitBody(
            new_reply="Pergunta nova",
            quoted_history="> Resposta antiga",
        )
        out = format_for_prompt(split)
        assert "NOVA MENSAGEM DO REMETENTE" in out
        assert "HISTÓRICO" in out
        assert "Pergunta nova" in out
        assert "> Resposta antiga" in out

    def test_history_truncation(self):
        long_history = "x" * 10_000
        split = SplitBody(new_reply="ok", quoted_history=long_history)
        out = format_for_prompt(split, max_history_chars=500)
        assert "[... histórico truncado ...]" in out
        # The truncated chunk plus the surrounding prompt text is bounded
        assert len(out) < 2000

    def test_empty_new_reply_with_history(self):
        split = SplitBody(new_reply="", quoted_history="> histórico")
        out = format_for_prompt(split)
        assert "(mensagem vazia" in out
        assert "> histórico" in out
