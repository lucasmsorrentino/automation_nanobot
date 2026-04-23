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

    def test_estagios_intents_do_not_require_numero_tce(self):
        """Domain rule: nem todo TCE tem número (depende da origem). Intents
        Tier 0 de Estágios NÃO devem listar numero_tce em required_fields —
        caso contrário acuse/aditivo/conclusão nunca dão Tier 0 hit quando
        o documento não tem o número explícito.
        """
        from pathlib import Path

        from ufpr_automation.procedures.playbook import parse_procedures_md

        procedures_md = Path(__file__).resolve().parents[1] / "workspace" / "PROCEDURES.md"
        intents = {i.intent_name: i for i in parse_procedures_md(procedures_md)}

        for name in (
            "estagio_nao_obrig_acuse_inicial",
            "estagio_nao_obrig_aditivo",
            "estagio_nao_obrig_conclusao",
        ):
            assert name in intents, f"intent {name} ausente em PROCEDURES.md"
            assert "numero_tce" not in intents[name].required_fields, (
                f"intent {name} ainda exige numero_tce; torne-o opcional"
            )

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

    def test_intent_extended_fields_default_empty(self):
        """A legacy intent without SEI workflow fields must still parse
        with sensible defaults so existing PROCEDURES.md entries keep
        working unchanged.
        """
        i = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        assert i.sei_action == "none"
        assert i.sei_process_type == ""
        assert i.required_attachments == []
        assert i.blocking_checks == []
        assert i.despacho_template == ""
        assert i.llm_extraction_fields == []

    def test_intent_extended_fields_parse_from_yaml(self, tmp_path):
        """All 5 new SEI workflow fields round-trip through the YAML parser."""
        md = tmp_path / "PROCEDURES.md"
        md.write_text(
            """\
```intent
intent_name: tce_inicial_estagios
keywords:
  - "TCE inicial"
  - "termo de compromisso"
categoria: "Estágios"
action: "Abrir Processo SEI"
required_fields:
  - nome_aluno
  - numero_tce
  - data_inicio
last_update: "2026-04-10"
confidence: 0.92
template: "Despacho enviado — processo [NUMERO_PROCESSO_SEI] criado."
sei_action: create_process
sei_process_type: "Graduação/Ensino Técnico: Estágios não Obrigatórios"
required_attachments:
  - TCE_assinado
blocking_checks:
  - siga_matricula_ativa
  - siga_reprovacoes_ultimo_semestre
  - data_inicio_retroativa
  - tce_jornada_sem_horario
despacho_template: |
  Ao Setor X,
  Encaminha-se o TCE de [NOME_ALUNO] (GRR[GRR]) para análise.
```
""",
            encoding="utf-8",
        )
        intents = parse_procedures_md(md)
        assert len(intents) == 1
        intent = intents[0]
        assert intent.intent_name == "tce_inicial_estagios"
        assert intent.sei_action == "create_process"
        assert intent.sei_process_type.startswith("Graduação")
        assert intent.required_attachments == ["TCE_assinado"]
        assert intent.blocking_checks == [
            "siga_matricula_ativa",
            "siga_reprovacoes_ultimo_semestre",
            "data_inicio_retroativa",
            "tce_jornada_sem_horario",
        ]
        assert "[NOME_ALUNO]" in intent.despacho_template
        assert "análise" in intent.despacho_template

    def test_intent_sei_action_rejects_invalid_literal(self):
        """sei_action is a Literal — invalid values must fail validation."""
        with pytest.raises(Exception):  # pydantic ValidationError
            Intent(
                intent_name="x",
                categoria="Estágios",
                keywords=["x"],
                sei_action="delete_process",  # type: ignore[arg-type]
            )


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
        missing = missing_required_fields(intent, {"nome_aluno": "João", "numero_tce": "12345"})
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
        email = EmailData(sender="x@y.z", subject="Aluno GRR20231234", body="GRR 20231234")
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

    def test_nome_aluno_maiusculas_variant(self):
        intent = Intent(intent_name="x", categoria="Outros", keywords=["x"])
        email = EmailData(sender="João Silva <joao@ufpr.br>", subject="x", body="")
        vars = extract_variables(email, intent)
        assert vars["nome_aluno"] == "João Silva"
        assert vars["nome_aluno_maiusculas"] == "JOÃO SILVA"

    def test_nome_concedente_maiusculas_variant(self):
        from ufpr_automation.core.models import AttachmentData

        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        attach = AttachmentData(
            filename="tce.pdf",
            extracted_text="Parte Concedente: Acme Studios Ltda.",
        )
        email = EmailData(
            sender="x@y.z",
            subject="TCE",
            body="segue",
            attachments=[attach],
        )
        vars = extract_variables(email, intent)
        assert vars["nome_concedente"] == "Acme Studios Ltda"
        assert vars["nome_concedente_maiusculas"] == "ACME STUDIOS LTDA"


# ---------------------------------------------------------------------------
# Aditivo extraction — numero_aditivo + data_termino_novo (numeric / extenso)
# ---------------------------------------------------------------------------


class TestAditivoExtraction:
    def _make_attach(self, text: str):
        from ufpr_automation.core.models import AttachmentData

        return AttachmentData(filename="aditivo.pdf", extracted_text=text)

    def test_extracts_numero_aditivo_from_body(self):
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        email = EmailData(
            sender="x@y.z",
            subject="Encaminho Termo Aditivo nº 1",
            body="segue em anexo",
        )
        vars = extract_variables(email, intent)
        assert vars["numero_aditivo"] == "1"

    def test_extracts_numero_aditivo_from_attachment(self):
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        email = EmailData(sender="x@y.z", subject="aditivo", body="")
        email.attachments = [
            self._make_attach(
                "TERMO ADITIVO Nº 02 AO TERMO DE COMPROMISSO DE ESTÁGIO Nº 12345\n"
                "Pelo presente termo, fica prorrogada a vigência..."
            )
        ]
        vars = extract_variables(email, intent)
        assert vars["numero_aditivo"] == "02"
        # _TCE_RE should still pick up the 12345 correctly
        assert vars.get("numero_tce") == "12345"

    def test_aditivo_lookahead_skips_ao_termo(self):
        """'ADITIVO AO TERMO DE COMPROMISSO Nº 12345' must NOT capture 12345
        as numero_aditivo — the 12345 is the TCE, not the aditivo."""
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        email = EmailData(
            sender="x@y.z",
            subject="aditivo",
            body="ADITIVO AO TERMO DE COMPROMISSO DE ESTÁGIO Nº 12345",
        )
        vars = extract_variables(email, intent)
        assert "numero_aditivo" not in vars
        assert vars["numero_tce"] == "12345"

    def test_extracts_data_termino_novo_numeric(self):
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        email = EmailData(sender="x@y.z", subject="aditivo", body="")
        email.attachments = [self._make_attach("Fica prorrogada a vigência até 30/06/2027.")]
        vars = extract_variables(email, intent)
        assert vars["data_termino_novo"] == "30/06/2027"

    def test_extracts_data_termino_novo_extenso(self):
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        email = EmailData(sender="x@y.z", subject="aditivo", body="")
        email.attachments = [
            self._make_attach(
                "Pelo presente Termo Aditivo nº 1, fica prorrogado até "
                "1 de junho de 2027, preservadas as demais condições."
            )
        ]
        vars = extract_variables(email, intent)
        assert vars["numero_aditivo"] == "1"
        assert vars["data_termino_novo"] == "01/06/2027"

    def test_extracts_data_termino_novo_extenso_marco(self):
        """Accent in 'março' must normalize — keyed as 'marco' internally."""
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        email = EmailData(sender="x@y.z", subject="aditivo", body="")
        email.attachments = [self._make_attach("Nova vigência até 15 de março de 2027.")]
        vars = extract_variables(email, intent)
        assert vars["data_termino_novo"] == "15/03/2027"


class TestParseBrDate:
    def test_numeric(self):
        from ufpr_automation.procedures.playbook import _parse_br_date

        assert _parse_br_date("em 30/06/2026") == "30/06/2026"

    def test_extenso(self):
        from ufpr_automation.procedures.playbook import _parse_br_date

        assert _parse_br_date("1 de junho de 2027") == "01/06/2027"

    def test_extenso_com_acento(self):
        from ufpr_automation.procedures.playbook import _parse_br_date

        assert _parse_br_date("10 de março de 2027") == "10/03/2027"
        assert _parse_br_date("10 de marco de 2027") == "10/03/2027"

    def test_empty_and_no_match(self):
        from ufpr_automation.procedures.playbook import _parse_br_date

        assert _parse_br_date("") is None
        assert _parse_br_date("no date here") is None


# ---------------------------------------------------------------------------
# LLM extraction (Tier 0 staying Tier 0 via bounded LLM, no RAG)
# ---------------------------------------------------------------------------


class TestLLMExtractionFields:
    """Intents that declare `llm_extraction_fields` trigger bounded LLM calls
    from inside extract_variables (still Tier 0 — no RAG is consulted)."""

    def _mock_llm(self, monkeypatch, content: str):
        """Patch cascaded_completion_sync to return a canned response.

        Uses SimpleNamespace to mimic the LiteLLM response shape
        (response.choices[0].message.content).
        """
        from types import SimpleNamespace

        fake = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        def _fake_call(*args, **kwargs):
            return fake

        import ufpr_automation.procedures.playbook as pb

        # The function imports cascaded_completion_sync lazily *inside*
        # _llm_extract_fields, so we patch the source module, not playbook.
        monkeypatch.setattr("ufpr_automation.llm.router.cascaded_completion_sync", _fake_call)
        return pb

    def test_llm_fills_missing_field_when_declared(self, monkeypatch):
        pb = self._mock_llm(monkeypatch, "- falta assinatura da concedente\n- CPF ausente")
        intent = Intent(
            intent_name="pendencia",
            categoria="Estágios",
            keywords=["pendência"],
            required_fields=["nome_aluno", "lista_pendencias"],
            llm_extraction_fields=["lista_pendencias"],
        )
        email = EmailData(
            sender="Maria <maria@ufpr.br>",
            subject="pendência TCE",
            body="O TCE veio sem assinatura e sem CPF.",
        )
        vars = pb.extract_variables(email, intent)
        assert "- falta assinatura" in vars["lista_pendencias"]
        assert "CPF ausente" in vars["lista_pendencias"]

    def test_llm_none_response_leaves_field_absent(self, monkeypatch):
        pb = self._mock_llm(monkeypatch, "NONE")
        intent = Intent(
            intent_name="pendencia",
            categoria="Estágios",
            keywords=["x"],
            llm_extraction_fields=["lista_pendencias"],
        )
        email = EmailData(sender="x@y.z", subject="x", body="")
        vars = pb.extract_variables(email, intent)
        assert "lista_pendencias" not in vars

    def test_no_llm_call_when_field_not_declared(self, monkeypatch):
        """Intents without llm_extraction_fields must not trigger any LLM call,
        even when required_fields reference unextractable fields."""
        calls: list[int] = []

        def _boom(*args, **kwargs):
            calls.append(1)
            raise AssertionError("LLM must not be called for intents without llm_extraction_fields")

        monkeypatch.setattr("ufpr_automation.llm.router.cascaded_completion_sync", _boom)
        intent = Intent(
            intent_name="regex_only",
            categoria="Outros",
            keywords=["x"],
            required_fields=["lista_pendencias"],
        )
        email = EmailData(sender="x@y.z", subject="x", body="")
        vars = extract_variables(email, intent)
        assert calls == []
        assert "lista_pendencias" not in vars

    def test_regex_wins_over_llm(self, monkeypatch):
        """Fields populated by regex must NOT trigger an LLM call."""
        calls: list[int] = []

        def _boom(*args, **kwargs):
            calls.append(1)
            raise AssertionError("LLM must not be called when regex already filled the field")

        monkeypatch.setattr("ufpr_automation.llm.router.cascaded_completion_sync", _boom)
        # grr is regex-covered; declaring it in llm_extraction_fields should be a no-op.
        intent = Intent(
            intent_name="x",
            categoria="Outros",
            keywords=["x"],
            llm_extraction_fields=["grr"],
        )
        email = EmailData(sender="x@y.z", subject="GRR20231234", body="")
        vars = extract_variables(email, intent)
        assert vars["grr"] == "20231234"
        assert calls == []

    def test_llm_exception_swallowed(self, monkeypatch):
        """If the LLM call raises, the field stays absent and execution continues."""

        def _raise(*args, **kwargs):
            raise RuntimeError("simulated LLM failure")

        monkeypatch.setattr("ufpr_automation.llm.router.cascaded_completion_sync", _raise)
        intent = Intent(
            intent_name="pendencia",
            categoria="Estágios",
            keywords=["x"],
            llm_extraction_fields=["lista_pendencias"],
        )
        email = EmailData(sender="x@y.z", subject="x", body="")
        vars = extract_variables(email, intent)
        # Failure must not propagate; field simply stays absent.
        assert "lista_pendencias" not in vars


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
        old_mtime = datetime(2025, 1, 1).timestamp()
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


# ---------------------------------------------------------------------------
# Supervisor extraction (2026-04-22) — feeds supervisor_formacao_compativel
# ---------------------------------------------------------------------------


class TestSupervisorExtraction:
    def _make_attach(self, text: str):
        from ufpr_automation.core.models import AttachmentData

        return AttachmentData(filename="tce.pdf", extracted_text=text)

    def test_extracts_nome_and_formacao_supervisor_labeled(self):
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        tce = (
            "TERMO DE COMPROMISSO DE ESTÁGIO\n"
            "Supervisor no Local de Estágio: João Pereira Silva\n"
            "Formação do Supervisor: Design Gráfico\n"
            "CPF: 000.000.000-00\n"
        )
        email = EmailData(
            sender="x@y.z",
            subject="TCE",
            body="",
            attachments=[self._make_attach(tce)],
        )
        vars = extract_variables(email, intent)
        assert vars.get("nome_supervisor") == "João Pereira Silva"
        assert vars.get("formacao_supervisor") == "Design Gráfico"

    def test_extracts_via_cargo_alternative_label(self):
        """TCE podem usar 'Cargo do Supervisor:' em vez de 'Formação:'."""
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        tce = "Supervisor: Ana Ribeiro\nCargo do Supervisor: Diretora de Arte\n"
        email = EmailData(
            sender="x@y.z",
            subject="TCE",
            body="",
            attachments=[self._make_attach(tce)],
        )
        vars = extract_variables(email, intent)
        assert vars.get("nome_supervisor") == "Ana Ribeiro"
        assert vars.get("formacao_supervisor") == "Diretora de Arte"

    def test_missing_supervisor_returns_no_vars(self):
        intent = Intent(intent_name="x", categoria="Estágios", keywords=["x"])
        email = EmailData(
            sender="x@y.z",
            subject="TCE",
            body="",
            attachments=[self._make_attach("sem supervisor aqui")],
        )
        vars = extract_variables(email, intent)
        assert "nome_supervisor" not in vars
        assert "formacao_supervisor" not in vars
