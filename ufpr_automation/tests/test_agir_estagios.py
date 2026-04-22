"""Tests for agir_estagios node — Estágios SEI workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.graph.nodes import agir_estagios

SAMPLE_PROCEDURES_MD = """\
```intent
intent_name: tce_inicial_estagios
keywords:
  - "TCE inicial"
  - "termo de compromisso"
categoria: "Estágios"
action: "Abrir Processo SEI"
required_fields:
  - nome_aluno
last_update: "2026-04-10"
confidence: 0.92
template: "Prezado(a) [NOME_ALUNO], processo SEI [NUMERO_PROCESSO_SEI] criado."
sei_action: create_process
sei_process_type: "Graduação/Ensino Técnico: Estágios não Obrigatórios"
required_attachments:
  - TCE_assinado
blocking_checks:
  - siga_matricula_ativa
  - data_inicio_retroativa
despacho_template: |
  Ao Setor,
  Encaminha-se o TCE de [NOME_ALUNO] (GRR[GRR]) para análise.
```
"""


@pytest.fixture
def procedures_path(tmp_path: Path) -> Path:
    p = tmp_path / "PROCEDURES.md"
    p.write_text(SAMPLE_PROCEDURES_MD, encoding="utf-8")
    return p


def _make_email(subject="TCE inicial do aluno", body="Segue TCE inicial do aluno João Silva"):
    e = EmailData(
        sender="João Silva <joao@ufpr.br>",
        subject=subject,
        body=body,
    )
    e.compute_stable_id()
    return e


def _make_classification():
    return EmailClassification(
        categoria="Estágios",
        resumo="TCE inicial",
        acao_necessaria="Abrir Processo SEI",
        sugestao_resposta="",
    )


class TestAgirEstagiosHardBlock:
    def test_hard_block_drafts_refusal(self, procedures_path):
        email = _make_email()
        cls = _make_classification()

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "tier0_hits": [email.stable_id],
            "siga_contexts": {email.stable_id: {"matricula_status": "Trancada"}},
            "sei_contexts": {},
        }

        with patch("ufpr_automation.procedures.playbook.get_playbook") as mock_pb:
            from ufpr_automation.procedures.playbook import Playbook

            pb = Playbook(path=procedures_path)
            mock_pb.return_value = pb

            result = agir_estagios(state)

        ops = result["sei_operations"]
        assert len(ops) == 1
        assert ops[0]["reason"] == "hard_block"
        # Draft mentions the ajuste obrigatório and brings Lucas's signature
        # (merged hard+soft format from 2026-04-22).
        body = cls.sugestao_resposta
        assert "Ajustes obrigatórios" in body
        assert "Lucas Martins Sorrentino" in body
        # And reassures the aluno that the Secretaria handles the SEI side.
        assert "você não precisa abrir processo" in body.lower()


class TestAgirEstagiosAllPass:
    def test_all_pass_runs_sei_chain(self, procedures_path, monkeypatch):
        # Force dry_run so the test is isolated from ambient SEI_WRITE_MODE
        # in .env (a live env would cause the inner SEIWriter to attempt
        # loading sei_selectors.yaml, which isn't available on every machine).
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_MODE", "dry_run")

        email = _make_email(body="Segue TCE inicial do aluno João Silva, data início 01/06/2027")
        cls = _make_classification()

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "tier0_hits": [email.stable_id],
            "siga_contexts": {email.stable_id: {"matricula_status": "Ativa"}},
            "sei_contexts": {},
        }

        with patch("ufpr_automation.procedures.playbook.get_playbook") as mock_pb:
            from ufpr_automation.procedures.playbook import Playbook

            pb = Playbook(path=procedures_path)
            mock_pb.return_value = pb

            result = agir_estagios(state)

        ops = result["sei_operations"]
        assert len(ops) == 1
        assert ops[0]["op"] == "sei_chain"
        assert ops[0]["success"] is True
        # Should have create_process and despacho ops
        sub_ops = ops[0]["ops"]
        op_types = [o["op"] for o in sub_ops]
        assert "create_process" in op_types
        assert "despacho" in op_types


class TestAgirEstagiosSkipsNonEstagios:
    def test_skips_non_estagios_email(self, procedures_path):
        email = _make_email(subject="Trancamento de curso", body="Quero trancar o curso")
        cls = EmailClassification(
            categoria="Acadêmico / Matrícula",
            resumo="Trancamento",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Orientações...",
        )

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "tier0_hits": [email.stable_id],
            "siga_contexts": {},
            "sei_contexts": {},
        }

        with patch("ufpr_automation.procedures.playbook.get_playbook") as mock_pb:
            from ufpr_automation.procedures.playbook import Playbook

            pb = Playbook(path=procedures_path)
            mock_pb.return_value = pb

            result = agir_estagios(state)

        assert result["sei_operations"] == []


class TestAgirEstagiosNoTier0:
    def test_no_tier0_hits_returns_empty(self):
        state = {
            "emails": [],
            "classifications": {},
            "tier0_hits": [],
            "siga_contexts": {},
            "sei_contexts": {},
        }
        result = agir_estagios(state)
        assert result["sei_operations"] == []
