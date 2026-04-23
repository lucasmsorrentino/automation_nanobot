"""Regression tests for ``normalize_signature_block`` and save_draft cleanup.

Context: MiniMax-M2 routinely hallucinated sectors like "Núcleo de Estágios"
and drifted the signature wording between runs (observed 2026-04-23). The
post-processor in ``gmail/client.py`` forces the canonical
``settings.ASSINATURA_EMAIL`` regardless of what the LLM produced.

Additionally, ``save_draft`` now deletes previous drafts in the same Gmail
thread before appending the new one — prevents review-UI clutter.
"""

from __future__ import annotations

from ufpr_automation.gmail.client import normalize_signature_block


CANONICAL = (
    "Att,\n"
    "Lucas Martins Sorrentino\n"
    "_______________________________________________________\n"
    "Secretaria da Coordenação de Design Gráfico\n"
    "Setor de Artes Comunicação e Design / UFPR\n"
    "design.grafico@ufpr.br\n"
    "https://sacod.ufpr.br/coordesign/\n"
    "41 | 3360.5360"
)


class TestNormalizeSignatureBlock:
    def test_replaces_hallucinated_nucleo_de_estagios(self):
        """The concrete bug that surfaced in the 2026-04-23 Paloma run."""
        body = (
            "Prezada Paloma,\n\n"
            "Recebemos os documentos encaminhados:\n\n"
            "1. Relatório parcial de atividades de estágio\n"
            "2. Termo aditivo de prorrogação do estágio por 6 meses\n\n"
            "Os documentos serão analisados e arquivados conforme procedimentos internos.\n\n"
            "Permanecemos à disposição para eventuais dúvidas.\n\n"
            "Atenciosamente,\n"
            "Núcleo de Estágios\n"
            "UFPR\n"
        )
        out = normalize_signature_block(body, CANONICAL)
        assert "Núcleo de Estágios" not in out
        assert "Lucas Martins Sorrentino" in out
        assert "design.grafico@ufpr.br" in out
        # Pre-signature content preserved.
        assert "Prezada Paloma," in out
        assert "Termo aditivo" in out

    def test_replaces_inconsistent_sector_naming(self):
        """Drift observed: 'Secretaria do Curso de Design Gráfico' is not the
        canonical name; the real persona is 'Secretaria da Coordenação de
        Design Gráfico'. The replacement fixes the tail regardless."""
        body = (
            "Prezado Professor,\n\n"
            "Confirmamos o recebimento do seu voto.\n\n"
            "Atenciosamente,\n"
            "Secretaria do Curso de Design Gráfico\n"
            "Setor de Artes, Comunicação e Design (SACOD) / UFPR\n"
        )
        out = normalize_signature_block(body, CANONICAL)
        assert "Secretaria da Coordenação de Design Gráfico" in out
        # The old sector string should not survive.
        assert out.count("Secretaria do Curso de Design Gráfico") == 0

    def test_handles_att_alias(self):
        body = "Olá,\n\nCorpo.\n\nAtt,\nFulano\nSetor Fake\n"
        out = normalize_signature_block(body, CANONICAL)
        assert "Setor Fake" not in out
        assert "Lucas Martins Sorrentino" in out

    def test_handles_cordialmente_alias(self):
        body = "Boa tarde,\n\nCorpo.\n\nCordialmente,\nFulano\nSetor X\n"
        out = normalize_signature_block(body, CANONICAL)
        assert "Setor X" not in out
        assert CANONICAL.rstrip() in out

    def test_body_without_signoff_appends_canonical(self):
        body = "Prezada,\n\nEnviamos os documentos em anexo.\n\n"
        out = normalize_signature_block(body, CANONICAL)
        # Body preserved verbatim, canonical appended.
        assert "Prezada," in out
        assert "Enviamos os documentos em anexo." in out
        assert out.rstrip().endswith("41 | 3360.5360")

    def test_empty_canonical_is_passthrough(self):
        body = "Algum corpo\n\nAtt,\nQualquer coisa\n"
        out = normalize_signature_block(body, "")
        assert out == body

    def test_idempotent(self):
        """Calling twice is a no-op — the second call shouldn't strip the
        canonical signature it just appended."""
        body = "Prezada Paloma,\n\nCorpo.\n\nAtenciosamente,\nNúcleo de Estágios\nUFPR\n"
        first = normalize_signature_block(body, CANONICAL)
        second = normalize_signature_block(first, CANONICAL)
        # Same canonical signature present; no duplicated sign-off line.
        assert second.count("Lucas Martins Sorrentino") == 1
        assert "Núcleo de Estágios" not in second

    def test_middle_text_mentioning_atenciosamente_not_cut(self):
        """The regex only matches 'Atenciosamente' as an entire line, so
        mentions inside paragraphs shouldn't trigger truncation."""
        body = (
            "Prezado,\n\n"
            "Informamos que atenciosamente a equipe revisará o pedido.\n\n"
            "Pedimos paciência.\n\n"
            "Atenciosamente,\n"
            "Bogus Signer\n"
        )
        out = normalize_signature_block(body, CANONICAL)
        assert "atenciosamente a equipe revisará" in out  # body preserved
        assert "Bogus Signer" not in out
        assert "Lucas Martins Sorrentino" in out

    def test_case_insensitive_signoff(self):
        body = "Olá,\n\nCorpo.\n\nATENCIOSAMENTE,\nInventado\nSetor Fake\n"
        out = normalize_signature_block(body, CANONICAL)
        assert "Inventado" not in out
        assert "Setor Fake" not in out
