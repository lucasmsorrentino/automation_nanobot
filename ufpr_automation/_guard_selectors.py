"""Shared substring-match guard for forbidden Playwright selectors.

Used by ``sei/writer.py`` and ``siga/selectors.py`` to enforce read-only
or write-restricted policies against captured selector manifests. Each
caller keeps its own forbidden-token list (the SEI list blocks
sign/send/protocol; the SIGA list blocks all write actions because
SIGA integration is read-only by policy) and delegates the matching
logic here so the rule "case-insensitive substring match against any
token" lives in one place.

The function is intentionally tiny and pure — no logging, no side
effects, no module-level state. Callers are responsible for raising
their own domain-specific exception (``PermissionError`` /
``SelectorsError`` / ``SIGASelectorsError``) when a violation is
detected.
"""

from __future__ import annotations

from collections.abc import Iterable


def is_forbidden(selector: str, tokens: Iterable[str]) -> bool:
    """Return True if any token appears (case-insensitive) inside selector.

    Empty selectors return False (nothing to match). Tokens are matched
    as plain substrings, lowercased on both sides — so the same call
    catches every spelling of the same target:

        #btnAssinar, text=Assinar, button:has-text('Assinar'),
        a.btnAssinarDespacho, xpath=//button[text()='Assinar']
    """
    if not selector:
        return False
    s = selector.lower()
    return any(t.lower() in s for t in tokens)
