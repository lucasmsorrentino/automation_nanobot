"""Loader for siga_selectors.yaml — the grounded manifest of Playwright
selectors for the SIGA read-only flows.

This is the SIGA-side mirror of ``sei/writer_selectors.py``. The manifest
replaces the fragile "guess N alternatives" locators currently hardcoded
in ``siga/client.py`` with a single, captured, validated source of truth.

The YAML is produced by :mod:`ufpr_automation.agent_sdk.siga_grounder`,
which reads the processed UFPR Aberta BLOCO 3 tutorial markdown and uses
the Claude CLI to extract structured selectors + navigation flow.

Schema (top-level keys, documented in ``siga/SELECTORS_SCHEMA.md``):

    meta:            provenance (captured_at, source_tutorial, schema_version)
    login:           login page url + credential fields + submit + logged-in indicator
    navigation:      named navigation paths (home, student_search, ...)
    screens:         per-screen selector blocks — each with fields + indicators
    forbidden_selectors: belt-and-suspenders list of selectors the client
                         MUST NEVER click (SIGA is read-only by policy).

Usage::

    from ufpr_automation.siga.selectors import get_selectors, get_screen

    sels = get_selectors()
    search = get_screen("student_search")
    grr_sel = search["fields"]["grr_input"]["selector"]

The manifest is loaded lazily, validated, and cached. If no manifest
exists yet (e.g. before the grounder has run), any accessor raises
:class:`SIGASelectorsError` with a clear "capture pending" message so
callers can fall back to the legacy guess-based path.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Must match siga/client.py read-only policy. Any attempt to load a
# manifest whose leaf selector matches one of these raises immediately.
# Grounder output is validated against this list before being written.
#
# Matching is a case-insensitive substring check so all of the following
# forms are caught:
#     #btnSalvar, text=Salvar, button:has-text('Salvar'),
#     a.btnSalvarAlteracoes, xpath=//button[text()='Salvar']
# We err on the side of over-blocking: legitimate SIGA read screens
# won't contain these action words; if a false positive ever shows up,
# rename the selector upstream rather than weaken the guard.
_FORBIDDEN_SELECTORS: tuple[str, ...] = (
    "salvar",
    "gravar",
    "alterar",
    "editar",
    "excluir",
    "remover",
    "inserir",
    "matricular",
    "cadastrar",
    "confirmar",  # e.g. "Confirmar matrícula"
    "deletar",
)


class SIGASelectorsError(RuntimeError):
    """Raised when the manifest is missing, malformed, or violates the
    read-only forbidden-selector policy."""


_SCHEMA_VERSION = 1

_REQUIRED_TOP_LEVEL_KEYS = ("meta", "login", "screens")


# Default location. The grounder emits to
# procedures_data/siga_capture/<timestamp>/siga_selectors.yaml; this
# symlink/copy convention mirrors sei_selectors — the concrete path is
# overridable via SIGA_SELECTORS_PATH env var (handy for fixtures + tests).
_DEFAULT_DIR = (
    Path(__file__).resolve().parent.parent
    / "procedures_data"
    / "siga_capture"
)


def _manifest_path() -> Path:
    """Resolve the path of the active manifest.

    Precedence:
        1. ``SIGA_SELECTORS_PATH`` env var (absolute path).
        2. ``procedures_data/siga_capture/latest/siga_selectors.yaml``.
        3. Most recently modified ``siga_selectors.yaml`` under any
           timestamped subdir of ``procedures_data/siga_capture/``.
    """
    override = os.environ.get("SIGA_SELECTORS_PATH")
    if override:
        return Path(override)

    latest = _DEFAULT_DIR / "latest" / "siga_selectors.yaml"
    if latest.exists():
        return latest

    if _DEFAULT_DIR.exists():
        candidates = sorted(
            _DEFAULT_DIR.glob("*/siga_selectors.yaml"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]

    # Return the "expected" path even if missing — the loader raises a
    # clear error on access rather than silently returning a stale path.
    return latest


@lru_cache(maxsize=1)
def get_selectors() -> dict[str, Any]:
    """Load, validate, and cache the SIGA selectors manifest.

    Raises:
        SIGASelectorsError: if the YAML is missing, malformed, violates
            the schema, or references a forbidden (write-op) selector.
    """
    path = _manifest_path()
    if not path.exists():
        raise SIGASelectorsError(
            f"siga_selectors.yaml not found at {path}. "
            "Run the grounder (python -m ufpr_automation.agent_sdk.siga_grounder) "
            "after the UFPR Aberta BLOCO 3 tutorial has been processed into "
            "base_conhecimento/ufpr_aberta/, or set SIGA_SELECTORS_PATH to "
            "point at a fixture manifest."
        )

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise SIGASelectorsError(f"malformed siga_selectors.yaml at {path}: {e}") from e

    if not isinstance(data, dict):
        raise SIGASelectorsError(
            f"siga_selectors.yaml at {path} must be a mapping at the top level"
        )

    _validate_schema(data, path)
    _validate_no_forbidden_selectors(data, path)
    return data


def clear_cache() -> None:
    """Clear the lru_cache. Needed in tests that swap manifests."""
    get_selectors.cache_clear()


def _validate_schema(data: dict[str, Any], path: Path) -> None:
    missing = [k for k in _REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing:
        raise SIGASelectorsError(
            f"{path}: missing required top-level keys: {missing}. "
            f"Required: {list(_REQUIRED_TOP_LEVEL_KEYS)}"
        )
    meta = data.get("meta") or {}
    version = meta.get("schema_version")
    if version != _SCHEMA_VERSION:
        raise SIGASelectorsError(
            f"{path}: schema_version {version!r} != expected {_SCHEMA_VERSION}. "
            "Re-run the grounder or upgrade the loader."
        )


def _is_forbidden(sel: str) -> bool:
    low = sel.lower()
    return any(f.lower() in low for f in _FORBIDDEN_SELECTORS)


def _validate_no_forbidden_selectors(data: dict[str, Any], path: Path) -> None:
    """Walk the manifest and raise if any leaf selector string matches
    _FORBIDDEN_SELECTORS. Mirrors the SEI writer guard.

    The ``forbidden_selectors`` section (if present) is explicitly
    excluded — listing them is documentation; using them is the
    violation.
    """
    violations: list[str] = []

    def _walk(node: Any, loc: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{loc}.{k}" if loc else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{loc}[{i}]")
        elif isinstance(node, str):
            # Ignore the documentation block that names the forbidden
            # selectors by design.
            if loc.startswith("forbidden_selectors"):
                return
            # Only flag values that LOOK like a selector — heuristic:
            # either the key is a known selector field, or the value
            # starts with #, ., text=, xpath=, input[.
            parent_key = loc.rsplit(".", 1)[-1] if "." in loc else loc
            is_selector_key = parent_key in {
                "selector", "tab_selector", "submit_selector",
                "result_indicator", "logged_in_indicator",
            } or parent_key.endswith("_selector")
            looks_like_selector = node.startswith(
                ("#", ".", "text=", "xpath=", "input[", "button[", "a[")
            )
            if (is_selector_key or looks_like_selector) and _is_forbidden(node):
                violations.append(f"{loc} = {node!r}")

    _walk(data, "")
    if violations:
        raise SIGASelectorsError(
            f"{path}: selectors violate read-only policy (_FORBIDDEN_SELECTORS):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


# Convenience accessors -----------------------------------------------------

def get_screen(screen_name: str) -> dict[str, Any]:
    """Return the selector block for a named screen. Raises if unknown."""
    screens = get_selectors().get("screens", {})
    if screen_name not in screens:
        raise SIGASelectorsError(
            f"unknown screen '{screen_name}' — available: {sorted(screens)}"
        )
    return screens[screen_name]


def get_field(screen_name: str, field_name: str) -> dict[str, Any]:
    """Return the selector block for a single field on a screen."""
    fields = get_screen(screen_name).get("fields", {})
    if field_name not in fields:
        raise SIGASelectorsError(
            f"unknown field '{field_name}' on screen '{screen_name}' — "
            f"available: {sorted(fields)}"
        )
    return fields[field_name]


def get_navigation(name: str) -> dict[str, Any]:
    """Return a named navigation path (menu clicks / URL hint)."""
    nav = get_selectors().get("navigation", {})
    if name not in nav:
        raise SIGASelectorsError(
            f"unknown navigation '{name}' — available: {sorted(nav)}"
        )
    return nav[name]


def get_login() -> dict[str, Any]:
    """Return the login selector block."""
    login = get_selectors().get("login")
    if not login:
        raise SIGASelectorsError("manifest is missing the 'login' section")
    return login


def has_manifest() -> bool:
    """Cheap check: does a manifest exist on disk? Doesn't validate it.

    Callers can use this to fall back to the legacy guess-based path
    while the grounder hasn't run yet.
    """
    return _manifest_path().exists()
