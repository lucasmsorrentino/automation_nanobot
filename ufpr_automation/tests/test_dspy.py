"""Tests for dspy_modules/ — Signatures, Modules, and Metrics.

DSPy LM calls are mocked so tests run offline. The dspy package itself
must be installed (pip install dspy) for these tests to run.
"""

from __future__ import annotations

import importlib
import json as _json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Skip entire module if dspy is not installed
dspy = pytest.importorskip("dspy")

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.dspy_modules.metrics import (
    VALID_CATEGORIES,
    category_match,
    category_valid,
    composite_metric,
    confidence_reasonable,
    formal_tone,
    response_not_empty,
)
from ufpr_automation.dspy_modules.modules import (
    EmailClassifierModule,
    SelfRefineModule,
    prediction_to_classification,
)
from ufpr_automation.dspy_modules.signatures import (
    DraftCritic,
    DraftRefiner,
    EmailClassifier,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pred(**kwargs) -> dspy.Prediction:
    """Create a dspy.Prediction with the given fields."""
    return dspy.Prediction(**kwargs)


def _default_pred(**overrides) -> dspy.Prediction:
    defaults = {
        "categoria": "Estágios",
        "resumo": "Solicitacao de estagio obrigatorio.",
        "acao_necessaria": "Redigir Resposta",
        "sugestao_resposta": "Prezado(a), informamos que recebemos sua solicitacao.",
        "confianca": 0.92,
    }
    defaults.update(overrides)
    return _pred(**defaults)


# ===========================================================================
# Signatures — structure validation
# ===========================================================================


class TestSignatures:
    def test_email_classifier_has_expected_fields(self):
        fields = EmailClassifier.model_fields
        input_names = {k for k, v in fields.items() if v.json_schema_extra and v.json_schema_extra.get("__dspy_field_type") == "input"}
        output_names = {k for k, v in fields.items() if v.json_schema_extra and v.json_schema_extra.get("__dspy_field_type") == "output"}

        # At minimum these should exist as fields
        for name in ("email_subject", "email_body", "email_sender", "rag_context"):
            assert name in fields, f"Missing input field: {name}"
        for name in ("categoria", "resumo", "acao_necessaria", "sugestao_resposta", "confianca"):
            assert name in fields, f"Missing output field: {name}"

    def test_draft_critic_has_expected_fields(self):
        fields = DraftCritic.model_fields
        for name in ("email_subject", "email_body", "draft_response", "categoria", "rag_context"):
            assert name in fields
        for name in ("has_issues", "critique"):
            assert name in fields

    def test_draft_refiner_has_expected_fields(self):
        fields = DraftRefiner.model_fields
        for name in ("email_subject", "email_body", "original_draft", "critique", "rag_context"):
            assert name in fields
        for name in ("categoria", "resumo", "acao_necessaria", "sugestao_resposta", "confianca"):
            assert name in fields


# ===========================================================================
# prediction_to_classification
# ===========================================================================


class TestPredictionToClassification:
    def test_basic_conversion(self):
        pred = _default_pred()
        cls = prediction_to_classification(pred)

        assert isinstance(cls, EmailClassification)
        assert cls.categoria == "Estágios"
        assert cls.confianca == pytest.approx(0.92)

    def test_string_confianca_converted(self):
        pred = _default_pred(confianca="0.85")
        cls = prediction_to_classification(pred)
        assert cls.confianca == pytest.approx(0.85)

    def test_invalid_confianca_defaults_to_half(self):
        pred = _default_pred(confianca="not-a-number")
        cls = prediction_to_classification(pred)
        assert cls.confianca == pytest.approx(0.5)

    def test_confianca_clamped_high(self):
        pred = _default_pred(confianca=1.5)
        cls = prediction_to_classification(pred)
        assert cls.confianca == 1.0

    def test_confianca_clamped_low(self):
        pred = _default_pred(confianca=-0.3)
        cls = prediction_to_classification(pred)
        assert cls.confianca == 0.0

    def test_preserves_all_fields(self):
        pred = _default_pred(
            categoria="Outros",
            resumo="Um oficio",
            acao_necessaria="Encaminhar para Secretaria",
            sugestao_resposta="Prezado, encaminhamos...",
            confianca=0.88,
        )
        cls = prediction_to_classification(pred)
        assert cls.categoria == "Outros"
        assert cls.resumo == "Um oficio"
        assert cls.acao_necessaria == "Encaminhar para Secretaria"
        assert cls.sugestao_resposta == "Prezado, encaminhamos..."


# ===========================================================================
# Metrics — category_valid
# ===========================================================================


class TestCategoryValid:
    def test_valid_categories(self):
        example = MagicMock()
        for cat in VALID_CATEGORIES:
            pred = _default_pred(categoria=cat)
            assert category_valid(example, pred) is True

    def test_invalid_category(self):
        example = MagicMock()
        pred = _default_pred(categoria="CategoriaInvalida")
        assert category_valid(example, pred) is False


# ===========================================================================
# Metrics — category_match
# ===========================================================================


class TestCategoryMatch:
    def test_match_when_equal(self):
        example = MagicMock()
        example.expected_categoria = "Estágios"
        pred = _default_pred(categoria="Estágios")
        assert category_match(example, pred) is True

    def test_no_match_when_different(self):
        example = MagicMock()
        example.expected_categoria = "Outros"
        pred = _default_pred(categoria="Estágios")
        assert category_match(example, pred) is False

    def test_true_when_no_ground_truth(self):
        example = MagicMock(spec=[])  # no expected_categoria attribute
        pred = _default_pred()
        assert category_match(example, pred) is True


# ===========================================================================
# Metrics — response_not_empty
# ===========================================================================


class TestResponseNotEmpty:
    def test_passes_when_response_provided(self):
        example = MagicMock()
        pred = _default_pred(
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Prezado...",
        )
        assert response_not_empty(example, pred) is True

    def test_fails_when_response_empty_but_needed(self):
        example = MagicMock()
        pred = _default_pred(
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="",
        )
        assert response_not_empty(example, pred) is False

    def test_passes_when_no_response_needed(self):
        example = MagicMock()
        pred = _default_pred(
            acao_necessaria="Arquivar",
            sugestao_resposta="",
        )
        assert response_not_empty(example, pred) is True


# ===========================================================================
# Metrics — confidence_reasonable
# ===========================================================================


class TestConfidenceReasonable:
    def test_valid_float(self):
        example = MagicMock()
        assert confidence_reasonable(example, _default_pred(confianca=0.5)) is True
        assert confidence_reasonable(example, _default_pred(confianca=0.0)) is True
        assert confidence_reasonable(example, _default_pred(confianca=1.0)) is True

    def test_out_of_range(self):
        example = MagicMock()
        assert confidence_reasonable(example, _default_pred(confianca=1.5)) is False
        assert confidence_reasonable(example, _default_pred(confianca=-0.1)) is False

    def test_non_numeric(self):
        example = MagicMock()
        assert confidence_reasonable(example, _default_pred(confianca="abc")) is False


# ===========================================================================
# Metrics — formal_tone
# ===========================================================================


class TestFormalTone:
    def test_empty_response_full_score(self):
        example = MagicMock()
        pred = _default_pred(sugestao_resposta="")
        assert formal_tone(example, pred) == 1.0

    def test_formal_markers_increase_score(self):
        example = MagicMock()
        pred = _default_pred(
            sugestao_resposta="Prezado Senhor, informamos que o documento segue em anexo. Atenciosamente."
        )
        score = formal_tone(example, pred)
        assert score > 0.5

    def test_informal_text_low_score(self):
        example = MagicMock()
        pred = _default_pred(sugestao_resposta="Oi, tudo bem? Manda o arquivo ai.")
        score = formal_tone(example, pred)
        assert score == pytest.approx(0.0)


# ===========================================================================
# Metrics — composite_metric
# ===========================================================================


class TestCompositeMetric:
    def test_perfect_score(self):
        example = MagicMock()
        example.expected_categoria = "Estágios"
        pred = _default_pred(
            sugestao_resposta="Prezado Senhor, informamos que encaminhamos. Atenciosamente.",
            confianca=0.9,
        )
        score = composite_metric(example, pred)
        assert score > 0.7

    def test_wrong_category_reduces_score(self):
        example = MagicMock()
        example.expected_categoria = "Outros"
        pred = _default_pred(categoria="Estágios")  # wrong
        score = composite_metric(example, pred)
        # At most 4/5 since category_match fails
        assert score <= 0.85

    def test_invalid_category_reduces_score(self):
        example = MagicMock(spec=[])
        pred = _default_pred(categoria="Invalida")
        score = composite_metric(example, pred)
        assert score < 1.0


# ===========================================================================
# EmailClassifierModule
# ===========================================================================


class TestEmailClassifierModule:
    def test_forward_calls_predict(self):
        module = EmailClassifierModule()
        mock_predict_result = _default_pred()
        module.classify = MagicMock(return_value=mock_predict_result)

        result = module.forward(
            email_subject="Estagio",
            email_body="Corpo",
            email_sender="prof@ufpr.br",
            rag_context="",
        )

        assert result == mock_predict_result
        module.classify.assert_called_once_with(
            email_subject="Estagio",
            email_body="Corpo",
            email_sender="prof@ufpr.br",
            rag_context="",
        )


# ===========================================================================
# SelfRefineModule
# ===========================================================================


class TestSelfRefineModule:
    def test_no_issues_returns_original(self):
        module = SelfRefineModule()

        classification = _default_pred()
        critic_result = _pred(has_issues=False, critique="SEM PROBLEMAS")

        module.classify = MagicMock(return_value=classification)
        module.critique = MagicMock(return_value=critic_result)
        module.refine = MagicMock()

        result = module.forward(
            email_subject="Estagio",
            email_body="Corpo",
            email_sender="prof@ufpr.br",
        )

        assert result == classification
        module.refine.assert_not_called()

    def test_with_issues_triggers_refine(self):
        module = SelfRefineModule()

        classification = _default_pred(sugestao_resposta="Rascunho com erro")
        critic_result = _pred(has_issues=True, critique="Tom informal detectado")
        refined = _default_pred(sugestao_resposta="Prezado(a), resposta corrigida.")

        module.classify = MagicMock(return_value=classification)
        module.critique = MagicMock(return_value=critic_result)
        module.refine = MagicMock(return_value=refined)

        result = module.forward(
            email_subject="Estagio",
            email_body="Corpo",
            email_sender="prof@ufpr.br",
        )

        assert result == refined
        module.refine.assert_called_once()
        # Check refine got the critique
        call_kwargs = module.refine.call_args[1]
        assert call_kwargs["critique"] == "Tom informal detectado"
        assert call_kwargs["original_draft"] == "Rascunho com erro"

    def test_rag_context_passed_through(self):
        module = SelfRefineModule()

        classification = _default_pred()
        critic_result = _pred(has_issues=False, critique="SEM PROBLEMAS")

        module.classify = MagicMock(return_value=classification)
        module.critique = MagicMock(return_value=critic_result)

        module.forward(
            email_subject="Estagio",
            email_body="Corpo",
            email_sender="prof@ufpr.br",
            rag_context="Art. 1 ...",
        )

        # Both classify and critique should receive rag_context
        assert module.classify.call_args[1]["rag_context"] == "Art. 1 ..."
        assert module.critique.call_args[1]["rag_context"] == "Art. 1 ..."


# ===========================================================================
# classify_email_dspy (integration-style, mocked LM)
# ===========================================================================


class TestClassifyEmailDspy:
    def test_with_self_refine(self):
        from ufpr_automation.dspy_modules.modules import classify_email_dspy

        email = EmailData(
            sender="prof@ufpr.br",
            subject="Solicitacao de Estagio",
            body="Corpo do email",
        )

        mock_pred = _default_pred()

        with patch.object(SelfRefineModule, "forward", return_value=mock_pred):
            result = classify_email_dspy(email, use_self_refine=True)

        assert isinstance(result, EmailClassification)
        assert result.categoria == "Estágios"

    def test_without_self_refine(self):
        from ufpr_automation.dspy_modules.modules import classify_email_dspy

        email = EmailData(
            sender="prof@ufpr.br",
            subject="Oficio",
            body="Corpo do oficio",
        )

        mock_pred = _default_pred(categoria="Outros")

        with patch.object(EmailClassifierModule, "forward", return_value=mock_pred):
            result = classify_email_dspy(email, use_self_refine=False)

        assert result.categoria == "Outros"

    def test_uses_body_fallback_to_preview(self):
        from ufpr_automation.dspy_modules.modules import classify_email_dspy

        email = EmailData(
            sender="prof@ufpr.br",
            subject="Estagio",
            body="",
            preview="Preview text",
        )

        mock_pred = _default_pred()

        with patch.object(SelfRefineModule, "forward", return_value=mock_pred) as mock_fwd:
            classify_email_dspy(email, use_self_refine=True)

        call_kwargs = mock_fwd.call_args[1]
        assert call_kwargs["email_body"] == "Preview text"


# ===========================================================================
# USE_DSPY tri-state feature flag (WS1)
# ===========================================================================


class TestUseDspyFlag:
    """Tests for the ``USE_DSPY`` tri-state gate in graph/nodes.py.

    Each test reloads the settings and nodes modules so the fresh
    ``USE_DSPY`` env value is picked up, and monkeypatches
    ``OPTIMIZED_DIR`` on the optimize module so compiled-prompt
    presence can be simulated without touching the real package dir.
    """

    def _reload_modules(self):
        """Reload settings + nodes so USE_DSPY env is picked up fresh."""
        from ufpr_automation.config import settings as settings_mod
        from ufpr_automation.graph import nodes as nodes_mod

        importlib.reload(settings_mod)
        importlib.reload(nodes_mod)
        return settings_mod, nodes_mod

    def _point_optimized_dir(self, monkeypatch, tmp_path: Path):
        """Monkeypatch OPTIMIZED_DIR on the optimize module to tmp_path."""
        from ufpr_automation.dspy_modules import optimize as optimize_mod

        monkeypatch.setattr(optimize_mod, "OPTIMIZED_DIR", tmp_path)
        return optimize_mod

    def _write_fake_compiled(self, tmp_path: Path, name: str = "gepa_optimized.json"):
        """Write a fake compiled prompt file so _has_compiled_prompt() is True."""
        path = tmp_path / name
        path.write_text(_json.dumps({"dummy": True}), encoding="utf-8")
        return path

    def test_off_never_uses_dspy(self, monkeypatch, tmp_path):
        """USE_DSPY=off -> _should_use_dspy() returns False even if compiled file exists."""
        monkeypatch.setenv("USE_DSPY", "off")
        _, nodes_mod = self._reload_modules()
        self._point_optimized_dir(monkeypatch, tmp_path)
        # Even with a compiled file present, off must win.
        self._write_fake_compiled(tmp_path)

        assert nodes_mod._should_use_dspy() is False

    def test_on_without_compiled_raises(self, monkeypatch, tmp_path):
        """USE_DSPY=on with no compiled file -> RuntimeError."""
        monkeypatch.setenv("USE_DSPY", "on")
        _, nodes_mod = self._reload_modules()
        self._point_optimized_dir(monkeypatch, tmp_path)
        # tmp_path is empty — no compiled file.

        with pytest.raises(RuntimeError, match="no compiled prompt file"):
            nodes_mod._should_use_dspy()

    def test_auto_without_compiled_falls_back(self, monkeypatch, tmp_path, caplog):
        """USE_DSPY=auto with no compiled file -> False + info log."""
        monkeypatch.setenv("USE_DSPY", "auto")
        _, nodes_mod = self._reload_modules()
        self._point_optimized_dir(monkeypatch, tmp_path)

        with caplog.at_level(logging.INFO, logger="ufpr_automation"):
            result = nodes_mod._should_use_dspy()

        assert result is False
        # Assert the fallback log line was captured
        assert any(
            "USE_DSPY=auto but no compiled prompts yet" in record.getMessage()
            for record in caplog.records
        ), f"Expected fallback log line, got: {[r.getMessage() for r in caplog.records]}"

    def test_auto_with_compiled_uses_dspy(self, monkeypatch, tmp_path):
        """USE_DSPY=auto with compiled file present -> True."""
        monkeypatch.setenv("USE_DSPY", "auto")
        _, nodes_mod = self._reload_modules()
        self._point_optimized_dir(monkeypatch, tmp_path)
        self._write_fake_compiled(tmp_path)

        assert nodes_mod._should_use_dspy() is True

    def test_on_with_compiled_uses_dspy(self, monkeypatch, tmp_path):
        """USE_DSPY=on with compiled file present -> True (no raise)."""
        monkeypatch.setenv("USE_DSPY", "on")
        _, nodes_mod = self._reload_modules()
        self._point_optimized_dir(monkeypatch, tmp_path)
        self._write_fake_compiled(tmp_path)

        assert nodes_mod._should_use_dspy() is True
