"""Append-only JSONL store for procedure logging and learning.

Records what the system did for each email, how long it took, and the outcome.
This data enables the system to learn which procedures are most efficient
and adapt over time based on human feedback.

Usage:
    store = ProcedureStore()
    store.add(ProcedureRecord(
        run_id="abc123",
        email_hash="def456",
        steps=[ProcedureStep(name="perceber", duration_ms=1200, result="ok")],
        outcome="draft_saved",
    ))
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ufpr_automation.config import settings
from ufpr_automation.utils.logging import logger

PROCEDURES_DIR = settings.PROCEDURES_DATA_DIR
PROCEDURES_FILE = PROCEDURES_DIR / "procedures.jsonl"


class ProcedureStep(BaseModel):
    """A single step within a procedure execution."""

    name: str = Field(description="Step name (e.g. perceber, classificar, consultar_sei)")
    duration_ms: int = Field(default=0, description="Time taken in milliseconds")
    result: str = Field(default="ok", description="Step result: ok, error, skipped")
    notes: str = Field(default="", description="Additional context or error message")


class ProcedureRecord(BaseModel):
    """A complete procedure execution record for one email."""

    timestamp: str = Field(default="")
    run_id: str = Field(default="", description="Unique ID for the pipeline run")
    email_hash: str = Field(default="", description="stable_id of the email processed")
    email_subject: str = Field(default="")
    email_categoria: str = Field(default="")
    steps: list[ProcedureStep] = Field(default_factory=list)
    total_duration_ms: int = Field(default=0)
    outcome: str = Field(
        default="",
        description="Final outcome: draft_saved, escalated, sei_consulted, "
        "siga_consulted, error, skipped",
    )
    sei_process: str = Field(default="", description="SEI process number if consulted")
    siga_grr: str = Field(default="", description="GRR if SIGA was consulted")
    human_feedback: str = Field(
        default="",
        description="Feedback from human review: approved, corrected, rejected",
    )


class ProcedureStore:
    """Append-only JSONL store for procedure records."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or PROCEDURES_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, record: ProcedureRecord) -> ProcedureRecord:
        """Append a procedure record to the store."""
        if not record.timestamp:
            record.timestamp = datetime.now(timezone.utc).isoformat()
        if not record.total_duration_ms and record.steps:
            record.total_duration_ms = sum(s.duration_ms for s in record.steps)

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

        logger.info(
            "Procedimento registrado: %s [%s] %dms — %s",
            record.email_subject[:40],
            record.email_categoria,
            record.total_duration_ms,
            record.outcome,
        )
        return record

    def list_all(self) -> list[ProcedureRecord]:
        """Read all procedure records."""
        if not self._path.exists():
            return []
        records = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(ProcedureRecord.model_validate_json(line))
                except Exception as e:
                    logger.warning("Procedimento: linha %d invalida: %s", line_num, e)
        return records

    def list_recent(self, days: int = 30) -> list[ProcedureRecord]:
        """Read procedure records from the last N days."""
        all_records = self.list_all()
        if not all_records:
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        recent = []
        for r in all_records:
            try:
                ts = datetime.fromisoformat(r.timestamp).timestamp()
                if ts >= cutoff:
                    recent.append(r)
            except (ValueError, TypeError):
                recent.append(r)  # Include if timestamp is unparseable
        return recent

    def count(self) -> int:
        """Count total procedure records."""
        if not self._path.exists():
            return 0
        with open(self._path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    @property
    def path(self) -> Path:
        return self._path
