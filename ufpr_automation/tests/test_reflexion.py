"""Tests for feedback/reflexion.py — Reflexion episodic memory.

All vector store (LanceDB) and embedding model (sentence-transformers)
dependencies are mocked so tests run offline and fast.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ufpr_automation.core.models import EmailClassification

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def original_cls():
    return EmailClassification(
        categoria="Outros",
        resumo="Classificacao incorreta",
        acao_necessaria="Ignorar",
        sugestao_resposta="",
    )


@pytest.fixture
def corrected_cls():
    return EmailClassification(
        categoria="Estágios",
        resumo="Solicitacao de estagio",
        acao_necessaria="Redigir Resposta",
        sugestao_resposta="Prezado, recebemos sua solicitacao...",
    )


def _mock_completion(text: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def _make_memory(tmp_path, *, table_exists=False):
    """Create a ReflexionMemory with mocked internals (no real LanceDB/model)."""
    from ufpr_automation.feedback.reflexion import ReflexionMemory

    mem = ReflexionMemory()
    mem._db = MagicMock()
    mem._model = MagicMock()
    mem._model.encode.return_value = MagicMock(tolist=lambda: [0.1] * 10)

    if table_exists:
        mem._table = MagicMock()
    else:
        mem._table = None
        mem._db.create_table.return_value = MagicMock()

    return mem


# ===========================================================================
# generate_reflection
# ===========================================================================


class TestGenerateReflection:
    def test_generates_via_llm(self, original_cls, corrected_cls):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        expected = "A categoria deveria ser Estagios, nao Outros."

        with patch("ufpr_automation.feedback.reflexion.settings") as mock_settings:
            mock_settings.LLM_MODEL = "test-model"

            with patch("litellm.completion", return_value=_mock_completion(expected)):
                mem = ReflexionMemory()
                result = mem.generate_reflection(
                    "Solicitacao de Estagio",
                    "Corpo do email sobre estagio",
                    original_cls,
                    corrected_cls,
                )

        assert result == expected

    def test_fallback_when_llm_fails_category_diff(self, original_cls, corrected_cls):
        """When LLM fails and categories differ, fallback describes the category error."""
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        with patch("ufpr_automation.feedback.reflexion.settings") as mock_settings:
            mock_settings.LLM_MODEL = "test-model"

            with patch("litellm.completion", side_effect=RuntimeError("API down")):
                mem = ReflexionMemory()
                result = mem.generate_reflection(
                    "Solicitacao de Estagio",
                    "Corpo",
                    original_cls,
                    corrected_cls,
                )

        assert "Outros" in result
        assert "Estágios" in result

    def test_fallback_action_diff(self):
        """When LLM fails and actions differ, fallback describes the action error."""
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        orig = EmailClassification(
            categoria="Estágios",
            resumo="r",
            acao_necessaria="Arquivar",
            sugestao_resposta="",
        )
        corr = EmailClassification(
            categoria="Estágios",
            resumo="r",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Prezado...",
        )

        with patch("ufpr_automation.feedback.reflexion.settings") as mock_settings:
            mock_settings.LLM_MODEL = "test-model"

            with patch("litellm.completion", side_effect=RuntimeError("fail")):
                mem = ReflexionMemory()
                result = mem.generate_reflection("Subj", "Body", orig, corr)

        assert "Arquivar" in result
        assert "Redigir Resposta" in result

    def test_fallback_no_diff(self):
        """When only sugestao_resposta differs, fallback returns generic text."""
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        orig = EmailClassification(
            categoria="Estágios",
            resumo="r",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Resp original",
        )
        corr = EmailClassification(
            categoria="Estágios",
            resumo="r",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Resp corrigida",
        )

        with patch("ufpr_automation.feedback.reflexion.settings") as mock_settings:
            mock_settings.LLM_MODEL = "test-model"

            with patch("litellm.completion", side_effect=RuntimeError("fail")):
                mem = ReflexionMemory()
                result = mem.generate_reflection("Subj", "Body", orig, corr)

        assert "corrigida pelo revisor" in result.lower()


# ===========================================================================
# add_reflection
# ===========================================================================


class TestAddReflection:
    def test_saves_to_jsonl_and_creates_table(self, tmp_path, original_cls, corrected_cls):
        mem = _make_memory(tmp_path, table_exists=False)

        with (
            patch("ufpr_automation.feedback.reflexion.REFLEXION_DIR", tmp_path),
            patch(
                "ufpr_automation.feedback.reflexion.REFLEXION_FILE",
                tmp_path / "reflexions.jsonl",
            ),
        ):
            text = mem.add_reflection(
                "Estagio",
                "Corpo do email",
                original_cls,
                corrected_cls,
                reflection_text="Pre-generated reflection",
            )

        assert text == "Pre-generated reflection"
        # Check JSONL written
        jsonl = tmp_path / "reflexions.jsonl"
        assert jsonl.exists()
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert record["email_subject"] == "Estagio"
        assert record["original_categoria"] == "Outros"
        assert record["corrected_categoria"] == "Estágios"
        # Should create table since none existed
        mem._db.create_table.assert_called_once()

    def test_generates_reflection_when_not_provided(self, tmp_path, original_cls, corrected_cls):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        mem = _make_memory(tmp_path, table_exists=False)

        with (
            patch("ufpr_automation.feedback.reflexion.REFLEXION_DIR", tmp_path),
            patch(
                "ufpr_automation.feedback.reflexion.REFLEXION_FILE",
                tmp_path / "reflexions.jsonl",
            ),
            patch.object(
                ReflexionMemory,
                "generate_reflection",
                return_value="Auto-generated reflection",
            ),
        ):
            text = mem.add_reflection("Estagio", "Corpo", original_cls, corrected_cls)

        assert text == "Auto-generated reflection"

    def test_appends_to_existing_table(self, tmp_path, original_cls, corrected_cls):
        mem = _make_memory(tmp_path, table_exists=True)

        with (
            patch("ufpr_automation.feedback.reflexion.REFLEXION_DIR", tmp_path),
            patch(
                "ufpr_automation.feedback.reflexion.REFLEXION_FILE",
                tmp_path / "reflexions.jsonl",
            ),
        ):
            mem.add_reflection(
                "Estagio",
                "Corpo",
                original_cls,
                corrected_cls,
                reflection_text="reflection",
            )

        # Should call add() on existing table, not create_table()
        mem._table.add.assert_called_once()
        mem._db.create_table.assert_not_called()


# ===========================================================================
# retrieve + retrieve_formatted
# ===========================================================================


class TestRetrieve:
    def test_returns_empty_when_no_table(self, tmp_path):
        mem = _make_memory(tmp_path, table_exists=False)
        results = mem.retrieve("estagio obrigatorio")
        assert results == []

    def test_returns_results_from_vector_search(self, tmp_path):
        import pyarrow as pa

        arrow_tbl = pa.table(
            {
                "text": ["Erro: classificou como Outros, era Estagios"],
                "_distance": pa.array([0.12], type=pa.float32()),
                "original_categoria": ["Outros"],
                "corrected_categoria": ["Estágios"],
                "email_subject": ["Solicitacao de Estagio"],
            }
        )

        mem = _make_memory(tmp_path, table_exists=True)
        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.to_arrow.return_value = arrow_tbl
        mem._table.search.return_value = mock_search

        results = mem.retrieve("estagio", top_k=3)

        assert len(results) == 1
        assert results[0]["text"] == "Erro: classificou como Outros, era Estagios"
        assert results[0]["score"] == pytest.approx(0.12, abs=0.01)
        assert results[0]["original_categoria"] == "Outros"
        assert results[0]["corrected_categoria"] == "Estágios"

    def test_retrieve_formatted_returns_header(self):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        with patch.object(
            ReflexionMemory,
            "retrieve",
            return_value=[
                {
                    "text": "Reflexao sobre erro",
                    "score": 0.1,
                    "original_categoria": "Outros",
                    "corrected_categoria": "Estágios",
                    "email_subject": "Estagio",
                }
            ],
        ):
            mem = ReflexionMemory()
            output = mem.retrieve_formatted("query")

        assert "ERROS ANTERIORES" in output
        assert "[1]" in output
        assert "Outros" in output
        assert "Estágios" in output

    def test_retrieve_formatted_empty(self):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        with patch.object(ReflexionMemory, "retrieve", return_value=[]):
            mem = ReflexionMemory()
            output = mem.retrieve_formatted("query")

        assert output == ""

    def test_retrieve_formatted_multiple(self):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        items = [
            {
                "text": f"Reflexao {i}",
                "score": 0.1 * i,
                "original_categoria": "Outros",
                "corrected_categoria": "Estágios",
                "email_subject": f"Subj {i}",
            }
            for i in range(1, 4)
        ]

        with patch.object(ReflexionMemory, "retrieve", return_value=items):
            mem = ReflexionMemory()
            output = mem.retrieve_formatted("query")

        assert "[1]" in output
        assert "[2]" in output
        assert "[3]" in output


# ===========================================================================
# count
# ===========================================================================


class TestCount:
    def test_count_zero_when_no_file(self, tmp_path):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        with patch(
            "ufpr_automation.feedback.reflexion.REFLEXION_FILE",
            tmp_path / "nonexistent.jsonl",
        ):
            mem = ReflexionMemory()
            assert mem.count() == 0

    def test_count_matches_lines(self, tmp_path):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        jsonl = tmp_path / "reflexions.jsonl"
        jsonl.write_text(
            '{"timestamp":"2026-01-01","reflection":"r1"}\n'
            '{"timestamp":"2026-01-02","reflection":"r2"}\n',
            encoding="utf-8",
        )

        with patch("ufpr_automation.feedback.reflexion.REFLEXION_FILE", jsonl):
            mem = ReflexionMemory()
            assert mem.count() == 2

    def test_count_skips_blank_lines(self, tmp_path):
        from ufpr_automation.feedback.reflexion import ReflexionMemory

        jsonl = tmp_path / "reflexions.jsonl"
        jsonl.write_text(
            '{"a":1}\n\n{"b":2}\n  \n',
            encoding="utf-8",
        )

        with patch("ufpr_automation.feedback.reflexion.REFLEXION_FILE", jsonl):
            mem = ReflexionMemory()
            assert mem.count() == 2
