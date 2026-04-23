"""Regression tests for the ``consultar_tier0_sei_siga`` node.

Bug background: when Tier 0 resolves an email with ``sei_action != "none"``
the pipeline previously skipped the Fleet — so
:func:`_consult_sei_for_email` and :func:`_consult_siga_for_email` (which
live inside the Fleet sub-agent) never ran, leaving ``sei_contexts`` and
``siga_contexts`` empty. ``agir_estagios``' checkers would then fall into
defensive soft-blocks and the student got a nonsense draft.

This node fills the gap by calling the same per-email consult helpers for
Tier 0 hits whose intent declares a non-trivial ``sei_action``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.graph.nodes import consultar_tier0_sei_siga


def _email(sid: str, subject: str = "Termo aditivo") -> EmailData:
    e = EmailData(sender="aluna@ufpr.br", subject=subject, body="corpo")
    e.stable_id = sid
    return e


def _estagios_cls() -> EmailClassification:
    return EmailClassification(
        categoria="Estágios",
        resumo="r",
        acao_necessaria="Redigir Resposta",
        sugestao_resposta="d",
        confianca=0.9,
    )


def _non_estagios_cls() -> EmailClassification:
    return EmailClassification(
        categoria="Outros",
        resumo="r",
        acao_necessaria="Revisão Manual",
        sugestao_resposta="d",
        confianca=0.5,
    )


class _FakeIntent:
    def __init__(self, sei_action: str):
        self.sei_action = sei_action
        self.intent_name = "fake"


class _FakeMatch:
    def __init__(self, sei_action: str):
        self.intent = _FakeIntent(sei_action)
        self.method = "keyword"
        self.score = 1.0


class _FakePlaybook:
    """Playbook stub that returns a fixed sei_action regardless of input."""

    def __init__(self, sei_action: str | None):
        self._action = sei_action

    def lookup(self, _text: str):
        if self._action is None:
            return None
        return _FakeMatch(self._action)


class TestConsultarTier0SeiSiga:
    def test_no_tier0_hits_is_noop(self):
        state = {"tier0_hits": [], "emails": [], "classifications": {}}
        result = consultar_tier0_sei_siga(state)
        assert result == {}

    def test_calls_consult_for_eligible_tier0_hits(self):
        """Intent with ``sei_action='append_to_existing'`` triggers both
        SEI and SIGA consultation and merges results into state."""
        email = _email("e1", "Termo aditivo de prorrogação")
        cls = _estagios_cls()
        state = {
            "tier0_hits": ["e1"],
            "emails": [email],
            "classifications": {"e1": cls},
        }

        with (
            patch(
                "ufpr_automation.procedures.playbook.get_playbook",
                return_value=_FakePlaybook("append_to_existing"),
            ),
            patch(
                "ufpr_automation.graph.nodes._consult_sei_for_email",
                return_value={"mode": "grr", "processo_id": "23075.123/2026-78"},
            ) as sei_mock,
            patch(
                "ufpr_automation.graph.nodes._consult_siga_for_email",
                return_value={"matricula_ativa": True},
            ) as siga_mock,
        ):
            result = consultar_tier0_sei_siga(state)

        sei_mock.assert_called_once_with(email, cls)
        siga_mock.assert_called_once_with(email, cls)
        assert result["sei_contexts"] == {
            "e1": {"mode": "grr", "processo_id": "23075.123/2026-78"}
        }
        assert result["siga_contexts"] == {"e1": {"matricula_ativa": True}}

    def test_skips_tier0_hit_with_sei_action_none(self):
        email = _email("e1", "convocação colegiado")
        cls = _estagios_cls()
        state = {
            "tier0_hits": ["e1"],
            "emails": [email],
            "classifications": {"e1": cls},
        }
        with (
            patch(
                "ufpr_automation.procedures.playbook.get_playbook",
                return_value=_FakePlaybook("none"),
            ),
            patch("ufpr_automation.graph.nodes._consult_sei_for_email") as sei_mock,
            patch("ufpr_automation.graph.nodes._consult_siga_for_email") as siga_mock,
        ):
            result = consultar_tier0_sei_siga(state)

        sei_mock.assert_not_called()
        siga_mock.assert_not_called()
        assert result["sei_contexts"] == {}
        assert result["siga_contexts"] == {}

    def test_skips_non_estagios_tier0_hits(self):
        email = _email("e1")
        cls = _non_estagios_cls()
        state = {
            "tier0_hits": ["e1"],
            "emails": [email],
            "classifications": {"e1": cls},
        }
        with (
            patch(
                "ufpr_automation.procedures.playbook.get_playbook",
                return_value=_FakePlaybook("append_to_existing"),
            ),
            patch("ufpr_automation.graph.nodes._consult_sei_for_email") as sei_mock,
            patch("ufpr_automation.graph.nodes._consult_siga_for_email") as siga_mock,
        ):
            consultar_tier0_sei_siga(state)

        sei_mock.assert_not_called()
        siga_mock.assert_not_called()

    def test_sei_consult_failure_does_not_block_siga(self):
        """Per-email isolation: SEI exception does not prevent SIGA."""
        email = _email("e1")
        cls = _estagios_cls()
        state = {
            "tier0_hits": ["e1"],
            "emails": [email],
            "classifications": {"e1": cls},
        }
        with (
            patch(
                "ufpr_automation.procedures.playbook.get_playbook",
                return_value=_FakePlaybook("create_process"),
            ),
            patch(
                "ufpr_automation.graph.nodes._consult_sei_for_email",
                side_effect=RuntimeError("sei down"),
            ),
            patch(
                "ufpr_automation.graph.nodes._consult_siga_for_email",
                return_value={"matricula_ativa": True},
            ),
        ):
            result = consultar_tier0_sei_siga(state)

        assert "e1" not in result["sei_contexts"]
        assert result["siga_contexts"] == {"e1": {"matricula_ativa": True}}

    def test_consult_returning_none_does_not_populate(self):
        email = _email("e1")
        cls = _estagios_cls()
        state = {
            "tier0_hits": ["e1"],
            "emails": [email],
            "classifications": {"e1": cls},
        }
        with (
            patch(
                "ufpr_automation.procedures.playbook.get_playbook",
                return_value=_FakePlaybook("append_to_existing"),
            ),
            patch(
                "ufpr_automation.graph.nodes._consult_sei_for_email",
                return_value=None,
            ),
            patch(
                "ufpr_automation.graph.nodes._consult_siga_for_email",
                return_value=None,
            ),
        ):
            result = consultar_tier0_sei_siga(state)

        assert result["sei_contexts"] == {}
        assert result["siga_contexts"] == {}

    def test_graph_wires_node_before_fleet_dispatch(self):
        """Integration smoke: the compiled graph has the node between
        prewarm_sessions and the Fleet conditional."""
        from ufpr_automation.graph.builder import build_graph

        graph = build_graph(channel="gmail")
        node_names = set(graph.get_graph().nodes.keys())
        assert "consultar_tier0_sei_siga" in node_names
