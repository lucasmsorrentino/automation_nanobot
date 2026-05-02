"""Text normalization helpers shared across modules."""

from __future__ import annotations

import unicodedata


def strip_accents_lower(s: str) -> str:
    """Normalize a Portuguese string for keyword matching: remove diacritics,
    lowercase, collapse whitespace.

    Examples:
        >>> strip_accents_lower("Comunicação Social")
        'comunicacao social'
        >>> strip_accents_lower("  ÁGUA   é   BOA  ")
        'agua e boa'
    """
    norm = unicodedata.normalize("NFD", s or "")
    stripped = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    return " ".join(stripped.lower().split())
