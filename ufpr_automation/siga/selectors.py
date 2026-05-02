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

from pathlib import Path
from typing import Any

from ufpr_automation._guard_selectors import is_forbidden as _guard_is_forbidden
from ufpr_automation._selectors_loader import make_loader

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
_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "procedures_data" / "siga_capture"


def _default_path_resolver() -> Path:
    """Resolve the path of the active manifest.

    Precedence:
        1. ``procedures_data/siga_capture/latest/siga_selectors.yaml``.
        2. Most recently modified ``siga_selectors.yaml`` under any
           timestamped subdir of ``procedures_data/siga_capture/``.

    The ``SIGA_SELECTORS_PATH`` env var override is applied by
    :mod:`ufpr_automation._selectors_loader`, not here.
    """
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


def _is_forbidden(sel: str) -> bool:
    """Thin wrapper around the shared substring guard, pinning the
    SIGA-specific forbidden-token tuple. Kept as a module-level function
    so internal callers (and any external imports) keep working unchanged.
    """
    return _guard_is_forbidden(sel, _FORBIDDEN_SELECTORS)


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


def _is_selector_leaf(loc: str, value: str) -> bool:
    """True iff the leaf at dotted path ``loc`` with string ``value``
    should be treated as a Playwright selector.

    SIGA is more heuristic than SEI because the grounder-produced
    manifest doesn't enforce a fixed key suffix. Two paths to True:

    1. Parent key is a known selector field (``selector``,
       ``tab_selector``, ``submit_selector``, ``result_indicator``,
       ``logged_in_indicator``, or ``*_selector``).
    2. Value starts with one of the canonical Playwright selector
       prefixes (``#``, ``.``, ``text=``, ``xpath=``, ``input[``,
       ``button[``, ``a[``).
    """
    parent_key = loc.rsplit(".", 1)[-1] if "." in loc else loc
    is_selector_key = parent_key in {
        "selector",
        "tab_selector",
        "submit_selector",
        "result_indicator",
        "logged_in_indicator",
    } or parent_key.endswith("_selector")
    looks_like_selector = value.startswith(
        ("#", ".", "text=", "xpath=", "input[", "button[", "a[")
    )
    return is_selector_key or looks_like_selector


def _skip_forbidden_path(loc: str) -> bool:
    """Skip the documentation-only ``forbidden_selectors`` block —
    listing them is documentation, using them is the violation.
    """
    return loc.startswith("forbidden_selectors")


_loader = make_loader(
    manifest_filename="siga_selectors.yaml",
    default_path_resolver=_default_path_resolver,
    env_var="SIGA_SELECTORS_PATH",
    forbidden_tokens=_FORBIDDEN_SELECTORS,
    forbidden_skip_paths=_skip_forbidden_path,
    is_selector_leaf=_is_selector_leaf,
    error_cls=SIGASelectorsError,
    schema_validator=_validate_schema,
    missing_manifest_hint=(
        "Run the grounder (python -m ufpr_automation.agent_sdk.siga_grounder) "
        "after the UFPR Aberta BLOCO 3 tutorial has been processed into "
        "base_conhecimento/ufpr_aberta/, or set SIGA_SELECTORS_PATH to "
        "point at a fixture manifest."
    ),
    forbidden_violation_msg="selectors violate read-only policy",
)

get_selectors = _loader["get_selectors"]
clear_cache = _loader["clear_cache"]
has_manifest = _loader["has_manifest"]
_manifest_path = _loader["manifest_path"]


def _validate_no_forbidden_selectors(data: dict[str, Any], path: Path) -> None:
    """Walk the manifest and raise if any leaf selector string matches
    _FORBIDDEN_SELECTORS. Mirrors the SEI writer guard.

    The ``forbidden_selectors`` section (if present) is explicitly
    excluded — listing them is documentation; using them is the
    violation.

    Exposed at module level (in addition to running internally during
    :func:`get_selectors`) because :mod:`agent_sdk.siga_grounder`
    validates a candidate manifest before persisting it.
    """
    _loader["validate_no_forbidden_selectors"](data, path)


# Convenience accessors -----------------------------------------------------


def get_screen(screen_name: str) -> dict[str, Any]:
    """Return the selector block for a named screen. Raises if unknown."""
    screens = get_selectors().get("screens", {})
    if screen_name not in screens:
        raise SIGASelectorsError(f"unknown screen '{screen_name}' — available: {sorted(screens)}")
    return screens[screen_name]


def get_field(screen_name: str, field_name: str) -> dict[str, Any]:
    """Return the selector block for a single field on a screen."""
    fields = get_screen(screen_name).get("fields", {})
    if field_name not in fields:
        raise SIGASelectorsError(
            f"unknown field '{field_name}' on screen '{screen_name}' — available: {sorted(fields)}"
        )
    return fields[field_name]


def get_navigation(name: str) -> dict[str, Any]:
    """Return a named navigation path (menu clicks / URL hint)."""
    nav = get_selectors().get("navigation", {})
    if name not in nav:
        raise SIGASelectorsError(f"unknown navigation '{name}' — available: {sorted(nav)}")
    return nav[name]


def get_login() -> dict[str, Any]:
    """Return the login selector block."""
    login = get_selectors().get("login")
    if not login:
        raise SIGASelectorsError("manifest is missing the 'login' section")
    return login
