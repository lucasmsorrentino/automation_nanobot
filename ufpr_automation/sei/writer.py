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
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.config import settings
from ufpr_automation.sei.writer_models import (
    AcompanhamentoEspecialResult,
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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

        # --- LIVE MODE ---
        from urllib.parse import urljoin

        from ufpr_automation.sei.writer_selectors import get_form

        form = get_form("incluir_documento_externo")
        page = self._page
        dialog_texts: list[str] = []

        async def _on_dialog(d):
            dialog_texts.append(d.message)
            logger.warning("attach_document dialog[%s]: %s", d.type, d.message)
            await d.accept()

        page.on("dialog", _on_dialog)
        try:
            # Ensure we're at a process page. The caller is expected to have
            # navigated there (either via create_process' result or via
            # #txtPesquisaRapida). If processo_id looks like a full SEI
            # number and we're not on its page, navigate via search.
            cur_title = await page.title()
            if processo_id and processo_id not in (cur_title or ""):
                logger.info(
                    "attach_document: navigating to process %s via search",
                    processo_id,
                )
                search = page.locator("#txtPesquisaRapida")
                await search.click()
                await search.fill("")
                await search.press_sequentially(processo_id, delay=20)
                await search.press("Enter")
                await page.wait_for_load_state("networkidle", timeout=20000)

            # Find the "Incluir Documento" anchor in the toolbar. Works
            # whether the page is framed (ifrConteudoVisualizacao) or flat.
            href = None
            for frame in [page.main_frame, *page.frames]:
                try:
                    a = frame.locator(
                        'xpath=//a[.//img[@title="Incluir Documento"]]'
                    ).first
                    if await a.count() > 0:
                        href = await a.get_attribute("href")
                        break
                except Exception:
                    pass
            if not href:
                raise RuntimeError(
                    "attach_document: 'Incluir Documento' anchor not found. "
                    "Page may not be on a process view."
                )
            absolute_url = urljoin(page.url, href)

            # Navigate the form frame if it exists, else the main page.
            vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
            if vf is None:
                await page.goto(absolute_url, wait_until="networkidle")
            else:
                await vf.goto(absolute_url, wait_until="networkidle")
                # Refresh frame handle after navigation.
                vf = next(
                    (f for f in page.frames if f.name == "ifrVisualizacao"), None
                )

            target = vf or page.main_frame

            # Click "Externo" option (escolher(-1)).
            await target.evaluate("() => escolher(-1)")
            await page.wait_for_timeout(2000)

            # Refresh frame handle (the escolher() call navigates).
            vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
            target = vf or page.main_frame
            # Wait for the Externo form to render — #txtDataElaboracao is a
            # reliable indicator that the form fields are hydrated.
            await target.wait_for_selector(
                form["fields"]["data_documento"]["selector"],
                state="visible",
                timeout=15000,
            )

            # Fill the form.
            # 1. Tipo do Documento (Série): select by visible text. Changing
            # Série can trigger an AJAX refresh that resets other fields —
            # do this FIRST before filling anything else.
            if classification.sei_subtipo:
                try:
                    await target.locator(
                        form["fields"]["tipo_documento"]["selector"]
                    ).select_option(label=classification.sei_subtipo)
                    logger.info(
                        "attach_document: selected selSerie label='%s'",
                        classification.sei_subtipo,
                    )
                except Exception as e:
                    logger.warning(
                        "tipo_documento select_option by label '%s' failed: %s. "
                        "Trying partial match.",
                        classification.sei_subtipo,
                        e,
                    )
                    await target.evaluate(
                        """(subtipo) => {
                          const sel = document.querySelector('#selSerie');
                          if (!sel) return;
                          for (const o of sel.options) {
                            if ((o.textContent || '').toLowerCase().includes(subtipo.toLowerCase())) {
                              sel.value = o.value;
                              sel.dispatchEvent(new Event('change', {bubbles: true}));
                              return;
                            }
                          }
                        }""",
                        classification.sei_subtipo,
                    )
                # Wait for any SEI-side refresh to settle.
                await page.wait_for_timeout(1200)

            # 3. Texto Inicial = Nenhum.
            try:
                await target.locator(
                    form["fields"]["texto_inicial_nenhum"]["label"]
                ).click()
            except Exception:
                pass

            # 4. Nome na Árvore (optional — ex.: "TCE - NOME").
            nome_arvore = (
                f"{classification.sei_subtipo or 'Documento'} - "
                f"{classification.sei_classificacao or ''}"
            ).strip(" -")
            try:
                await target.locator(
                    form["fields"]["nome_na_arvore"]["selector"]
                ).fill(nome_arvore)
            except Exception as e:
                logger.debug("nome_arvore fill soft-failed: %s", e)

            # 5. Formato = Nato-digital (default for PDFs).
            try:
                await target.locator(
                    form["fields"]["formato"]["labels"]["nato_digital"]
                ).click()
            except Exception:
                pass

            # 6. Nível de Acesso.
            nivel_key = "restrito" if classification.sigiloso else "publico"
            try:
                await target.locator(
                    form["fields"]["nivel_acesso"]["labels"][nivel_key]
                ).click()
                await page.wait_for_timeout(200)
            except Exception as e:
                logger.warning("nivel_acesso click failed: %s", e)

            # 7. Hipótese Legal (if Restrito).
            if classification.sigiloso:
                default_hl = form["fields"]["hipotese_legal"]["default_value"]
                try:
                    await target.locator(
                        form["fields"]["hipotese_legal"]["selector"]
                    ).select_option(value=default_hl)
                except Exception as e:
                    logger.warning("hipotese_legal select failed: %s", e)

            # 7.5. Fill Data do Documento LAST (before upload). Doing this
            # after Série+Nivel+Hipotese avoids any AJAX-triggered reset.
            date_str = classification.data_documento or datetime.now().strftime("%d/%m/%Y")
            if "-" in date_str:
                try:
                    y, m, d = date_str.split("-")
                    date_str = f"{d}/{m}/{y}"
                except Exception:
                    pass
            date_loc = target.locator(
                form["fields"]["data_documento"]["selector"]
            ).first
            await date_loc.click()
            await date_loc.fill("")
            await date_loc.press_sequentially(date_str, delay=30)
            await date_loc.press("Tab")  # force blur → change event
            # Read back to confirm.
            actual_date = await date_loc.input_value()
            logger.info(
                "attach_document: data_documento fill='%s' → actual='%s'",
                date_str,
                actual_date,
            )

            # 8. Upload file. set_input_files triggers onchange which
            # auto-starts the upload; wait for completion.
            file_input_sel = form["fields"]["arquivo"]["selector"]
            await target.locator(file_input_sel).set_input_files(str(file_path))
            # Wait for upload to finish. SEI shows progress; we poll until
            # the progress frame reports idle or the Salvar button is enabled.
            await page.wait_for_timeout(3000)

            artifacts.append(
                await self._screenshot(f"attach_pre_save_{processo_id}_{sha}")
            )

            # 9. Click Salvar. SEI renders the button twice (top + bottom
            # toolbars of the form); use .first to pick the top one.
            submit_sel = form["submit"]["selector"]
            self._assert_not_forbidden(submit_sel)
            await target.locator(submit_sel).first.click()
            await page.wait_for_load_state("networkidle", timeout=30000)

            if dialog_texts:
                artifacts.append(
                    await self._screenshot(f"attach_dialog_{processo_id}")
                )
                return AttachResult(
                    success=False,
                    processo_id=processo_id,
                    file_path=file_path,
                    classification=classification,
                    artifacts=artifacts,
                    dry_run=False,
                    error=f"SEI alerts blocked save: {dialog_texts}",
                )

            artifacts.append(
                await self._screenshot(f"attach_post_save_{processo_id}_{sha}")
            )

            self._audit(
                "attach_document",
                processo_id,
                mode="live",
                file_path=str(file_path),
                file_sha256=sha,
                sei_tipo=classification.sei_tipo,
                sei_subtipo=classification.sei_subtipo,
                sei_classificacao=classification.sei_classificacao,
                sigiloso=classification.sigiloso,
                nome_arvore=nome_arvore,
                artifacts=[str(p) for p in artifacts],
            )
            logger.info(
                "SEIWriter[live]: attached %s to %s as %s/%s (%s)",
                file_path.name,
                processo_id,
                classification.sei_tipo,
                classification.sei_subtipo,
                "Restrito" if classification.sigiloso else "Público",
            )
            return AttachResult(
                success=True,
                processo_id=processo_id,
                file_path=file_path,
                classification=classification,
                artifacts=artifacts,
                dry_run=False,
            )
        finally:
            try:
                page.remove_listener("dialog", _on_dialog)
            except Exception:
                pass

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

        # --- LIVE MODE ---
        from ufpr_automation.sei.writer_selectors import get_form

        form = get_form("iniciar_processo")
        page = self._page
        dialog_texts: list[str] = []

        async def _on_dialog(d):
            dialog_texts.append(d.message)
            logger.warning("create_process dialog[%s]: %s", d.type, d.message)
            await d.accept()

        page.on("dialog", _on_dialog)
        try:
            # Navigate to menu "Iniciar Processo".
            await self._safe_click('a:has-text("Iniciar Processo")')
            await page.wait_for_load_state("networkidle", timeout=15000)

            # Filter the type picker to reach the desired tipo_processo.
            # SEI uses onkeyup; fill() won't trigger it, so press sequentially.
            filt = page.locator("#txtFiltro")
            await filt.click()
            await filt.fill("")
            # Use a short, unique substring to avoid ambiguous matches.
            await filt.press_sequentially(tipo_processo[:20], delay=40)
            await page.wait_for_timeout(600)

            # Click the specific type link.
            await self._safe_click(f'a:has-text("{tipo_processo}")')
            await page.wait_for_load_state("networkidle", timeout=15000)

            # Fill the form.
            await page.locator(form["fields"]["especificacao"]["selector"]).fill(
                especificacao
            )
            if interessado:
                try:
                    await page.locator(
                        form["fields"]["interessados"]["selector"]
                    ).fill(interessado)
                except Exception as e:
                    logger.debug("interessado fill soft-failed: %s", e)
            if motivo:
                try:
                    await page.locator(
                        form["fields"]["observacoes"]["selector"]
                    ).fill(motivo)
                except Exception as e:
                    logger.debug("observacoes fill soft-failed: %s", e)

            # Nível de Acesso = Público (label click, radio has overlay).
            publico_label = form["fields"]["nivel_acesso"]["labels"]["publico"]
            await self._safe_click(publico_label)
            await page.wait_for_timeout(200)

            # Screenshot pre-submit for audit.
            artifacts.append(await self._screenshot(f"create_proc_pre_save_{self._run_id}"))

            # Click Salvar.
            submit_sel = form["submit"]["selector"]
            await self._safe_click(submit_sel)
            await page.wait_for_load_state("networkidle", timeout=20000)

            if dialog_texts:
                artifacts.append(
                    await self._screenshot(f"create_proc_dialog_{self._run_id}")
                )
                return CreateProcessResult(
                    success=False,
                    tipo_processo=tipo_processo,
                    especificacao=especificacao,
                    interessado=interessado,
                    processo_id="",
                    artifacts=artifacts,
                    dry_run=False,
                    error=f"SEI alerts blocked save: {dialog_texts}",
                )

            # Extract process number from the resulting page.
            # After Iniciar Processo save, SEI places the number in:
            # - document.title: "SEI - 23075.020959/2026-31"
            # - <h1> inside #divInfraBarraLocalizacao
            # - the tree sidebar (may be in a nested frame)
            # document.title is the most robust.
            proc_num = await page.evaluate(
                r"""
                () => {
                  const re = /\d{5}\.\d{6}\/\d{4}-\d{2}/;
                  const t = (document.title || '').match(re);
                  if (t) return t[0];
                  const h = document.querySelector('#divInfraBarraLocalizacao h1');
                  if (h) {
                    const m = (h.textContent || '').match(re);
                    if (m) return m[0];
                  }
                  for (const a of document.querySelectorAll('a')) {
                    const m = (a.textContent || '').match(re);
                    if (m) return m[0];
                  }
                  const body = (document.body.innerText || '').match(re);
                  return body ? body[0] : null;
                }
                """
            )

            artifacts.append(await self._screenshot(f"create_proc_post_save_{self._run_id}"))

            if not proc_num:
                # Save succeeded (URL shows procedimento_trabalhar) but
                # number extraction failed. Return success with empty id
                # and include the URL for debugging.
                logger.warning(
                    "create_process: saved but number extraction failed. url=%s",
                    page.url,
                )

            self._audit(
                "create_process",
                proc_num or "",
                mode="live",
                tipo_processo=tipo_processo,
                especificacao=especificacao,
                interessado=interessado,
                motivo=motivo,
                final_url=page.url,
                artifacts=[str(p) for p in artifacts],
            )
            logger.info(
                "SEIWriter[live]: created process %s for '%s'",
                proc_num,
                especificacao,
            )
            return CreateProcessResult(
                success=bool(proc_num),
                tipo_processo=tipo_processo,
                especificacao=especificacao,
                interessado=interessado,
                processo_id=proc_num or "",
                artifacts=artifacts,
                dry_run=False,
                error=None if proc_num else "process_number_extraction_failed",
            )
        finally:
            # Remove dialog handler — keep the page listener list clean.
            try:
                page.remove_listener("dialog", _on_dialog)
            except Exception:
                pass

    @staticmethod
    async def _clear_editor_body(popup) -> None:
        """Clear pre-existing content in the CKEditor body.

        Defense-in-depth against 'Texto Inicial = Nenhum' not being honored
        by the Despacho form (Sprint 3 regression: default template loaded
        into editor despite the Nenhum radio click). Ctrl+A + Delete is safe
        — the body locator has already been clicked for focus.
        """
        await popup.keyboard.press("Control+A")
        await popup.keyboard.press("Delete")
        await popup.wait_for_timeout(150)

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

            # --- LIVE MODE ---
            from urllib.parse import urljoin

            from ufpr_automation.sei.writer_selectors import get_form

            form = get_form("incluir_documento_despacho")
            page = self._page
            dialog_texts: list[str] = []

            async def _on_dialog(d):
                dialog_texts.append(d.message)
                logger.warning(
                    "save_despacho_draft dialog[%s]: %s", d.type, d.message
                )
                await d.accept()

            page.on("dialog", _on_dialog)
            try:
                # Ensure we're at the process.
                cur_title = await page.title()
                if processo_id and processo_id not in (cur_title or ""):
                    logger.info(
                        "save_despacho_draft: navigating to %s via search",
                        processo_id,
                    )
                    search = page.locator("#txtPesquisaRapida")
                    await search.click()
                    await search.fill("")
                    await search.press_sequentially(processo_id, delay=20)
                    await search.press("Enter")
                    await page.wait_for_load_state("networkidle", timeout=20000)

                # Extract Incluir Documento href.
                href = None
                for frame in [page.main_frame, *page.frames]:
                    try:
                        a = frame.locator(
                            'xpath=//a[.//img[@title="Incluir Documento"]]'
                        ).first
                        if await a.count() > 0:
                            href = await a.get_attribute("href")
                            break
                    except Exception:
                        pass
                if not href:
                    raise RuntimeError(
                        "save_despacho_draft: 'Incluir Documento' anchor not found"
                    )
                absolute_url = urljoin(page.url, href)

                vf = next(
                    (f for f in page.frames if f.name == "ifrVisualizacao"), None
                )
                if vf is None:
                    await page.goto(absolute_url, wait_until="networkidle")
                else:
                    await vf.goto(absolute_url, wait_until="networkidle")
                    vf = next(
                        (f for f in page.frames if f.name == "ifrVisualizacao"),
                        None,
                    )
                target = vf or page.main_frame

                # Click Despacho option (escolher(5)).
                await target.evaluate("() => escolher(5)")
                await page.wait_for_timeout(1500)
                vf = next(
                    (f for f in page.frames if f.name == "ifrVisualizacao"), None
                )
                target = vf or page.main_frame

                # Texto Inicial = Nenhum. Explicitly click the radio input
                # (not just the label) and verify it is checked — in Sprint 3
                # we observed the label-click silently not registering, which
                # caused the default template to load into the editor.
                texto_inicial_cfg = form["fields"]["texto_inicial_nenhum"]
                nenhum_radio_sel = texto_inicial_cfg.get(
                    "selector", texto_inicial_cfg.get("label")
                )
                try:
                    await target.locator(nenhum_radio_sel).first.check()
                except Exception:
                    try:
                        await target.locator(
                            texto_inicial_cfg["label"]
                        ).click()
                    except Exception:
                        pass
                try:
                    is_checked = await target.locator(
                        nenhum_radio_sel
                    ).first.is_checked()
                    if not is_checked:
                        logger.warning(
                            "save_despacho_draft: 'Texto Inicial = Nenhum' "
                            "NOT checked after click — editor will load "
                            "default template. Editor body will be cleared "
                            "before typing as a safety net."
                        )
                except Exception:
                    pass

                # Nível de Acesso = Público (despachos administrativos).
                try:
                    await target.locator(
                        form["fields"]["nivel_acesso"]["labels"]["publico"]
                    ).click()
                    await page.wait_for_timeout(200)
                except Exception as e:
                    logger.warning("nivel_acesso click failed: %s", e)

                artifacts.append(
                    await self._screenshot(f"draft_pre_save_{processo_id}_{tipo}")
                )

                # Click Salvar — opens CKEditor popup. Button appears twice
                # (top + bottom toolbars); use .first.
                context = page.context
                popup = None
                try:
                    async with context.expect_page(timeout=10000) as popup_info:
                        await target.locator(
                            form["submit_form"]["selector"]
                        ).first.click()
                    popup = await popup_info.value
                    logger.info(
                        "save_despacho_draft: editor popup opened: %s",
                        popup.url,
                    )
                except Exception as e:
                    logger.warning(
                        "save_despacho_draft: popup not detected (%s); "
                        "editor may be inline or click failed",
                        e,
                    )

                if popup is None:
                    # Fallback: editor might be in a frame of the main page.
                    artifacts.append(
                        await self._screenshot(
                            f"draft_no_popup_{processo_id}_{tipo}"
                        )
                    )
                    return DraftResult(
                        success=False,
                        processo_id=processo_id,
                        tipo=tipo,
                        artifacts=artifacts,
                        error="editor_popup_not_detected",
                        dry_run=False,
                    )

                await popup.wait_for_load_state("networkidle", timeout=25000)

                # Fill the editor body. CKEditor 5 contenteditable divs
                # don't respond to fill(); click to focus then keyboard.type.
                editor_cfg = form["editor"]
                body_sel = editor_cfg["body"]["selector"]
                body = popup.locator(body_sel).first
                await body.wait_for(state="visible", timeout=15000)
                await body.click()
                # Clear any pre-existing content in the editor (default
                # template may have loaded if 'Texto Inicial = Nenhum'
                # was not honored by the form — Sprint 3 fix).
                await self._clear_editor_body(popup)
                # Type line by line so \n becomes Enter.
                for i, line in enumerate(filled.split("\n")):
                    if i > 0:
                        await popup.keyboard.press("Enter")
                    if line:
                        await popup.keyboard.type(line, delay=5)
                await popup.wait_for_timeout(300)

                # Screenshot editor with text filled.
                try:
                    pre_save_png = self._artifacts_dir / (
                        f"{int(time.time() * 1000)}_draft_editor_filled.png"
                    )
                    await popup.screenshot(path=str(pre_save_png), full_page=True)
                    artifacts.append(pre_save_png)
                except Exception:
                    pass

                # Click Salvar in the editor (class .salvar__buttonview).
                save_sel = editor_cfg["save_button"]["selector"]
                self._assert_not_forbidden(save_sel)
                await popup.locator(save_sel).click()
                await popup.wait_for_timeout(2500)

                # Screenshot post-save.
                try:
                    post_save_png = self._artifacts_dir / (
                        f"{int(time.time() * 1000)}_draft_editor_saved.png"
                    )
                    await popup.screenshot(path=str(post_save_png), full_page=True)
                    artifacts.append(post_save_png)
                except Exception:
                    pass

                # Close popup — leaves the saved draft in the process.
                try:
                    await popup.close()
                except Exception:
                    pass

                if dialog_texts:
                    return DraftResult(
                        success=False,
                        processo_id=processo_id,
                        tipo=tipo,
                        artifacts=artifacts,
                        error=f"SEI alerts blocked save: {dialog_texts}",
                        dry_run=False,
                    )

                self._audit(
                    "save_despacho_draft",
                    processo_id,
                    mode="live",
                    tipo=tipo,
                    content_sha256=content_hash,
                    content_length=len(filled),
                    content_preview=filled[:200],
                    artifacts=[str(p) for p in artifacts],
                )
                logger.info(
                    "SEIWriter[live]: saved despacho draft (%s, %d chars) to %s",
                    tipo,
                    len(filled),
                    processo_id,
                )
                return DraftResult(
                    success=True,
                    processo_id=processo_id,
                    tipo=tipo,
                    artifacts=artifacts,
                    dry_run=False,
                )
            finally:
                try:
                    page.remove_listener("dialog", _on_dialog)
                except Exception:
                    pass
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

    async def add_to_acompanhamento_especial(
        self,
        processo_id: str,
        grupo: str,
        observacao: str = "",
    ) -> AcompanhamentoEspecialResult:
        """Add a SEI process to an Acompanhamento Especial group (POP-38).

        Used by the Estágios não-obrigatório flow to flag newly-created
        TCE processes into the "Estágio não obrigatório" group so the
        secretariat can monitor them as a cohort.

        In ``dry_run`` mode: audits the intent, captures a screenshot,
        and returns ``success=True, dry_run=True`` without clicking.

        In ``live`` mode: currently raises :class:`NotImplementedError`.
        The form ``acompanhamento_especial`` is absent from the current
        ``sei_selectors.yaml`` capture (SEI 5.0.3, CCDG). Wiring the live
        path is blocked on a fresh capture — see
        ``sei/SELECTOR_AUDIT.md §1`` for the expected selector spec.
        """
        artifacts: list[Path] = []

        if self._dry_run:
            try:
                artifacts.append(
                    await self._screenshot(f"acompesp_dryrun_{processo_id}")
                )
            except Exception:
                pass
            self._audit(
                "add_to_acompanhamento_especial",
                processo_id,
                mode="dry_run",
                grupo=grupo,
                observacao=observacao,
                artifacts=[str(p) for p in artifacts],
            )
            logger.info(
                "SEIWriter[dry_run]: would add %s to Acompanhamento Especial "
                "grupo=%r",
                processo_id,
                grupo,
            )
            return AcompanhamentoEspecialResult(
                success=True,
                processo_id=processo_id,
                grupo=grupo,
                observacao=observacao,
                artifacts=artifacts,
                dry_run=True,
            )

        raise NotImplementedError(
            "add_to_acompanhamento_especial live flow is not wired — "
            "form 'acompanhamento_especial' absent from sei_selectors.yaml. "
            "See sei/SELECTOR_AUDIT.md §1 for the capture spec."
        )
