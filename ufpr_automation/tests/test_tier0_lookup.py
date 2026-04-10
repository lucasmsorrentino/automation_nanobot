"""Tests for the tier0_lookup graph node + Tier 1 short-circuiting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.graph.nodes import classificar, rag_retrieve, tier0_lookup
from ufpr_automation.procedures.playbook import Playbook

SAMPLE_PROCEDURES_MD = """\
# Test playbook

```intent
intent_name: faq_prorrogar
keywords:
  - "prorrogar meu estágio"
  - "renovar estágio"
categoria: "Estágios"
action: "Redigir Resposta"
required_fields:
  - nome_aluno
sources: ["Resolução 46/10-CEPE"]
last_update: "2026-01-15"
confidence: 0.95
template: |
  Prezado(a) [NOME_ALUNO],

  Sim, é possível prorrogar via Termo Aditivo.

  Atenciosamente.
```

```intent
intent_name: needs_tce_number
keywords:
  - "encaminho TCE"
categoria: "Estágios"
action: "Redigir Resposta"
required_fields:
  - nome_aluno
  - numero_tce
sources: []
last_update: "2026-01-15"
confidence: 0.90
template: |
  Recebido TCE [NUMERO_TCE] do(a) [NOME_ALUNO].
```
"""


@pytest.fixture
def fake_playbook(tmp_path: Path) -> Playbook:
    p = tmp_path / "PROCEDURES.md"
    p.write_text(SAMPLE_PROCEDURES_MD, encoding="utf-8")
    return Playbook(path=p)


@pytest.fixture
def patch_get_playbook(fake_playbook):
    """Replace the module-level singleton with our fake one.

    By default the fixture forces ``is_stale`` to return False so the
    real RAG store mtime cannot make tests flaky. Tests that exercise
    staleness override ``is_stale`` themselves.
    """
    fake_playbook.is_stale = lambda intent, **kw: False  # type: ignore
    with patch(
        "ufpr_automation.procedures.playbook.get_playbook", return_value=fake_playbook
    ):
        yield fake_playbook


def _make_email(sender: str, subject: str, body: str = "") -> EmailData:
    e = EmailData(sender=sender, subject=subject, body=body or subject)
    e.compute_stable_id()
    return e


# ---------------------------------------------------------------------------
# tier0_lookup
# ---------------------------------------------------------------------------


class TestTier0Lookup:
    def test_keyword_hit_creates_classification(self, patch_get_playbook):
        emails = [
            _make_email(
                "Ana Souza <ana@ufpr.br>",
                "Quero prorrogar meu estágio na empresa X",
            )
        ]
        result = tier0_lookup({"emails": emails})

        assert len(result["tier0_hits"]) == 1
        assert emails[0].stable_id in result["tier0_hits"]

        cls = result["classifications"][emails[0].stable_id]
        assert isinstance(cls, EmailClassification)
        assert cls.categoria == "Estágios"
        assert "Ana Souza" in cls.sugestao_resposta
        assert cls.confianca == 0.95
        assert "Tier 0" in cls.resumo

    def test_no_emails_returns_empty(self, patch_get_playbook):
        result = tier0_lookup({"emails": []})
        assert result == {"tier0_hits": [], "classifications": {}}

    def test_miss_returns_no_classification(self, patch_get_playbook):
        # Disable semantic so the test stays fast and deterministic
        patch_get_playbook._ensure_embeddings = lambda: False  # type: ignore
        emails = [_make_email("x@y.z", "Aleatório sobre futebol")]
        result = tier0_lookup({"emails": emails})
        assert result["tier0_hits"] == []
        assert result["classifications"] == {}

    def test_required_field_missing_falls_back(self, patch_get_playbook):
        # "encaminho TCE" matches needs_tce_number but no TCE number in body
        emails = [_make_email("Ana <ana@ufpr.br>", "encaminho TCE", "sem número")]
        result = tier0_lookup({"emails": emails})
        # nome_aluno extractable but numero_tce required and absent → fallback
        assert result["tier0_hits"] == []
        assert result["classifications"] == {}

    def test_required_field_present_succeeds(self, patch_get_playbook):
        emails = [
            _make_email(
                "Ana <ana@ufpr.br>",
                "encaminho TCE 4567",
                "TCE 4567 anexo",
            )
        ]
        result = tier0_lookup({"emails": emails})
        assert len(result["tier0_hits"]) == 1
        cls = result["classifications"][emails[0].stable_id]
        assert "4567" in cls.sugestao_resposta
        assert "Ana" in cls.sugestao_resposta

    def test_stale_intent_falls_back(self, patch_get_playbook):
        # Force is_stale to always return True
        patch_get_playbook.is_stale = lambda intent, **kw: True  # type: ignore
        emails = [
            _make_email("Ana <ana@ufpr.br>", "Quero prorrogar meu estágio")
        ]
        result = tier0_lookup({"emails": emails})
        assert result["tier0_hits"] == []
        assert result["classifications"] == {}

    def test_mixed_hit_and_miss(self, patch_get_playbook):
        patch_get_playbook._ensure_embeddings = lambda: False  # type: ignore
        emails = [
            _make_email("Ana <ana@ufpr.br>", "prorrogar meu estágio"),  # hit
            _make_email("X <x@y.z>", "promoção"),                        # miss
        ]
        result = tier0_lookup({"emails": emails})
        assert len(result["tier0_hits"]) == 1
        assert emails[0].stable_id in result["tier0_hits"]
        assert emails[1].stable_id not in result["tier0_hits"]


# ---------------------------------------------------------------------------
# rag_retrieve / classificar short-circuit on Tier 0 hits
# ---------------------------------------------------------------------------


class TestTier1ShortCircuit:
    def test_rag_retrieve_skips_all_tier0(self, patch_get_playbook):
        emails = [
            _make_email("Ana <ana@ufpr.br>", "prorrogar meu estágio"),
            _make_email("Bia <bia@ufpr.br>", "renovar estágio"),
        ]
        # Pretend tier0 caught both
        state = {
            "emails": emails,
            "tier0_hits": [e.stable_id for e in emails],
        }
        result = rag_retrieve(state)
        # Empty contexts because every email was already handled
        assert result["rag_contexts"] == {}

    def test_classificar_skips_tier0_and_preserves_them(self, patch_get_playbook):
        e1 = _make_email("Ana <ana@ufpr.br>", "prorrogar")
        cls1 = EmailClassification(
            categoria="Estágios",
            resumo="Tier 0",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="ok",
            confianca=0.95,
        )
        state = {
            "emails": [e1],
            "classifications": {e1.stable_id: cls1},
            "tier0_hits": [e1.stable_id],
        }
        # Should NOT call any LLM and should return the existing classification
        result = classificar(state)
        assert result["classifications"] == {e1.stable_id: cls1}

    def test_classificar_merges_tier0_with_tier1(self, patch_get_playbook):
        e1 = _make_email("Ana <ana@ufpr.br>", "prorrogar")
        e2 = _make_email("Bia <bia@ufpr.br>", "alguma coisa nova")
        cls1 = EmailClassification(
            categoria="Estágios",
            resumo="Tier 0",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="ok",
            confianca=0.95,
        )
        cls2 = EmailClassification(
            categoria="Outros",
            resumo="Tier 1 LLM result",
            acao_necessaria="Revisão Manual",
            sugestao_resposta="",
            confianca=0.6,
        )

        state = {
            "emails": [e1, e2],
            "classifications": {e1.stable_id: cls1},
            "rag_contexts": {},
        }

        # Stub the inner LLM helpers so we don't call any model
        with patch(
            "ufpr_automation.graph.nodes._classify_with_dspy",
            return_value={e2.stable_id: cls2},
        ):
            result = classificar(state)

        assert result["classifications"][e1.stable_id] is cls1  # preserved
        assert result["classifications"][e2.stable_id] is cls2  # added
