#!/usr/bin/env python
"""SEI selector capture harness — Marco IV unblock sprint.

See ``ufpr_automation/SDD_SEI_SELECTOR_CAPTURE.md`` for the full spec. This
script is the Sprint 1 artifact described in §6 of that SDD: it drives a
headed Playwright browser against the SEI web UI, captures the DOM of the
three write-path forms (``iniciar_processo``, ``incluir_documento_externo``,
``incluir_documento_despacho``) and produces a raw snapshot set that a
follow-up session analyzes to author ``sei_selectors.yaml``.

SAFETY PRINCIPLES
-----------------

1. **Manual-first navigation.** The script does NOT try to click its way
   through SEI menus — SEI menu layouts vary between units and deployments
   and an over-eager automation would be one wrong click away from
   signing/sending a document. Instead the human drives navigation and the
   script takes snapshots on demand at each checkpoint.

2. **Forbidden-click guard.** Every click the script itself issues passes
   through :func:`ufpr_automation.sei.writer._is_forbidden`, which rejects
   any selector containing ``assinar``/``enviar``/``protocolar`` tokens —
   the same belt-and-suspenders guard that protects ``SEIWriter``.

3. **Nothing is ever saved.** The script only reads the DOM. The human is
   prompted to cancel/escape each form after the snapshot, and the
   CAPTURE_LOG.md reminder re-states this.

USAGE
-----

Typical interactive run::

    python scripts/capture_sei_selectors.py

Useful flags::

    --output-dir <path>       Override the default timestamped output dir
    --skip-login              Skip auto_login and wait for manual login
    --targets iniciar_processo incluir_externo   Capture only a subset

The output directory defaults to
``ufpr_automation/procedures_data/sei_capture/<YYYYMMDD_HHMMSS>/`` and
contains::

    raw/
        iniciar_processo_form.html
        iniciar_processo_form.png
        iniciar_processo_form_elements.json
        incluir_externo_form.html
        ...
        incluir_despacho_editor.html
        incluir_despacho_editor__frame_*.html   # TinyMCE iframe dumps
    CAPTURE_LOG.md

The ``*_elements.json`` files are the primary input for the follow-up
analysis: each entry lists ``tag``, ``id``, ``name``, ``type``, ``value``,
``placeholder``, ``label``, ``visible`` and a few other hints that are
enough to propose a stable Playwright selector per field.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# When invoked as ``python scripts/capture_sei_selectors.py`` the script's
# own directory is prepended to sys.path, not the repo root. Make the
# ``ufpr_automation`` package importable regardless of CWD.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# NOTE: ``ufpr_automation.sei.browser`` pulls in Playwright at module load
# time. We defer that import into ``main_async`` so ``--help`` works even
# in environments that only installed the dev extras (no Playwright).
from ufpr_automation.sei.writer import _is_forbidden  # noqa: E402
from ufpr_automation.utils.logging import logger  # noqa: E402


# ---------------------------------------------------------------------------
# DOM enumeration JS
# ---------------------------------------------------------------------------

# Runs in the page context and returns a JSON-serializable list of every
# form-relevant element visible in the current document. The set of tags is
# deliberately wide (``a[onclick]`` and ``img[title]`` included) because SEI
# renders some controls as clickable images / anchors rather than native
# ``<button>``.
_ENUMERATE_JS = r"""
() => {
  const pickLabel = (el) => {
    if (el.id) {
      const escaped = el.id.replace(/"/g, '\\"');
      const lbl = document.querySelector(`label[for="${escaped}"]`);
      if (lbl) return (lbl.innerText || lbl.textContent || '').trim();
    }
    let p = el.parentElement;
    while (p && p.tagName !== 'LABEL' && p !== document.body) p = p.parentElement;
    if (p && p.tagName === 'LABEL') return (p.innerText || '').trim();
    return el.getAttribute('aria-label') || '';
  };
  const trim = (s, n) => (s == null ? null : String(s).slice(0, n));
  const take = (el) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || null,
    name: el.getAttribute('name'),
    type: el.getAttribute('type'),
    value: trim(el.value !== undefined ? el.value : null, 120),
    placeholder: el.getAttribute('placeholder'),
    class: el.getAttribute('class'),
    text: trim((el.innerText || el.textContent || '').trim(), 120),
    label: pickLabel(el),
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
    href: el.getAttribute('href'),
    title: el.getAttribute('title'),
    onclick: el.getAttribute('onclick') ? 'yes' : null,
  });
  const sel = 'input, select, textarea, button, a[onclick], a[href], img[title]';
  return Array.from(document.querySelectorAll(sel)).map(take);
}
"""


# ---------------------------------------------------------------------------
# Capture session
# ---------------------------------------------------------------------------


def _safe_name(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", label)[:60]


class CaptureSession:
    """Snapshot helper bound to an open Playwright ``Page``.

    One session per script invocation. All artifacts go under
    ``<output_dir>/raw/`` and a ``CAPTURE_LOG.md`` is written at the end
    with the list of snapshots taken.
    """

    def __init__(self, page, out_dir: Path):
        self.page = page
        self.out_dir = out_dir
        self.raw_dir = out_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.log: list[dict] = []

    # ---- guarded click -------------------------------------------------

    async def safe_click(self, selector: str, *, description: str = "") -> None:
        """Click gated by ``_is_forbidden``.

        Never used during a normal capture run (navigation is manual), but
        exposed so an interactive Claude Code session can use it for the
        Cancelar/Esc step without bypassing the safety guard.
        """
        if _is_forbidden(selector):
            raise PermissionError(
                f"refusing to click forbidden selector {selector!r} "
                f"({description or 'unlabeled click'})"
            )
        logger.info("safe_click: %s (%s)", selector, description or "")
        await self.page.click(selector)

    # ---- snapshot ------------------------------------------------------

    async def snapshot(self, label: str, *, also_frames: bool = False) -> dict:
        """Write HTML, full-page PNG and elements JSON for the current page.

        When ``also_frames`` is True, every child frame's HTML is also
        dumped — needed for the Despacho rich-text editor which is
        typically a TinyMCE iframe.
        """
        safe = _safe_name(label)
        html_path = self.raw_dir / f"{safe}.html"
        png_path = self.raw_dir / f"{safe}.png"
        elements_path = self.raw_dir / f"{safe}_elements.json"

        try:
            html = await self.page.content()
            html_path.write_text(html, encoding="utf-8")
        except Exception as e:
            logger.warning("page.content() falhou (%s): %s", label, e)
            html_path.write_text(f"<!-- capture error: {e} -->", encoding="utf-8")

        try:
            await self.page.screenshot(path=str(png_path), full_page=True)
        except Exception as e:
            logger.warning("screenshot falhou (%s): %s", label, e)

        try:
            elements = await self.page.evaluate(_ENUMERATE_JS)
        except Exception as e:
            logger.warning("enumerate JS falhou (%s): %s", label, e)
            elements = []

        elements_path.write_text(
            json.dumps(elements, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        frame_dumps: list[str] = []
        if also_frames:
            for frame in self.page.frames:
                if frame is self.page.main_frame:
                    continue
                name = frame.name or frame.url or "frame"
                fname = _safe_name(name) or "frame"
                frame_html_path = self.raw_dir / f"{safe}__frame_{fname}.html"
                try:
                    fh = await frame.content()
                except Exception as e:
                    logger.warning("frame %s content falhou: %s", name, e)
                    continue
                frame_html_path.write_text(fh, encoding="utf-8")
                frame_dumps.append(str(frame_html_path.relative_to(self.out_dir)))

        meta = {
            "label": label,
            "url": self.page.url,
            "html": str(html_path.relative_to(self.out_dir)),
            "screenshot": str(png_path.relative_to(self.out_dir)),
            "elements": str(elements_path.relative_to(self.out_dir)),
            "element_count": len(elements),
            "frame_dumps": frame_dumps,
            "captured_at": datetime.now().isoformat(),
        }
        self.log.append(meta)
        logger.info(
            "snapshot %s: %d elementos, %d frames dump",
            label,
            len(elements),
            len(frame_dumps),
        )
        return meta

    # ---- log writer ----------------------------------------------------

    def write_capture_log(self, extra_notes: str = "") -> Path:
        log_path = self.out_dir / "CAPTURE_LOG.md"
        lines: list[str] = [
            "# SEI selector capture log",
            "",
            f"- Captured at: {datetime.now().isoformat()}",
            f"- Output dir: `{self.out_dir}`",
            "- SDD: `ufpr_automation/SDD_SEI_SELECTOR_CAPTURE.md`",
            "",
            "## Safety check",
            "",
            "- [ ] Confirmar manualmente no SEI que NENHUM processo novo foi salvo",
            "- [ ] Confirmar que NENHUM documento (externo ou despacho) foi persistido",
            "- [ ] Se um processo de teste foi aberto, cancelar/arquivar após revisão",
            "",
            "## Snapshots",
            "",
        ]
        if not self.log:
            lines.append("_(nenhum snapshot registrado)_")
            lines.append("")
        for entry in self.log:
            lines.append(f"### {entry['label']}")
            lines.append("")
            lines.append(f"- URL: `{entry['url']}`")
            lines.append(f"- HTML: `{entry['html']}`")
            lines.append(f"- PNG: `{entry['screenshot']}`")
            lines.append(
                f"- Elements: `{entry['elements']}` ({entry['element_count']} itens)"
            )
            if entry["frame_dumps"]:
                lines.append("- Frames:")
                for fd in entry["frame_dumps"]:
                    lines.append(f"  - `{fd}`")
            lines.append("")
        if extra_notes:
            lines.append("## Notes")
            lines.append("")
            lines.append(extra_notes)
            lines.append("")
        lines.append("## Próximo passo")
        lines.append("")
        lines.append(
            "Analise os `raw/*_elements.json` e `raw/*.html` e produza "
            "`sei_selectors.yaml` no schema da §5 do SDD."
        )
        lines.append("")
        log_path.write_text("\n".join(lines), encoding="utf-8")
        return log_path


# ---------------------------------------------------------------------------
# Capture targets (SDD §4) — manual-first with prompts at each checkpoint
# ---------------------------------------------------------------------------


def _prompt(msg: str) -> None:
    """Print a checkpoint and block on ENTER."""
    print("\n>>> " + msg)
    try:
        input("    [ENTER para continuar, Ctrl+C para abortar] ")
    except EOFError:
        pass


async def capture_iniciar_processo(cap: CaptureSession) -> None:
    _prompt(
        "Form 1/3 — Iniciar Processo.\n"
        "    Navegue MANUALMENTE no SEI aberto: menu -> 'Iniciar Processo' ->\n"
        "    selecione o tipo 'Graduação/Ensino Técnico: Estágios não\n"
        "    Obrigatórios' (ou similar) -> espere o formulário aparecer.\n"
        "    Marque 'Nível de Acesso: Restrito' para que 'Hipótese Legal'\n"
        "    fique visível. NÃO clique em Salvar."
    )
    await cap.snapshot("iniciar_processo_form")
    _prompt(
        "Snapshot 1/3 capturado. Cancele o formulário (Esc ou botão Cancelar)\n"
        "    e confirme que nenhum processo foi aberto."
    )


async def capture_incluir_externo(cap: CaptureSession) -> None:
    _prompt(
        "Form 2/3 — Incluir Documento Externo.\n"
        "    Entre em um processo de teste existente (ou peça a alguém para\n"
        "    criar um processo fictício) -> clique no ícone 'Incluir\n"
        "    Documento' -> selecione 'Externo'. No formulário, marque:\n"
        "      - Tipo do Documento: Termo (ou o sub-tipo usado para TCE)\n"
        "      - Formato: 'Digitalizado nesta Unidade'\n"
        "      - Nível de Acesso: Restrito\n"
        "    NÃO clique em Confirmar/Salvar. NÃO anexe arquivo real."
    )
    await cap.snapshot("incluir_externo_form")
    _prompt(
        "Snapshot 2/3 capturado. Cancele o formulário SEM salvar e confirme\n"
        "    que nenhum documento apareceu na árvore do processo."
    )


async def capture_incluir_despacho(cap: CaptureSession) -> None:
    _prompt(
        "Form 3/3a — Incluir Documento: Despacho (formulário inicial).\n"
        "    Dentro do mesmo processo de teste -> 'Incluir Documento' ->\n"
        "    selecione 'Despacho'. No form inicial marque:\n"
        "      - Texto Inicial: Nenhum\n"
        "      - Nível de Acesso: Restrito\n"
        "    NÃO clique em Confirmar ainda."
    )
    await cap.snapshot("incluir_despacho_form")

    _prompt(
        "Snapshot 3a capturado. Agora clique 'Confirmar' (apenas esse clique\n"
        "    é autorizado — ele apenas abre o editor rich-text, não salva\n"
        "    nada). Espere o editor abrir.\n"
        "    IMPORTANTE: se abrir em POPUP (janela nova do browser), deixe\n"
        "    a janela no foreground antes de continuar — o script vai\n"
        "    capturar a página/frame corrente."
    )
    await cap.snapshot("incluir_despacho_editor", also_frames=True)

    _prompt(
        "Snapshot 3b capturado. FECHE o editor SEM salvar:\n"
        "      - popup: fechar a janela (X) ou Ctrl+W\n"
        "      - iframe: botão Cancelar do editor, ou Esc\n"
        "    Confirme visualmente que o despacho NÃO foi persistido na\n"
        "    árvore do processo de teste."
    )


TARGETS: dict[str, callable] = {
    "iniciar_processo": capture_iniciar_processo,
    "incluir_externo": capture_incluir_externo,
    "incluir_despacho": capture_incluir_despacho,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    # Deferred imports — see module-level note.
    from ufpr_automation.sei.browser import (
        auto_login,
        create_browser_context,
        is_logged_in,
        launch_browser,
        save_session_state,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = Path("ufpr_automation/procedures_data/sei_capture") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("SEI capture: output dir = %s", out_dir)

    pw, browser = await launch_browser(headless=False)
    try:
        context = await create_browser_context(browser, headless=False)
        page = await context.new_page()

        if args.skip_login:
            from ufpr_automation.config.settings import SEI_URL

            logger.info("--skip-login: abrindo %s", SEI_URL)
            await page.goto(SEI_URL, wait_until="domcontentloaded")
            if not await is_logged_in(page):
                _prompt(
                    "Sessão não logada. Faça login MANUAL no SEI que está\n"
                    "    aberto, depois volte aqui e pressione ENTER."
                )
        else:
            ok = await auto_login(page)
            if not ok:
                _prompt(
                    "auto_login() falhou (credenciais, CAPTCHA ou MFA novo).\n"
                    "    Faça login MANUAL no SEI que está aberto e pressione\n"
                    "    ENTER — o script continua a partir daí."
                )

        try:
            await save_session_state(context)
        except Exception as e:
            logger.warning("save_session_state falhou: %s", e)

        cap = CaptureSession(page, out_dir)

        targets = args.targets or list(TARGETS.keys())
        for t in targets:
            fn = TARGETS.get(t)
            if fn is None:
                logger.warning("target desconhecido: %s", t)
                continue
            try:
                await fn(cap)
            except PermissionError as e:
                # Forbidden-click guard fired — abort the whole run so it
                # gets surfaced immediately.
                logger.error("ABORT: forbidden click bloqueado em %s: %s", t, e)
                cap.write_capture_log(extra_notes=f"ABORTED: forbidden click — {e}")
                return 2
            except KeyboardInterrupt:
                logger.warning("interrompido pelo usuário em %s", t)
                cap.write_capture_log(extra_notes="Interrompido pelo usuário.")
                return 130
            except Exception as e:
                logger.error("capture %s falhou: %s", t, e)
                _prompt(
                    f"Erro no target {t}: {e}\n"
                    "    ENTER para tentar o próximo target, Ctrl+C para abortar."
                )

        log_path = cap.write_capture_log()
        logger.info("CAPTURE_LOG.md escrito em %s", log_path)
        print("\n--- Captura concluída ---")
        print(f"Output: {out_dir}")
        print(f"Log:    {log_path}")
        print(
            "Próximo passo: analisar raw/*_elements.json e produzir "
            "sei_selectors.yaml (schema na §5 do SDD)."
        )
    finally:
        try:
            await browser.close()
        finally:
            await pw.stop()

    return 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Capture SEI form DOMs for selector authoring — Marco IV unblock. "
            "See ufpr_automation/SDD_SEI_SELECTOR_CAPTURE.md."
        ),
    )
    p.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Diretório de saída (default: "
            "ufpr_automation/procedures_data/sei_capture/<YYYYMMDD_HHMMSS>)"
        ),
    )
    p.add_argument(
        "--skip-login",
        action="store_true",
        help="Não tentar auto_login; abre SEI_URL e espera login manual.",
    )
    p.add_argument(
        "--targets",
        nargs="*",
        choices=list(TARGETS.keys()),
        default=None,
        help="Subset de forms a capturar (default: todos os 3).",
    )
    return p


def main() -> None:
    args = build_argparser().parse_args()
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
