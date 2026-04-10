"""Tests for procedures/playbook.py — Tier 0 parser, lookup, staleness."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from ufpr_automation.core.models import EmailData
from ufpr_automation.procedures.playbook import (
    Intent,
    Playbook,
    extract_variables,
    fill_template,
    missing_required_fields,
    parse_procedures_md,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_PROCEDURES_MD = """\
# Test playbook

> A few intents for unit tests.

```intent
intent_name: faq_prorrogar_estagio
keywords:
  - "prorrogar meu estágio"
  - "renovar estágio"
  - "Termo Aditivo"
categoria: "Estágios"
action: "Redigir Resposta"
required_fields:
  - nome_aluno
sources:
  - "Resolução 46/10-CEPE"
last_update: "2026-01-15"
confidence: 0.95
template: |
  Prezado(a) [NOME_ALUNO],

  Sim, é possível prorrogar via Termo Aditivo (TCE [NUMERO_TCE]).

  {{ assinatura_email }}
```

```intent
intent_name: trancamento_curso
keywords:
  - "trancar o curso"
  - "trancamento de curso"
categoria: "Acadêmico / Matrícula"
action: "Redigir Resposta"
required_fields:
  - nome_aluno
sources: []
last_update: "2026-01-15"
confidence: 0.85
template: "Prezado(a) [NOME_ALUNO], orientações sobre trancamento..."
```

```intent
intent_name: malformed_intent
keywords: not-a-list
categoria: "Outros"
last_update: "2026-01-15"
```
"""


@pytest.fixture
def procedures_path(tmp_path: Path) -> Path:
    p = tmp_path / "PROCEDURES.md"
    p.write_text(SAMPLE_PROCEDURES_MD, encoding="utf-8")
    return p


@pytest.fixture
def playbook(procedures_path: Path) -> Playbook:
    return Playbook(path=procedures_path)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParser:
    def test_parses_valid_intents(self, procedures_path):
        intents = parse_procedures_md(procedures_path)
        names = [i.intent_name for i in intents]
        # malformed_intent should be skipped (keywords is not a list)
        assert "faq_prorrogar_estagio" in names
        assert "trancamento_curso" in names
        assert "malformed_intent" not in names

    def test_intent_fields_loaded(self, procedures_path):
        intents = parse_procedures_md(procedures_path)
        intent = next(i for i in intents if i.intent_name == "faq_prorrogar_estagio")
        assert intent.categoria == "Estágios"
        assert "prorrogar meu estágio" in intent.keywords
        assert intent.required_fields == ["nome_aluno"]
        assert intent.confidence == 0.95
        assert intent.last_update == "2026-01-15"
        assert "[NOME_ALUNO]" in intent.template

    def test_missing_file_returns_empty(self, tmp_path):
        intents = parse_procedures_md(tmp_path / "nonexistent.md")
        assert intents == []

    def test_intent_last_update_date(self):
        i = Intent(
            intent_name="x",
            categoria="Outros",
            keywords=["x"],
            last_update="2026-01-15",
        )
        assert i.last_update_date() == date(2026, 1, 15)

    def test_intent_invalid_date(self):
        i = Intent(
            intent_name="x",
            categoria="Outros",
            last_update="not-a-date",
        )
        assert i.last_update_date() is None


# ---------------------------------------------------------------------------
# Keyword lookup (S = 1.0, no embedding model loaded)
# ---------------------------------------------------------------------------


class TestKeywordLookup:
    def test_exact_keyword_match(self, playbook):
        match = playbook.lookup("Olá, gostaria de prorrogar meu estágio na empresa X")
        assert match is not None
        assert match.intent.intent_name == "faq_prorrogar_estagio"
        assert match.score == 1.0
        assert match.method == "keyword"
        assert "prorrogar meu estágio" in match.matched_keywords

    def test_case_insensitive(self, playbook):
        match = playbook.lookup("Quero TRANCAR O CURSO no próximo semestre")
        assert match is not None
        assert match.intent.intent_name == "trancamento_curso"
        assert match.score == 1.0

    def test_multi_word_keyword(self, playbook):
        # "Termo Aditivo" — multi-token literal
        match = playbook.lookup("Anexo o Termo Aditivo para prorrogação")
        assert match is not None
        # could match either prorrogar or aditivo intent — both share keywords
        assert match.method == "keyword"

    def test_no_match_returns_none(self, playbook):
        # Generic query with no playbook keywords AND no semantic load
        # (we never call _ensure_embeddings here because keyword path returns
        # quickly on empty intents — but here we want it to actually try)
        # We monkey-patch to disable semantic so test stays fast.
        playbook._ensure_embeddings = lambda: False  # type: ignore
        match = playbook.lookup("aleatório sobre futebol e churrasco")
        assert match is None

    def test_empty_query(self, playbook):
        assert playbook.lookup("") is None
        assert playbook.lookup("   ") is None


# ---------------------------------------------------------------------------
# Required fields validation
# ---------------------------------------------------------------------------


class TestRequiredFields:
    def test_all_present(self):
        intent = Intent(
            intent_name="x",
            categoria="Outros",
            keywords=["x"],
            required_fields=["nome_aluno", "numero_tce"],
        )
        missing = missing_required_fields(
            intent, {"nome_aluno": "João", "numero_tce": "12345"}
        )
        assert missing == []

    def test_some_missing(self):
        intent = Intent(
            intent_name="x",
            categoria="Outros",
            keywords=["x"],
            required_fields=["nome_aluno", "numero_tce"],
        )
        missing = missing_required_fields(intent, {"nome_aluno": "João"})
        assert missing == ["numero_tce"]

    def test_empty_value_counts_as_missing(self):
        intent = Intent(
            intent_name="x",
            categoria="Outros",
            keywords=["x"],
            required_fields=["nome_aluno"],
        )
        assert missing_required_fields(intent, {"nome_aluno": ""}) == ["nome_aluno"]


# ---------------------------------------------------------------------------
# Variable extraction (regex)
# ---------------------------------------------------------------------------


class TestExtractVariables:
    def test_sender_name_with_address(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        email = EmailData(
            sender="João Silva <joao@ufpr.br>",
            subject="TCE 12345",
            body="oi",
        )
        vars = extract_variables(email, intent)
        assert vars["nome_aluno"] == "João Silva"

    def test_sender_bare_address(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        email = EmailData(sender="maria.santos@ufpr.br", subject="oi", body="")
        vars = extract_variables(email, intent)
        assert vars["nome_aluno"] == "maria.santos"

    def test_extracts_tce_number(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        email = EmailData(
            sender="x@y.z",
            subject="Encaminho TCE nº 4567",
            body="conforme TCE n. 4567",
        )
        vars = extract_variables(email, intent)
        assert vars["numero_tce"] == "4567"

    def test_extracts_sei_number(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        email = EmailData(
            sender="x@y.z",
            subject="Processo",
            body="processo SEI 23075.123456/2026-01 referente",
        )
        vars = extract_variables(email, intent)
        assert vars["numero_processo_sei"] == "23075.123456/2026-01"

    def test_extracts_grr(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        email = EmailData(
            sender="x@y.z", subject="Aluno GRR20231234", body="GRR 20231234"
        )
        vars = extract_variables(email, intent)
        assert vars["grr"] == "20231234"

    def test_extracts_dates(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        email = EmailData(
            sender="x@y.z",
            subject="Estágio",
            body="período de 01/02/2026 a 31/12/2026",
        )
        vars = extract_variables(email, intent)
        assert vars["data_inicio"] == "01/02/2026"
        assert vars["data_termino"] == "31/12/2026"


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------


class TestFillTemplate:
    def test_replaces_brackets(self):
        result = fill_template(
            "Olá [NOME_ALUNO], TCE [NUMERO_TCE]",
            {"nome_aluno": "Ana", "numero_tce": "999"},
        )
        assert result == "Olá Ana, TCE 999"

    def test_replaces_jinja_style(self):
        result = fill_template(
            "Saudações,\n{{ assinatura_email }}",
            {"assinatura_email": "Coord. DG"},
        )
        assert result == "Saudações,\nCoord. DG"

    def test_unknown_placeholder_left_intact(self):
        # Unfilled placeholders survive so a human reviewer can spot them
        result = fill_template("Olá [NOME_ALUNO], [DATA_INICIO]", {"nome_aluno": "Ana"})
        assert result == "Olá Ana, [DATA_INICIO]"

    def test_empty_template(self):
        assert fill_template("", {"x": "y"}) == ""


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------


class TestStaleness:
    def test_intent_fresh_when_rag_older(self, playbook):
        intent = playbook.get("faq_prorrogar_estagio")
        assert intent is not None
        # Pretend RAG store mtime is BEFORE intent.last_update — fresh
        old_mtime = (
            datetime(2025, 1, 1).timestamp()
        )
        assert playbook.is_stale(intent, rag_mtime=old_mtime) is False

    def test_intent_stale_when_rag_newer(self, playbook):
        intent = playbook.get("faq_prorrogar_estagio")
        assert intent is not None
        # Pretend RAG was just re-ingested — newer than 2026-01-15
        new_mtime = datetime(2027, 6, 1).timestamp()
        assert playbook.is_stale(intent, rag_mtime=new_mtime) is True

    def test_intent_with_no_date_never_stale(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        pb = Playbook(path=Path("/tmp/nonexistent.md"))
        assert pb.is_stale(intent, rag_mtime=datetime(2099, 1, 1).timestamp()) is False


# ---------------------------------------------------------------------------
# End-to-end keyword path
# ---------------------------------------------------------------------------


class TestEndToEndKeyword:
    def test_lookup_and_fill(self, playbook):
        match = playbook.lookup("Olá, quero prorrogar meu estágio")
        assert match is not None
        intent = match.intent

        email = EmailData(
            sender="Ana Souza <ana@ufpr.br>",
            subject="prorrogar TCE 1234",
            body="quero prorrogar meu estágio TCE 1234",
        )
        vars = extract_variables(email, intent)
        assert missing_required_fields(intent, vars) == []
        draft = playbook.fill(intent, vars)
        assert "Ana Souza" in draft
        assert "1234" in draft
