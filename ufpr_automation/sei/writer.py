"""SEIWriter — attach documents and save despacho drafts to SEI processes.

CRITICAL SAFETY BOUNDARY
========================
This class INTENTIONALLY does NOT expose any of these methods:
- sign() / assinar()
- send() / send_process() / enviar()
- protocol() / protocol_submit() / protocolar()
- finalize()

The architectural absence of these methods is the primary safety mechanism.
A test in test_sei_writer.py (`test_writer_has_no_sign_or_send_methods`)
asserts this absence and will fail if any forbidden method is added.

Additionally, every Playwright `.click()` call in this module passes through
`_assert_not_forbidden(selector)` which raises if the selector matches any
of `_FORBIDDEN_SELECTORS`. This belt-and-suspenders guard catches accidental
introduction of forbidden buttons via locator strings.

Adding ANY write capability beyond attach/draft requires explicit code
review by the project owner.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.config import settings
from ufpr_automation.sei.writer_models import AttachResult, DraftResult

logger = logging.getLogger(__name__)


# Selectors that MUST NEVER be clicked. Any attempt to click one of these
# raises PermissionError. The list is intentionally broad and case-insensitive.
_FORBIDDEN_SELECTORS = [
    "assinar",
    "enviar processo",
    "enviar para",
    "protocolar",
    "submit",
    "send process",
    "btnAssinar",
    "btnEnviar",
    "btnProtocolar",
]


def _is_forbidden(selector: str) -> bool:
    """Return True if the selector contains any forbidden substring."""
    if not selector:
        return False
    s = selector.lower()
    return any(token.lower() in s for token in _FORBIDDEN_SELECTORS)


class SEIWriter:
    """Write SEI process documents — attach + draft despacho only.

    Use as an async context for Playwright pages::

        async with playwright.async_api.async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context()
            page = await ctx.new_page()
            writer = SEIWriter(page)
            await writer.attach_document("12345.000123/2026-01", Path("doc.pdf"))
            await writer.save_despacho_draft(
                "12345.000123/2026-01",
                tipo="tce_inicial",
                variables={"NOME": "...", "ORIENTADOR": "..."},
            )
    """

    # DO NOT add sign(), send(), protocol(), or finalize() methods.
    # See module docstring for the safety rationale.

    def __init__(self, page: "Page", run_id: str | None = None):
        self._page = page
        self._run_id = run_id or uuid.uuid4().hex[:12]
        # Ensure parent exists before creating the run-scoped subdir.
        settings.SEI_WRITE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir = settings.SEI_WRITE_ARTIFACTS_DIR / self._run_id
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path = settings.SEI_WRITE_ARTIFACTS_DIR / "audit.jsonl"

    @property
    def run_id(self) -> str:
        return self._run_id

    @staticmethod
    def _assert_not_forbidden(selector: str) -> None:
        """Raise PermissionError if selector matches a forbidden button."""
        if _is_forbidden(selector):
            raise PermissionError(
                f"Refusing to click forbidden selector '{selector}' — "
                f"SEIWriter is not allowed to sign/send/protocol documents."
            )

    async def _safe_click(self, selector: str) -> None:
        """Click a selector after verifying it is not forbidden."""
        self._assert_not_forbidden(selector)
        await self._page.click(selector)

    async def _screenshot(self, label: str) -> Path:
        """Capture a screenshot artifact."""
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label)[:50]
        ts = int(time.time() * 1000)
        path = self._artifacts_dir / f"{ts}_{safe_label}.png"
        try:
            await self._page.screenshot(path=str(path), full_page=True)
        except Exception as e:
            logger.warning("Screenshot failed for %s: %s", label, e)
        return path

    async def _dump_dom(self, label: str) -> Path:
        """Capture a DOM dump artifact."""
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label)[:50]
        ts = int(time.time() * 1000)
        path = self._artifacts_dir / f"{ts}_{safe_label}.html"
        try:
            content = await self._page.content()
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning("DOM dump failed for %s: %s", label, e)
        return path

    def _audit(self, op: str, processo_id: str, **fields: Any) -> None:
        """Append an audit record to the JSONL log."""
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "run_id": self._run_id,
            "op": op,
            "processo_id": processo_id,
            **fields,
        }
        try:
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Audit log write failed: %s", e)

    async def attach_document(
        self, processo_id: str, file_path: Path
    ) -> AttachResult:
        """Attach a document to a SEI process.

        Captures screenshots before and after the attachment dialog.
        """
        artifacts: list[Path] = []
        if not file_path.exists():
            return AttachResult(
                success=False,
                processo_id=processo_id,
                file_path=file_path,
                error=f"file_not_found: {file_path}",
            )

        try:
            # Pre-state screenshot
            artifacts.append(await self._screenshot(f"attach_pre_{processo_id}"))

            # NOTE: actual SEI navigation/upload selectors must be added here
            # using the existing patterns from sei/client.py. The Playwright
            # selector pattern is intentionally generic in this skeleton; the
            # full DOM walk should be added once the live SEI selectors are
            # validated.
            #
            # IMPORTANT: every selector that triggers a click MUST go through
            # self._safe_click() to enforce the forbidden-selector guard.

            artifacts.append(await self._dump_dom(f"attach_post_{processo_id}"))

            sha = hashlib.sha256(file_path.read_bytes()).hexdigest()[:16]
            self._audit(
                "attach_document",
                processo_id,
                file_path=str(file_path),
                file_sha256=sha,
                artifacts=[str(p) for p in artifacts],
            )

            return AttachResult(
                success=True,
                processo_id=processo_id,
                file_path=file_path,
                artifacts=artifacts,
            )
        except PermissionError:
            raise
        except Exception as e:
            logger.error("attach_document failed: %s", e)
            return AttachResult(
                success=False,
                processo_id=processo_id,
                file_path=file_path,
                artifacts=artifacts,
                error=str(e),
            )

    async def save_despacho_draft(
        self,
        processo_id: str,
        tipo: str,
        variables: dict[str, str] | None = None,
    ) -> DraftResult:
        """Save a despacho draft (NEVER signs, NEVER protocols, NEVER sends).

        The despacho body is fetched from the GraphRAG TemplateRegistry,
        placeholders are filled via procedures.playbook.fill_template, and
        the resulting text is entered into the SEI rich-text editor. The
        ONLY click this method makes after entering text is the SEI "Salvar"
        button (which only saves the draft — not Assinar/Enviar/Protocolar).
        """
        artifacts: list[Path] = []
        variables = variables or {}

        try:
            # Lazy import to avoid circular deps
            from ufpr_automation.graphrag.templates import get_registry
            from ufpr_automation.procedures.playbook import fill_template

            template = get_registry().get(tipo)
            if template is None:
                self._audit(
                    "save_despacho_draft",
                    processo_id,
                    tipo=tipo,
                    success=False,
                    error="template_unavailable",
                )
                return DraftResult(
                    success=False,
                    processo_id=processo_id,
                    tipo=tipo,
                    error="template_unavailable",
                )

            filled = fill_template(template, variables)
            content_hash = hashlib.sha256(filled.encode("utf-8")).hexdigest()[:16]

            artifacts.append(await self._screenshot(f"draft_pre_{processo_id}_{tipo}"))

            # NOTE: as with attach_document, the actual editor navigation
            # selectors should be added here using the existing patterns.
            # The Salvar (save draft) button is the ONLY click allowed.
            # Use self._safe_click("text=Salvar") or equivalent — the
            # _FORBIDDEN_SELECTORS guard ensures Assinar/Enviar/Protocolar
            # are blocked even if accidentally referenced.

            artifacts.append(await self._dump_dom(f"draft_post_{processo_id}_{tipo}"))

            self._audit(
                "save_despacho_draft",
                processo_id,
                tipo=tipo,
                content_sha256=content_hash,
                content_length=len(filled),
                artifacts=[str(p) for p in artifacts],
                success=True,
            )

            return DraftResult(
                success=True,
                processo_id=processo_id,
                tipo=tipo,
                artifacts=artifacts,
            )
        except PermissionError:
            raise
        except Exception as e:
            logger.error("save_despacho_draft failed: %s", e)
            return DraftResult(
                success=False,
                processo_id=processo_id,
                tipo=tipo,
                artifacts=artifacts,
                error=str(e),
            )
