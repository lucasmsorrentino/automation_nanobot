"""Result models for SEIWriter operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AttachResult:
    """Result of attaching a document to a SEI process."""
    success: bool
    processo_id: str
    file_path: Path
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None


@dataclass
class DraftResult:
    """Result of saving a despacho draft to a SEI process."""
    success: bool
    processo_id: str
    tipo: str
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None
