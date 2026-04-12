"""Lazy-cached loader for workspace/SEI_DOC_CATALOG.yaml.

Exposes ``get_doc_classification(label)`` which returns a
``SEIDocClassification`` ready for ``SEIWriter.attach_document``.

Usage::

    from ufpr_automation.procedures.doc_catalog import get_doc_classification

    cls = get_doc_classification("TCE")
    assert cls.sei_tipo == "Externo"
    assert cls.sei_subtipo == "Termo"

    cls = get_doc_classification("unknown")  # returns None
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any

import yaml

from ufpr_automation.sei.writer_models import SEIDocClassification

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "workspace" / "SEI_DOC_CATALOG.yaml"


@functools.lru_cache(maxsize=1)
def _load_catalog(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Parse SEI_DOC_CATALOG.yaml and return the raw dict (cached)."""
    p = path or _CATALOG_PATH
    if not p.exists():
        logger.warning("SEI_DOC_CATALOG.yaml not found at %s", p)
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning("SEI_DOC_CATALOG.yaml top-level is not a mapping")
            return {}
        return raw
    except Exception as e:
        logger.error("Failed to parse SEI_DOC_CATALOG.yaml: %s", e)
        return {}


def get_doc_classification(label: str, *, path: Path | None = None) -> SEIDocClassification | None:
    """Look up a semantic label and return a ``SEIDocClassification``.

    Args:
        label: Semantic document label (e.g. ``"TCE"``, ``"Termo Aditivo"``).
            Case-insensitive lookup is attempted if an exact match fails.
        path: Override catalog path (for testing).

    Returns:
        ``SEIDocClassification`` if found, ``None`` otherwise.
    """
    catalog = _load_catalog(path)
    if not catalog:
        return None

    # Exact match first
    entry = catalog.get(label)

    # Case-insensitive fallback
    if entry is None:
        label_lower = label.lower()
        for key, val in catalog.items():
            if key.lower() == label_lower:
                entry = val
                break

    if entry is None:
        return None

    return SEIDocClassification(
        sei_tipo=entry.get("sei_tipo", "Externo"),
        sei_subtipo=entry.get("sei_subtipo", ""),
        sei_classificacao=entry.get("sei_classificacao", ""),
        sigiloso=entry.get("sigiloso", True),
        motivo_sigilo=entry.get("motivo_sigilo", "Informação Pessoal"),
        data_documento=entry.get("data_documento", ""),
    )


def list_labels(*, path: Path | None = None) -> list[str]:
    """Return all known document labels from the catalog."""
    return list(_load_catalog(path).keys())


def reload_catalog() -> None:
    """Clear the LRU cache, forcing a re-read on next access."""
    _load_catalog.cache_clear()
