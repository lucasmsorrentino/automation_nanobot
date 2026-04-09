"""Append-only JSONL store for human feedback on email classifications.

Each record captures:
- The original email (hash + metadata)
- The system's classification
- The human reviewer's correction
- Timestamp

This data will feed DSPy's MIPROv2 optimizer in Marco II for automatic
prompt re-optimization based on accumulated human corrections.

Usage:
    store = FeedbackStore()
    store.add(email, original_classification, corrected_classification)
    records = store.list_all()
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailClassification
from ufpr_automation.utils.logging import logger

# Default location for the feedback store (override via FEEDBACK_DATA_DIR env var)
FEEDBACK_DIR = settings.FEEDBACK_DATA_DIR
FEEDBACK_FILE = FEEDBACK_DIR / "corrections.jsonl"


class FeedbackRecord(BaseModel):
    """A single human correction record."""

    timestamp: str = Field(description="ISO 8601 timestamp of the correction")
    email_hash: str = Field(description="stable_id of the email")
    email_sender: str = Field(default="")
    email_subject: str = Field(default="")
    original: EmailClassification = Field(description="System's original classification")
    corrected: EmailClassification = Field(description="Human-corrected classification")
    notes: str = Field(default="", description="Optional reviewer notes")


class FeedbackStore:
    """Append-only JSONL store for human corrections."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or FEEDBACK_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def add(
        self,
        email_hash: str,
        original: EmailClassification,
        corrected: EmailClassification,
        email_sender: str = "",
        email_subject: str = "",
        notes: str = "",
    ) -> FeedbackRecord:
        """Append a correction record to the store.

        Args:
            email_hash: The stable_id of the email.
            original: The system's original classification.
            corrected: The human-corrected classification.
            email_sender: Sender for context.
            email_subject: Subject for context.
            notes: Optional reviewer notes.

        Returns:
            The created FeedbackRecord.
        """
        record = FeedbackRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            email_hash=email_hash,
            email_sender=email_sender,
            email_subject=email_subject,
            original=original,
            corrected=corrected,
            notes=notes,
        )

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

        logger.info(
            "Feedback salvo: %s [%s -> %s]",
            email_subject[:40],
            original.categoria,
            corrected.categoria,
        )
        return record

    def list_all(self) -> list[FeedbackRecord]:
        """Read all feedback records from the store."""
        if not self._path.exists():
            return []

        records = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(FeedbackRecord.model_validate_json(line))
                except Exception as e:
                    logger.warning("Feedback: linha %d inválida: %s", line_num, e)
        return records

    def count(self) -> int:
        """Count total feedback records without loading all into memory."""
        if not self._path.exists():
            return 0
        with open(self._path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    @property
    def path(self) -> Path:
        return self._path
