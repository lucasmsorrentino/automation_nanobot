"""Tests for agent_sdk/procedures_staleness — PROCEDURES.md staleness checker."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from ufpr_automation.agent_sdk.procedures_staleness import (
    IntentCheck,
    _load_soul_sections,
    check_intent,
    run_staleness_check,
)
from ufpr_automation.procedures.playbook import Intent


def _make_intent(**overrides) -> Intent:
    """Create an Intent with sensible defaults, overridable."""
    defaults = {
        "intent_name": "test_intent",
        "keywords": ["test"],
        "categoria": "Outros",
        "action": "Redigir Resposta",
        "last_update": date.today().isoformat(),
        "confidence": 0.9,
        "template": "Prezado(a) [NOME_ALUNO], teste.",
    }
    defaults.update(overrides)
    return Intent(**defaults)


REGISTERED_CHECKS = {
    "siga_matricula_ativa",
    "data_inicio_retroativa",
    "tce_assinado_presente",
    "jornada_antes_meio_dia",
}


# ---------------------------------------------------------------------------
# _load_soul_sections
# ---------------------------------------------------------------------------

class TestLoadSoulSections:
    def test_extracts_sections(self, tmp_path):
        soul = tmp_path / "SOUL.md"
        soul.write_text("## 8. Estágios\n### 8.1 Prazos\n## 11. Validação\n", encoding="utf-8")
        sections = _load_soul_sections(soul)
        assert "8" in sections
        assert "8.1" in sections or "11" in sections  # Depends on regex

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_soul_sections(tmp_path / "nope.md") == set()


# ---------------------------------------------------------------------------
# check_intent — blocking_checks
# ---------------------------------------------------------------------------

class TestCheckIntentBlockingChecks:
    def test_all_checks_registered(self):
        intent = _make_intent(blocking_checks=["siga_matricula_ativa", "data_inicio_retroativa"])
        result = check_intent(
            intent, registered_checks=REGISTERED_CHECKS,
            soul_sections=set(), catalog_types=set(),
        )
        assert result.status == "ok"
        assert not result.issues

    def test_unregistered_check_is_stale(self):
        intent = _make_intent(blocking_checks=["nonexistent_check"])
        result = check_intent(
            intent, registered_checks=REGISTERED_CHECKS,
            soul_sections=set(), catalog_types=set(),
        )
        assert result.status == "stale"
        assert any("not registered" in i for i in result.issues)

    def test_empty_blocking_checks_ok(self):
        intent = _make_intent(blocking_checks=[])
        result = check_intent(
            intent, registered_checks=REGISTERED_CHECKS,
            soul_sections=set(), catalog_types=set(),
        )
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_intent — sources
# ---------------------------------------------------------------------------

class TestCheckIntentSources:
    def test_valid_soul_reference(self):
        intent = _make_intent(sources=["SOUL.md §8"])
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections={"8", "11"}, catalog_types=set(),
        )
        assert result.status == "ok"

    def test_invalid_soul_reference_is_stale(self):
        intent = _make_intent(sources=["SOUL.md §99"])
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections={"8", "11"}, catalog_types=set(),
        )
        assert result.status == "stale"
        assert any("§99" in i for i in result.issues)

    def test_non_soul_sources_ignored(self):
        intent = _make_intent(sources=["Lei 11.788/2008", "Resolução 70/04-CEPE"])
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections={"8"}, catalog_types=set(),
        )
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_intent — last_update age
# ---------------------------------------------------------------------------

class TestCheckIntentAge:
    def test_recent_update_ok(self):
        intent = _make_intent(last_update=date.today().isoformat())
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections=set(), catalog_types=set(), max_age_days=90,
        )
        assert result.status == "ok"

    def test_old_update_warns(self):
        old_date = (date.today() - timedelta(days=120)).isoformat()
        intent = _make_intent(last_update=old_date)
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections=set(), catalog_types=set(), max_age_days=90,
        )
        assert result.status == "warning"
        assert any("120 days old" in i for i in result.issues)

    def test_invalid_date_warns(self):
        intent = _make_intent(last_update="not-a-date")
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections=set(), catalog_types=set(),
        )
        assert result.status == "warning"
        assert any("not a valid ISO date" in i for i in result.issues)

    def test_empty_last_update_ok(self):
        intent = _make_intent(last_update="")
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections=set(), catalog_types=set(),
        )
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_intent — SEI action consistency
# ---------------------------------------------------------------------------

class TestCheckIntentSEI:
    def test_sei_action_with_valid_type(self):
        intent = _make_intent(
            sei_action="create_process",
            sei_process_type="Graduação/Ensino Técnico: Estágios não Obrigatórios",
        )
        catalog = {"Graduação/Ensino Técnico: Estágios não Obrigatórios"}
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections=set(), catalog_types=catalog,
        )
        assert result.status == "ok"

    def test_sei_action_empty_type_warns(self):
        intent = _make_intent(sei_action="create_process", sei_process_type="")
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections=set(), catalog_types=set(),
        )
        assert result.status == "warning"
        assert any("sei_process_type is empty" in i for i in result.issues)

    def test_sei_action_none_no_check(self):
        intent = _make_intent(sei_action="none", sei_process_type="")
        result = check_intent(
            intent, registered_checks=set(),
            soul_sections=set(), catalog_types=set(),
        )
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# run_staleness_check (integration with real PROCEDURES.md)
# ---------------------------------------------------------------------------

class TestRunStalenessCheck:
    def test_with_synthetic_procedures(self, tmp_path):
        proc = tmp_path / "PROCEDURES.md"
        proc.write_text(
            '```intent\n'
            'intent_name: test_ok\n'
            'keywords: ["test"]\n'
            'categoria: Outros\n'
            'last_update: "' + date.today().isoformat() + '"\n'
            '```\n',
            encoding="utf-8",
        )

        results = run_staleness_check(
            procedures_path=proc,
            soul_path=tmp_path / "SOUL.md",
            catalog_path=tmp_path / "CATALOG.yaml",
            report_dir=tmp_path / "reports",
        )
        assert len(results) == 1
        assert results[0].status == "ok"
        # Report file written
        reports = list((tmp_path / "reports").rglob("report.md"))
        assert len(reports) == 1

    def test_detects_stale_intent(self, tmp_path):
        proc = tmp_path / "PROCEDURES.md"
        proc.write_text(
            '```intent\n'
            'intent_name: broken_intent\n'
            'keywords: ["broken"]\n'
            'categoria: Outros\n'
            'blocking_checks:\n'
            '  - nonexistent_checker\n'
            'sources:\n'
            '  - "SOUL.md §999"\n'
            '```\n',
            encoding="utf-8",
        )
        soul = tmp_path / "SOUL.md"
        soul.write_text("## 8. Estágios\n", encoding="utf-8")

        results = run_staleness_check(
            procedures_path=proc,
            soul_path=soul,
            report_dir=tmp_path / "reports",
        )
        assert len(results) == 1
        assert results[0].status == "stale"
        assert len(results[0].issues) >= 2  # checker + source

    def test_empty_procedures_returns_empty(self, tmp_path):
        proc = tmp_path / "PROCEDURES.md"
        proc.write_text("No intents here.", encoding="utf-8")
        results = run_staleness_check(
            procedures_path=proc,
            report_dir=tmp_path / "reports",
        )
        assert results == []

    def test_report_contains_status_table(self, tmp_path):
        proc = tmp_path / "PROCEDURES.md"
        proc.write_text(
            '```intent\n'
            'intent_name: intent_a\n'
            'keywords: ["a"]\n'
            'categoria: Outros\n'
            '```\n'
            '```intent\n'
            'intent_name: intent_b\n'
            'keywords: ["b"]\n'
            'categoria: Outros\n'
            'blocking_checks:\n  - fake_check\n'
            '```\n',
            encoding="utf-8",
        )
        results = run_staleness_check(
            procedures_path=proc,
            report_dir=tmp_path / "reports",
        )
        assert len(results) == 2
        report = list((tmp_path / "reports").rglob("report.md"))[0]
        content = report.read_text(encoding="utf-8")
        assert "intent_a" in content
        assert "intent_b" in content
        assert "STALE" in content
