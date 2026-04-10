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
from ufpr_automation.sei.writer_models import (
    AttachResult,
    CreateProcessResult,
    DraftResult,
    SEIDocClassification,
)

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
    """Write SEI process documents — attach, draft despacho, create process.

    Supports three write operations, all gated by the ``dry_run`` flag so
    the pipeline can exercise the planning logic without touching SEI:

        - :meth:`create_process`      — initiate a new SEI process
        - :meth:`attach_document`     — upload external doc to existing process
        - :meth:`save_despacho_draft` — paste despacho body into SEI editor

    Use as an async context for Playwright pages::

        async with playwright.async_api.async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context()
            page = await ctx.new_page()
            writer = SEIWriter(page, dry_run=True)
            result = await writer.create_process(
                tipo_processo="Graduação/Ensino Técnico: Estágios não Obrigatórios",
                especificacao="Design Gráfico",
                interessado="ALANIS ROCHA - GRR20230091",
            )
            await writer.attach_document(
                result.processo_id,
                Path("tce.pdf"),
                SEIDocClassification(
                    sei_tipo="Externo",
                    sei_subtipo="Termo",
                    sei_classificacao="Inicial",
                ),
            )
            await writer.save_despacho_draft(
                result.processo_id,
                tipo="tce_inicial",
                variables={"NOME": "...", "ORIENTADOR": "..."},
            )
    """

    # DO NOT add sign(), send(), protocol(), or finalize() methods.
    # See module docstring for the safety rationale.

    def __init__(
        self,
        page: "Page",
        run_id: str | None = None,
        *,
        dry_run: bool | None = None,
    ):
        self._page = page
        self._run_id = run_id or uuid.uuid4().hex[:12]
        # dry_run default from env var SEI_WRITE_MODE=dry_run|live
        # (dry_run is the SAFE default — set SEI_WRITE_MODE=live explicitly
        # once the Playwright selector flow has been validated against a
        # real SEI session.)
        if dry_run is None:
            mode = str(getattr(settings, "SEI_WRITE_MODE", "dry_run")).lower()
            dry_run = mode != "live"
        self._dry_run = dry_run
        # Ensure parent exists before creating the run-scoped subdir.
        settings.SEI_WRITE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir = settings.SEI_WRITE_ARTIFACTS_DIR / self._run_id
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path = settings.SEI_WRITE_ARTIFACTS_DIR / "audit.jsonl"

    @property
    def dry_run(self) -> bool:
        return self._dry_run

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
        self,
        processo_id: str,
        file_path: Path,
        classification: SEIDocClassification,
    ) -> AttachResult:
        """Attach a document to a SEI process with full classification.

        Mirrors the SEI "Incluir Documento" form:

            1. Menu → Incluir Documento
            2. Tipo do Documento → classification.sei_tipo ("Externo")
            3. Tipo (Externo sub-form):
                 - Subtipo → classification.sei_subtipo ("Termo"/"Relatório")
                 - Classificação → classification.sei_classificacao
            4. Data do Documento → classification.data_documento or today
            5. Nível de Acesso → Restrito (if sigiloso)
            6. Hipótese Legal → classification.motivo_sigilo
            7. Escolher arquivo → file_path
            8. Salvar

        In ``dry_run`` mode: logs the intended operation, captures the
        pre-state screenshot if a page is available, and returns a
        successful result with ``dry_run=True``. No clicks are made.

        In ``live`` mode: runs the full Playwright flow (NOT YET
        IMPLEMENTED — selectors need to be captured from a live SEI
        session first; the method currently raises NotImplementedError
        to prevent accidental live use).
        """
        artifacts: list[Path] = []
        if not file_path.exists():
            return AttachResult(
                success=False,
                processo_id=processo_id,
                file_path=file_path,
                classification=classification,
                error=f"file_not_found: {file_path}",
                dry_run=self._dry_run,
            )

        sha = hashlib.sha256(file_path.read_bytes()).hexdigest()[:16]

        if self._dry_run:
            # Log-only mode: capture the plan without clicking anything.
            try:
                artifacts.append(await self._screenshot(f"attach_dryrun_{processo_id}"))
            except Exception:
                pass  # no page navigated yet is acceptable in dry-run
            self._audit(
                "attach_document",
                processo_id,
                mode="dry_run",
                file_path=str(file_path),
                file_sha256=sha,
                sei_tipo=classification.sei_tipo,
                sei_subtipo=classification.sei_subtipo,
                sei_classificacao=classification.sei_classificacao,
                sigiloso=classification.sigiloso,
                motivo_sigilo=classification.motivo_sigilo,
                data_documento=classification.data_documento,
                artifacts=[str(p) for p in artifacts],
            )
            logger.info(
                "SEIWriter[dry_run]: would attach %s to %s as %s/%s/%s",
                file_path.name,
                processo_id,
                classification.sei_tipo,
                classification.sei_subtipo,
                classification.sei_classificacao,
            )
            return AttachResult(
                success=True,
                processo_id=processo_id,
                file_path=file_path,
                classification=classification,
                artifacts=artifacts,
                dry_run=True,
            )

        # Live mode — NOT YET IMPLEMENTED. The full DOM walk requires
        # selector capture from a real SEI session; see TASKS.md §Marco III
        # for the selector capture sprint.
        raise NotImplementedError(
            "attach_document live mode requires Playwright selector capture "
            "from a real SEI session. Set SEI_WRITE_MODE=dry_run (or omit) "
            "until the selector flow has been validated. See TASKS.md."
        )

    async def create_process(
        self,
        tipo_processo: str,
        especificacao: str,
        interessado: str,
        motivo: str = "",
    ) -> CreateProcessResult:
        """Initiate a NEW SEI process.

        Mirrors the SEI "Iniciar Processo" form:

            1. Menu → Iniciar Processo
            2. Tipo do Processo → tipo_processo (ex.:
               "Graduação/Ensino Técnico: Estágios não Obrigatórios")
            3. Especificação → especificacao (ex.: nome do curso)
            4. Interessado → interessado (ex.: "NOME ALUNO - GRRxxxxxx")
            5. Nível de Acesso → Restrito (sempre, para estágios)
            6. Hipótese Legal → "Informação Pessoal"
            7. Salvar

        ``motivo`` is an optional free-text field shown in the process
        dashboard (some tipos of process require it; most don't).

        Args:
            tipo_processo: The SEI "Tipo do Processo" dropdown value.
            especificacao: The "Especificação" text field.
            interessado: The "Interessado" free-text or picker field.
            motivo: Optional motivo/observação for the process header.

        Returns:
            CreateProcessResult with the assigned process number on
            success. In dry-run mode, ``processo_id`` is a synthetic
            placeholder (``DRYRUN-<run_id>``) so downstream code can chain
            attach_document + save_despacho_draft calls without touching
            SEI.

        SAFETY: this method does NOT sign, send, protocol, or tramitate
        the created process. It ONLY clicks Salvar. The
        ``_FORBIDDEN_SELECTORS`` guard prevents any accidental clicks on
        Assinar/Enviar/Protocolar even if selectors were miswritten.
        """
        artifacts: list[Path] = []

        if self._dry_run:
            try:
                artifacts.append(await self._screenshot(f"create_proc_dryrun_{self._run_id}"))
            except Exception:
                pass
            synthetic_id = f"DRYRUN-{self._run_id}"
            self._audit(
                "create_process",
                synthetic_id,
                mode="dry_run",
                tipo_processo=tipo_processo,
                especificacao=especificacao,
                interessado=interessado,
                motivo=motivo,
                artifacts=[str(p) for p in artifacts],
            )
            logger.info(
                "SEIWriter[dry_run]: would create process '%s' for '%s' (interessado: %s)",
                tipo_processo,
                especificacao,
                interessado,
            )
            return CreateProcessResult(
                success=True,
                tipo_processo=tipo_processo,
                especificacao=especificacao,
                interessado=interessado,
                processo_id=synthetic_id,
                artifacts=artifacts,
                dry_run=True,
            )

        raise NotImplementedError(
            "create_process live mode requires Playwright selector capture "
            "from a real SEI session. Set SEI_WRITE_MODE=dry_run (or omit) "
            "until the selector flow has been validated. See TASKS.md."
        )

    async def save_despacho_draft(
        self,
        processo_id: str,
        tipo: str,
        variables: dict[str, str] | None = None,
        body_override: str | None = None,
    ) -> DraftResult:
        """Save a despacho draft (NEVER signs, NEVER protocols, NEVER sends).

        The despacho body is resolved in this order of preference:

            1. ``body_override`` — if provided, used as-is (after placeholder
               fill). This is how the ``agir_estagios`` node passes the
               ``despacho_template`` from the Tier 0 intent directly,
               without needing a GraphRAG template lookup.
            2. GraphRAG ``TemplateRegistry`` — looked up by ``tipo``.

        The SEI flow (live mode) will be:

            1. Dentro do processo → Incluir Documento
            2. Tipo do Documento → "Despacho"
            3. Editar → o editor rich-text abre
            4. Colar o texto resolvido
            5. Preencher campos específicos (já feito pelo fill_template)
            6. Salvar  ← único clique permitido

        In ``dry_run`` mode: logs the intended text + hash without clicking.
        """
        artifacts: list[Path] = []
        variables = variables or {}

        try:
            # Lazy import to avoid circular deps
            from ufpr_automation.procedures.playbook import fill_template

            if body_override is not None:
                template = body_override
            else:
                from ufpr_automation.graphrag.templates import get_registry

                template = get_registry().get(tipo)
                if template is None:
                    self._audit(
                        "save_despacho_draft",
                        processo_id,
                        tipo=tipo,
                        success=False,
                        error="template_unavailable",
                        mode="dry_run" if self._dry_run else "live",
                    )
                    return DraftResult(
                        success=False,
                        processo_id=processo_id,
                        tipo=tipo,
                        error="template_unavailable",
                        dry_run=self._dry_run,
                    )

            filled = fill_template(template, variables)
            content_hash = hashlib.sha256(filled.encode("utf-8")).hexdigest()[:16]

            if self._dry_run:
                try:
                    artifacts.append(await self._screenshot(f"draft_dryrun_{processo_id}_{tipo}"))
                except Exception:
                    pass
                self._audit(
                    "save_despacho_draft",
                    processo_id,
                    mode="dry_run",
                    tipo=tipo,
                    content_sha256=content_hash,
                    content_length=len(filled),
                    content_preview=filled[:200],
                    artifacts=[str(p) for p in artifacts],
                )
                logger.info(
                    "SEIWriter[dry_run]: would save despacho (%s, %d chars) to %s",
                    tipo,
                    len(filled),
                    processo_id,
                )
                return DraftResult(
                    success=True,
                    processo_id=processo_id,
                    tipo=tipo,
                    artifacts=artifacts,
                    dry_run=True,
                )

            # Live mode — NOT YET IMPLEMENTED.
            raise NotImplementedError(
                "save_despacho_draft live mode requires Playwright selector "
                "capture from a real SEI session (rich-text editor + Salvar "
                "button). Set SEI_WRITE_MODE=dry_run (or omit) until the "
                "selector flow has been validated. See TASKS.md."
            )
        except PermissionError:
            raise
        except NotImplementedError:
            raise
        except Exception as e:
            logger.error("save_despacho_draft failed: %s", e)
            return DraftResult(
                success=False,
                processo_id=processo_id,
                tipo=tipo,
                artifacts=artifacts,
                error=str(e),
                dry_run=self._dry_run,
            )
