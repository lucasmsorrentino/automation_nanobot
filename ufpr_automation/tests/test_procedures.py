"""Tests for procedures/store.py — ProcedureStore JSONL persistence."""

from __future__ import annotations

import pytest

from ufpr_automation.procedures.store import ProcedureRecord, ProcedureStep, ProcedureStore


@pytest.fixture
def store(tmp_path):
    return ProcedureStore(path=tmp_path / "test_procedures.jsonl")


@pytest.fixture
def sample_record():
    return ProcedureRecord(
        run_id="run123",
        email_hash="abc456",
        email_subject="TCE Joao Silva",
        email_categoria="Estagios",
        steps=[
            ProcedureStep(name="perceber", duration_ms=500, result="ok"),
            ProcedureStep(name="classificar", duration_ms=1200, result="ok"),
            ProcedureStep(name="consultar_sei", duration_ms=3000, result="ok"),
            ProcedureStep(name="agir_draft", duration_ms=800, result="ok"),
        ],
        outcome="draft_saved",
        sei_process="23075.123456/2026-01",
    )


class TestProcedureStore:
    def test_add_and_count(self, store, sample_record):
        assert store.count() == 0
        store.add(sample_record)
        assert store.count() == 1

    def test_add_sets_timestamp(self, store, sample_record):
        record = store.add(sample_record)
        assert record.timestamp != ""

    def test_add_computes_total_duration(self, store):
        record = ProcedureRecord(
            run_id="r1",
            email_hash="h1",
            steps=[
                ProcedureStep(name="a", duration_ms=100),
                ProcedureStep(name="b", duration_ms=200),
            ],
        )
        result = store.add(record)
        assert result.total_duration_ms == 300

    def test_list_all(self, store, sample_record):
        store.add(sample_record)
        store.add(sample_record)
        records = store.list_all()
        assert len(records) == 2
        assert records[0].run_id == "run123"

    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_get_stats_empty(self, store):
        stats = store.get_stats()
        assert stats["total_runs"] == 0

    def test_get_stats(self, store, sample_record):
        store.add(sample_record)
        # Add a second record with different outcome
        r2 = ProcedureRecord(
            run_id="run456",
            email_hash="def789",
            email_subject="Oficio externo",
            email_categoria="Oficios",
            steps=[ProcedureStep(name="perceber", duration_ms=300)],
            outcome="escalated",
        )
        store.add(r2)

        stats = store.get_stats()
        assert stats["total_runs"] == 2
        assert stats["by_outcome"]["draft_saved"] == 1
        assert stats["by_outcome"]["escalated"] == 1
        assert stats["by_categoria"]["Estagios"] == 1
        assert stats["by_categoria"]["Oficios"] == 1
        assert stats["sei_consultations"] == 1
        assert stats["avg_duration_by_step"]["perceber"] > 0

    def test_list_recent(self, store, sample_record):
        store.add(sample_record)
        recent = store.list_recent(days=1)
        assert len(recent) == 1

    def test_path_property(self, store, tmp_path):
        assert store.path == tmp_path / "test_procedures.jsonl"
