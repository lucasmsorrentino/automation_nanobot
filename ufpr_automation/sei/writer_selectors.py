"""Loader for sei_selectors.yaml — the canonical manifest of Playwright
selectors captured from live SEI sessions. See SDD_SEI_SELECTOR_CAPTURE.md §5.

The manifest is loaded lazily, cached, and exposed as a plain dict so
``sei/writer.py`` can reference selectors by form name + field path without
a heavy DSL layer.

Usage:
    from ufpr_automation.sei.writer_selectors import get_selectors

    sels = get_selectors()
    form = sels["forms"]["iniciar_processo"]
    save_sel = form["submit"]["selector"]     # "#btnSalvar"
    desc_sel = form["fields"]["especificacao"]["selector"]  # "#txtDescricao"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ufpr_automation._selectors_loader import make_loader
from ufpr_automation.sei.writer import _FORBIDDEN_SELECTORS, _is_forbidden  # noqa: F401


class SelectorsError(RuntimeError):
    """Raised when the manifest is missing, malformed, or collides with
    the _FORBIDDEN_SELECTORS guard."""


# Default location — latest capture session's sei_selectors.yaml. Can be
# overridden via the SEI_SELECTORS_PATH env var (handy for tests against a
# fixture manifest) or settings.
# Canonical manifest location: Google Drive (shared across work/home machines).
# Fallback: local procedures_data/sei_capture/ (legacy path, pre-2026-04-14).
# Override in both cases via SEI_SELECTORS_PATH env var.
_DRIVE_PATH = Path(r"G:/Meu Drive/ufpr_automation_files/sei_selectors.yaml")
_LEGACY_LOCAL_PATH = (
    Path(__file__).resolve().parent.parent
    / "procedures_data"
    / "sei_capture"
    / "20260413_192020"
    / "sei_selectors.yaml"
)
_DEFAULT_PATH = _DRIVE_PATH if _DRIVE_PATH.exists() else _LEGACY_LOCAL_PATH


def _default_path_resolver() -> Path:
    return _DEFAULT_PATH


def _is_selector_leaf(loc: str, _value: str) -> bool:
    """True iff the leaf at dotted path ``loc`` is a Playwright selector.

    The SEI capture pipeline stamps selector keys with predictable
    suffixes. Filtering by key avoids false positives on documentation
    strings (notes that legitimately mention "assinar").
    """
    return loc.endswith(("selector", "label", "hidden_store", "hidden_id", "dropdown"))


def _skip_forbidden_path(loc: str) -> bool:
    """Skip the documentation-only ``forbidden_buttons`` block, which
    intentionally lists buttons the writer MUST NEVER click — listing
    them is documentation, using them is the violation.
    """
    return ".forbidden_buttons" in loc


_loader = make_loader(
    manifest_filename="sei_selectors.yaml",
    default_path_resolver=_default_path_resolver,
    env_var="SEI_SELECTORS_PATH",
    forbidden_tokens=_FORBIDDEN_SELECTORS,
    forbidden_skip_paths=_skip_forbidden_path,
    is_selector_leaf=_is_selector_leaf,
    error_cls=SelectorsError,
    missing_manifest_hint=(
        "Run the selector capture sprint (SDD §6) or set "
        "SEI_SELECTORS_PATH to point at a valid manifest."
    ),
)

get_selectors = _loader["get_selectors"]
clear_cache = _loader["clear_cache"]
_manifest_path = _loader["manifest_path"]


def _validate_no_forbidden_selectors(data: dict[str, Any]) -> None:
    """Backwards-compatible single-arg wrapper around the factory's
    invariant check. Kept so existing tests / call sites that pass just
    the parsed dict still work; the factory needs a path purely for
    error messages, so a synthetic ``<inline>`` is fine.
    """
    _loader["validate_no_forbidden_selectors"](data, Path("<inline>"))


# Convenience accessors -----------------------------------------------------


def get_form(form_name: str) -> dict[str, Any]:
    """Return the selector block for a form. Raises if unknown."""
    forms = get_selectors().get("forms", {})
    if form_name not in forms:
        raise SelectorsError(f"unknown form '{form_name}' — available: {sorted(forms)}")
    return forms[form_name]


def get_field(form_name: str, field_name: str) -> dict[str, Any]:
    """Return a single field's selector block."""
    fields = get_form(form_name).get("fields", {})
    if field_name not in fields:
        raise SelectorsError(
            f"unknown field '{field_name}' on form '{form_name}' — available: {sorted(fields)}"
        )
    return fields[field_name]


# Acompanhamento Especial (POP-38) — in-source defaults --------------------
#
# These defaults mirror ``sei/SELECTOR_AUDIT.md §1`` captured from live SEI
# 5.0.3 / CCDG on 2026-04-21. Kept inline (rather than in the YAML manifest
# on Google Drive) so the live path can be wired without a Drive write; a
# future manifest regeneration can add a ``forms.acompanhamento_especial``
# block and ``get_acompanhamento_form`` will prefer it.
_ACOMPANHAMENTO_ESPECIAL_DEFAULTS: dict[str, Any] = {
    "toolbar_icon": {
        # Lives in the process' top toolbar iframe.
        "selector": 'xpath=//a[.//img[@title="Acompanhamento Especial"]]',
        "frame": "ifrConteudoVisualizacao",
    },
    "gerenciar_processo": {
        # List page with Adicionar / Excluir. Reached when process already
        # has at least one acompanhamento. URL has action=acompanhamento_gerenciar.
        "frame": "ifrVisualizacao",
        "action_marker": "acompanhamento_gerenciar",
        "buttons": {
            "adicionar": {
                # onclick="location.href='...acao=acompanhamento_cadastrar...'"
                "selector": "#btnAdicionar",
            },
        },
    },
    "cadastrar": {
        # Form for create + edit. URL has action=acompanhamento_cadastrar.
        # #hdnIdAcompanhamento vazio=create, preenchido=edit.
        "frame": "ifrVisualizacao",
        "action_marker": "acompanhamento_cadastrar",
        "fields": {
            "grupo": {
                "selector": "#selGrupoAcompanhamento",
                "type": "select",
            },
            "novo_grupo_icon": {
                # + icon that opens the modal for creating a new group.
                "selector": "#imgNovoGrupoAcompanhamento",
                "onclick_fn": "cadastrarGrupoAcompanhamento",
                "modal_action_marker": "grupo_acompanhamento_cadastrar",
            },
            "observacao": {
                "selector": "#txaObservacao",
                "type": "textarea",
            },
        },
        "hidden": {
            "id_acompanhamento": "#hdnIdAcompanhamento",
            "id_protocolo": "#hdnIdProtocolo",
        },
        "submit": {
            # NÃO é #btnSalvar — é <button type=submit name=sbm...>.
            "selector": 'button[name="sbmCadastrarAcompanhamento"]',
            "value": "Salvar",
        },
        "cancel": {
            "selector": "#btnCancelar",
        },
    },
    "novo_grupo_modal": {
        # Iframe injected via infraAbrirJanelaModal(...). URL has
        # action=grupo_acompanhamento_cadastrar.
        "action_marker": "grupo_acompanhamento_cadastrar",
        "form_id": "#frmGrupoAcompanhamentoCadastro",
        "fields": {
            "nome": {
                "selector": "#txtNome",
                "maxlength": 150,
            },
        },
        "hidden": {
            "id_grupo": "#hdnIdGrupoAcompanhamento",
        },
        "submit": {
            "selector": 'button[name="sbmCadastrarGrupoAcompanhamento"]',
            "value": "Salvar",
        },
        # Modal has NO Cancelar button — close via Escape key or overlay click.
    },
}


def get_acompanhamento_form() -> dict[str, Any]:
    """Return the Acompanhamento Especial selector bundle.

    Prefers a ``forms.acompanhamento_especial`` entry from the loaded YAML
    manifest if present. Otherwise returns the in-source defaults mirroring
    SELECTOR_AUDIT §1 (captured 2026-04-21).

    Never raises on manifest-missing: the defaults are always available.
    """
    try:
        sels = get_selectors()
        form = sels.get("forms", {}).get("acompanhamento_especial")
        if form:
            return form
    except SelectorsError:
        # Manifest absent/malformed — fall back to the in-source defaults.
        pass
    return _ACOMPANHAMENTO_ESPECIAL_DEFAULTS
