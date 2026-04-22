#!/usr/bin/env python
"""SEI selector capture driver — non-interactive version of capture_sei_selectors.py.

Unlike the original capture harness, this script drives the navigation itself
(no `input()` / ENTER prompts). It's designed so Claude can iterate: run a
target → read the screenshot → adjust selectors → re-run. The human only
intervenes for auth edge cases (password change, new MFA, CAPTCHA).

Safety is inherited from SEIWriter: every `.click(...)` goes through
`_is_forbidden()` to refuse any selector containing
`assinar` / `enviar` / `protocolar` / `btnAssinar` tokens.

USAGE
-----

    # Log in once (saves session state), screenshot home:
    .venv/Scripts/python.exe scripts/sei_drive.py --target login

    # Subsequent targets reuse saved session:
    .venv/Scripts/python.exe scripts/sei_drive.py --target iniciar_processo
    .venv/Scripts/python.exe scripts/sei_drive.py --target incluir_externo
    .venv/Scripts/python.exe scripts/sei_drive.py --target incluir_despacho

Flags:
    --headless     Run browser headless (default: headed so human can watch)
    --output-dir   Override timestamped output dir

Each target writes to `<out>/raw/<label>.{html,png,_elements.json}` and
appends to `<out>/CAPTURE_LOG.md`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ufpr_automation.sei.writer import _is_forbidden  # noqa: E402
from ufpr_automation.utils.logging import logger  # noqa: E402

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
  const takeOptions = (el) => {
    if (el.tagName !== 'SELECT') return null;
    try {
      return Array.from(el.options).slice(0, 50).map(o => ({
        value: trim(o.value, 80),
        text: trim((o.textContent || '').trim(), 80),
        selected: o.selected,
      }));
    } catch (e) { return null; }
  };
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
    options: takeOptions(el),
  });
  const sel = 'input, select, textarea, button, a[onclick], a[href], img[title]';
  return Array.from(document.querySelectorAll(sel)).map(take);
}
"""


def _safe_name(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", label)[:60]


async def snapshot(page, out_dir: Path, label: str, *, also_frames: bool = False) -> dict:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(label)
    html_path = raw_dir / f"{safe}.html"
    png_path = raw_dir / f"{safe}.png"
    elements_path = raw_dir / f"{safe}_elements.json"

    try:
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
    except Exception as e:
        logger.warning("content() %s: %s", label, e)
        html_path.write_text(f"<!-- {e} -->", encoding="utf-8")

    try:
        await page.screenshot(path=str(png_path), full_page=True)
    except Exception as e:
        logger.warning("screenshot %s: %s", label, e)

    try:
        elements = await page.evaluate(_ENUMERATE_JS)
    except Exception as e:
        logger.warning("enumerate %s: %s", label, e)
        elements = []

    elements_path.write_text(
        json.dumps(elements, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    frame_dumps: list[str] = []
    if also_frames:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            name = frame.name or frame.url or "frame"
            fname = _safe_name(name) or "frame"
            frame_html_path = raw_dir / f"{safe}__frame_{fname}.html"
            try:
                fh = await frame.content()
            except Exception as e:
                logger.warning("frame %s: %s", name, e)
                continue
            frame_html_path.write_text(fh, encoding="utf-8")
            frame_dumps.append(str(frame_html_path.relative_to(out_dir)))

    meta = {
        "label": label,
        "url": page.url,
        "html": str(html_path.relative_to(out_dir)),
        "screenshot": str(png_path.relative_to(out_dir)),
        "elements": str(elements_path.relative_to(out_dir)),
        "element_count": len(elements),
        "frame_dumps": frame_dumps,
        "captured_at": datetime.now().isoformat(),
    }
    logger.info("snapshot %s: %d elementos, %d frames", label, len(elements), len(frame_dumps))
    _append_log(out_dir, meta)
    return meta


def _append_log(out_dir: Path, meta: dict) -> None:
    log_path = out_dir / "capture_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")


async def safe_click(page, selector: str, description: str = "") -> None:
    if _is_forbidden(selector):
        raise PermissionError(f"refused forbidden selector {selector!r} ({description})")
    logger.info("click: %s (%s)", selector, description or "")
    await page.click(selector)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


async def _ensure_logged_in(page, context) -> None:
    """Navigate to SEI_URL and ensure we have a valid session.

    Prefers the saved session (loaded automatically by create_browser_context).
    Falls back to auto_login() only if not logged in.
    """
    from ufpr_automation.config.settings import SEI_URL
    from ufpr_automation.sei.browser import auto_login, is_logged_in, save_session_state

    await page.goto(SEI_URL, wait_until="domcontentloaded")
    if await is_logged_in(page):
        logger.info("ensure_logged_in: saved session is valid, skipping login")
        return
    logger.info("ensure_logged_in: session invalid/absent, attempting auto_login")
    ok = await auto_login(page)
    if not ok or not await is_logged_in(page):
        raise RuntimeError("auto_login failed — saved session state may be stale")
    await save_session_state(context)
    logger.info("ensure_logged_in: auto_login OK, session saved")


async def target_login(page, out_dir: Path, context) -> None:
    """Ensure logged in and snapshot the SEI home page."""
    await _ensure_logged_in(page, context)
    await snapshot(page, out_dir, "home_after_login")
    logger.info("login: OK")


async def target_iniciar_processo(page, out_dir: Path, context) -> None:
    """Navigate to 'Iniciar Processo' form, snapshot the type-picker and a
    representative 'Graduação/Estágios' type form, then cancel out."""
    await _ensure_logged_in(page, context)

    # Step 1: click the "Iniciar Processo" menu item. The menu uses
    # <a> elements with text "Iniciar Processo". Try a few selectors.
    logger.info("iniciar_processo: clicking menu item")
    menu_candidates = [
        'a:has-text("Iniciar Processo")',
        '[title="Iniciar Processo"]',
        'a[href*="procedimento_escolher_tipo"]',
    ]
    clicked = False
    for sel in menu_candidates:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await safe_click(page, sel, "menu Iniciar Processo")
                clicked = True
                break
        except Exception as e:
            logger.debug("menu sel %s: %s", sel, e)
    if not clicked:
        await snapshot(page, out_dir, "iniciar_menu_not_found")
        raise RuntimeError("could not find 'Iniciar Processo' menu link")

    await page.wait_for_load_state("networkidle", timeout=15000)
    await snapshot(page, out_dir, "iniciar_tipo_picker")

    # Step 2: filter by "Estágio" using #txtFiltro and snapshot the matches.
    # #txtFiltro has onkeyup="infraFiltrarMenuBootstrap()" — fill() bypasses
    # keyup events, so type char-by-char instead.
    logger.info("iniciar_processo: filtering by 'Estágio'")
    filt = page.locator("#txtFiltro")
    await filt.click()
    await filt.fill("")
    await filt.press_sequentially("Estágio", delay=40)
    await page.wait_for_timeout(800)
    await snapshot(page, out_dir, "iniciar_tipo_picker_filter_estagio")

    # Step 3: click "Graduação/Ensino Técnico: Estágios não Obrigatórios"
    logger.info("iniciar_processo: clicking 'Estágios não Obrigatórios' type")
    tipo_link = page.locator(
        'a:has-text("Graduação/Ensino Técnico: Estágios não Obrigatórios")'
    ).first
    await tipo_link.wait_for(state="visible", timeout=5000)
    await safe_click(
        page,
        'a:has-text("Graduação/Ensino Técnico: Estágios não Obrigatórios")',
        "tipo Estágios não Obrigatórios",
    )
    await page.wait_for_load_state("networkidle", timeout=15000)
    await snapshot(page, out_dir, "iniciar_form_estagios_nao_obrig")

    # Step 4: select Nível de Acesso = Restrito to expose the "Hipótese Legal"
    # select, then re-snapshot. SEI wraps the radio with a <label> that
    # intercepts pointer events, so clicking the label is the reliable path
    # (also more user-like than .check(force=True)).
    logger.info("iniciar_processo: selecting Nível de Acesso = Restrito")
    try:
        await page.locator("#lblRestrito").click()
        await page.wait_for_timeout(400)
        await snapshot(page, out_dir, "iniciar_form_estagios_restrito")
    except Exception as e:
        logger.warning("restrito toggle failed: %s", e)

    # Step 5: cancel (safe — btnCancelar doesn't trigger any write).
    logger.info("iniciar_processo: cancelling form")
    try:
        await safe_click(page, '[name="btnCancelar"]', "cancelar form iniciar")
        await page.wait_for_load_state("networkidle", timeout=10000)
        await snapshot(page, out_dir, "iniciar_after_cancel")
    except Exception as e:
        logger.warning("cancel failed: %s", e)


async def target_iniciar_processo_save(page, out_dir: Path, context) -> None:
    """Create a real test process in SEI (Estágios não Obrigatórios, Público,
    sandbox marker in Especificação). This produces the process tree page
    we need to navigate for capturing 'Incluir Documento Externo' and
    'Incluir Documento: Despacho' forms.

    The process number + URL is persisted to
    `ufpr_automation/procedures_data/sei_capture/_state/test_process.json`
    so subsequent capture targets can reuse it without recreating.

    SAFETY: clicks #btnSalvar (permitted — creates DRAFT process). Does NOT
    sign or send or protocol anything. The resulting process must be
    manually archived by the human after capture is complete.
    """
    await _ensure_logged_in(page, context)

    # Reach the form same way as target_iniciar_processo.
    await safe_click(page, 'a:has-text("Iniciar Processo")', "menu Iniciar Processo")
    await page.wait_for_load_state("networkidle", timeout=15000)
    filt = page.locator("#txtFiltro")
    await filt.click()
    await filt.fill("")
    await filt.press_sequentially("Estágio", delay=40)
    await page.wait_for_timeout(600)
    await safe_click(
        page,
        'a:has-text("Graduação/Ensino Técnico: Estágios não Obrigatórios")',
        "tipo Estágios não Obrigatórios",
    )
    await page.wait_for_load_state("networkidle", timeout=15000)

    # Fill minimal fields. Nível de Acesso = Público (default policy for
    # Estágios — PII belongs to attached docs, not the process itself).
    marker = f"TESTE CAPTURA SELETORES — {datetime.now():%Y-%m-%d %H:%M}"
    logger.info("iniciar_save: especificação='%s'", marker)
    await page.locator("#txtDescricao").fill(marker)

    # Check Público via its label (radio is intercepted by label overlay).
    await page.locator("#lblPublico").click()
    await page.wait_for_timeout(200)

    # Register dialog handler — SEI's validarCadastro shows `alert()` on
    # errors. Capture the text for debugging; accept/dismiss otherwise.
    dialog_texts: list[str] = []

    async def _dialog(d):
        dialog_texts.append(d.message)
        logger.warning("dialog[%s]: %s", d.type, d.message)
        await d.accept()

    page.on("dialog", _dialog)

    await snapshot(page, out_dir, "iniciar_form_prefilled")

    # Click Salvar.
    logger.info("iniciar_save: clicking #btnSalvar")
    await safe_click(page, "#btnSalvar", "salvar processo de teste")
    # If alert fired, we caught it above; record into audit.
    if dialog_texts:
        logger.error("iniciar_save: Salvar blocked by alerts: %s", dialog_texts)
    await page.wait_for_load_state("networkidle", timeout=20000)
    await snapshot(page, out_dir, "iniciar_after_save")

    # Extract process number from URL or page. SEI puts the process number
    # in the URL as &id_procedimento=... or in the page title / infoTitle.
    url = page.url
    logger.info("iniciar_save: after-save url=%s", url)

    # The process number usually shows up in #divArvoreAcoes or the tree
    # root. Try to extract via JS.
    proc_number = await page.evaluate(
        r"""
        () => {
          // Try the tree root link text: "23075.XXXXXX/XXXX-XX"
          const anchors = document.querySelectorAll('a');
          for (const a of anchors) {
            const m = (a.textContent || '').match(/\d{5}\.\d{6}\/\d{4}-\d{2}/);
            if (m) return m[0];
          }
          // Fallback: look in the document body text
          const m2 = (document.body.innerText || '').match(/\d{5}\.\d{6}\/\d{4}-\d{2}/);
          return m2 ? m2[0] : null;
        }
        """
    )
    logger.info("iniciar_save: detected process number = %s", proc_number)

    # Persist for later targets.
    state_dir = Path("ufpr_automation/procedures_data/sei_capture/_state")
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "test_process.json"
    state_file.write_text(
        json.dumps(
            {
                "process_number": proc_number,
                "url_after_save": url,
                "especificacao": marker,
                "created_at": datetime.now().isoformat(),
                "capture_dir": str(out_dir),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info("iniciar_save: test process state saved to %s", state_file)


# Reference process used for capturing "Incluir Documento" forms.
# Passed in via --process or defaults to MODEL_PROCESS.
# 23075.007317/2026-46 is a modern Estágio process with empresa nº de estágio
# and richer document set — better reference than older processes.
MODEL_PROCESS = "23075.007317/2026-46"


async def _open_process(page, process_number: str) -> None:
    """Navigate to a specific SEI process via #txtPesquisaRapida.

    The field in the header accepts a full process number like
    "23075.066019/2024-26" and navigates directly to the process on submit.
    """
    logger.info("open_process: searching %s", process_number)
    search = page.locator("#txtPesquisaRapida")
    await search.click()
    await search.fill("")
    await search.press_sequentially(process_number, delay=20)
    await search.press("Enter")
    await page.wait_for_load_state("networkidle", timeout=20000)
    url = page.url
    logger.info("open_process: landed on %s", url)


async def target_open_process(page, out_dir: Path, context) -> None:
    """Navigate to the model process and snapshot it (tree + toolbar)."""
    await _ensure_logged_in(page, context)
    await _open_process(page, MODEL_PROCESS)
    await snapshot(page, out_dir, "process_tree_view", also_frames=True)


async def target_incluir_externo(page, out_dir: Path, context) -> None:
    """Open the model process, click 'Incluir Documento' in its toolbar,
    select 'Externo', snapshot the form, and CANCEL without saving."""
    await _ensure_logged_in(page, context)
    await _open_process(page, MODEL_PROCESS)
    await snapshot(page, out_dir, "process_before_incluir", also_frames=True)

    # The "Incluir Documento" link lives in #ifrConteudoVisualizacao and
    # targets ifrVisualizacao (sibling/parent frame). Its href is a direct
    # controlador.php URL — most reliable is to extract the href and
    # navigate the target frame ourselves.
    logger.info("incluir_externo: extracting 'Incluir Documento' href")
    href = None
    for frame in [page.main_frame, *page.frames]:
        try:
            a = frame.locator(
                'xpath=//a[.//img[@title="Incluir Documento"]]'
            ).first
            if await a.count() > 0:
                href = await a.get_attribute("href")
                logger.info(
                    "incluir_externo: found anchor in frame=%s href=%s",
                    frame.name or "(main)",
                    (href or "")[:120],
                )
                break
        except Exception as e:
            logger.debug("frame %s: %s", frame.name, e)
    if not href:
        await snapshot(page, out_dir, "incluir_anchor_not_found", also_frames=True)
        raise RuntimeError("could not find 'Incluir Documento' anchor")

    # Resolve relative href against current page URL.
    from urllib.parse import urljoin

    absolute = urljoin(page.url, href)
    # Find the ifrVisualizacao frame and navigate it directly.
    target_frame = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    if target_frame is None:
        logger.warning("ifrVisualizacao not found; navigating main page")
        await page.goto(absolute, wait_until="networkidle")
    else:
        logger.info("incluir_externo: navigating ifrVisualizacao → %s", absolute[:120])
        await target_frame.goto(absolute, wait_until="networkidle")
    await snapshot(page, out_dir, "documento_escolher_tipo", also_frames=True)

    # Click the "Externo" option in ifrVisualizacao. It's an <a class=ancoraOpcao>
    # with onclick="escolher(-1)" (Externo is always id=-1 in SEI).
    logger.info("incluir_externo: clicking 'Externo' option (escolher(-1))")
    vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    if vf is None:
        raise RuntimeError("ifrVisualizacao not found when clicking Externo")
    externo_link = vf.locator('a.ancoraOpcao', has_text="Externo").first
    await externo_link.wait_for(state="visible", timeout=10000)
    await externo_link.click()
    await page.wait_for_timeout(1500)
    await snapshot(page, out_dir, "incluir_externo_form", also_frames=True)

    # Toggle Nível de Acesso = Restrito via label (radio has overlay) to
    # expose the Hipótese Legal select, then dump its options.
    logger.info("incluir_externo: toggling Restrito to expose Hipótese Legal")
    vf2 = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    try:
        await vf2.locator("#lblRestrito").click()
        await page.wait_for_timeout(500)
        await snapshot(page, out_dir, "incluir_externo_form_restrito", also_frames=True)
        # Dump selHipoteseLegal options via evaluate.
        opts = await vf2.evaluate(
            r"""() => {
              const s = document.querySelector('#selHipoteseLegal');
              if (!s) return null;
              return Array.from(s.options).map(o => ({
                value: o.value,
                text: (o.textContent || '').trim(),
                selected: o.selected,
              }));
            }"""
        )
        if opts is not None:
            (out_dir / "raw" / "selHipoteseLegal_options.json").write_text(
                json.dumps(opts, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.info("incluir_externo: Hipótese Legal options saved (%d)", len(opts))
    except Exception as e:
        logger.warning("restrito/hipotese capture failed: %s", e)

    # Cancel form without saving.
    logger.info("incluir_externo: clicking cancel")
    try:
        await vf2.locator('[name="btnCancelar"]').first.click()
        await page.wait_for_timeout(800)
    except Exception as e:
        logger.warning("cancel failed: %s", e)


async def target_incluir_despacho(page, out_dir: Path, context) -> None:
    """Navigate model process → Incluir Documento → Despacho, capture form
    WITHOUT clicking Confirmar (that opens the editor and creates the
    placeholder document). Cancel out."""
    await _ensure_logged_in(page, context)
    await _open_process(page, MODEL_PROCESS)

    # Extract href of "Incluir Documento" (reused logic).
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
        raise RuntimeError("could not find Incluir Documento anchor")
    from urllib.parse import urljoin

    target_frame = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    absolute = urljoin(page.url, href)
    await target_frame.goto(absolute, wait_until="networkidle")

    # Click Despacho (escolher(5)) directly via JS — selector by text can
    # collide with "Despacho (AGU)", "Despacho Decisório", etc.
    logger.info("incluir_despacho: invoking escolher(5)")
    vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    await vf.evaluate("() => escolher(5)")
    await page.wait_for_timeout(1500)
    await snapshot(page, out_dir, "incluir_despacho_form", also_frames=True)

    # Cancel without clicking Confirmar.
    logger.info("incluir_despacho: clicking cancel")
    try:
        vf2 = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
        await vf2.locator('[name="btnCancelar"]').first.click()
        await page.wait_for_timeout(800)
    except Exception as e:
        logger.warning("cancel failed: %s", e)


async def target_acompanhamento_especial_menu(page, out_dir: Path, context) -> None:
    """Home → left sidebar → 'Acompanhamento Especial' entry.

    Documents where the menu link lives (selector + href) and snapshots the
    list page (all groups + processes under Acompanhamento Especial for the
    current unit). READ-ONLY — just clicks the menu, no form submission.
    """
    await _ensure_logged_in(page, context)
    await snapshot(page, out_dir, "home_sidebar", also_frames=True)

    # Try a few candidate selectors for the sidebar link. SEI's main menu
    # typically renders as <a title="..." href="controlador.php?...">.
    menu_candidates = [
        'a[title="Acompanhamento Especial"]',
        'a:has-text("Acompanhamento Especial")',
        'a[href*="acompanhamento_especial_listar"]',
    ]
    chosen_sel: str | None = None
    chosen_href: str | None = None
    chosen_frame_name: str | None = None
    for frame in [page.main_frame, *page.frames]:
        for sel in menu_candidates:
            try:
                loc = frame.locator(sel).first
                if await loc.count() > 0:
                    chosen_sel = sel
                    chosen_href = await loc.get_attribute("href")
                    chosen_frame_name = frame.name or "(main)"
                    logger.info(
                        "acompanhamento_menu: found sel=%s frame=%s href=%s",
                        sel,
                        chosen_frame_name,
                        (chosen_href or "")[:120],
                    )
                    break
            except Exception as e:
                logger.debug("sel %s in %s: %s", sel, frame.name, e)
        if chosen_sel is not None:
            break

    if chosen_sel is None:
        await snapshot(page, out_dir, "menu_link_not_found", also_frames=True)
        raise RuntimeError("'Acompanhamento Especial' menu link not found")

    # Persist discovered menu entry for future reference.
    (out_dir / "raw" / "menu_entry.json").write_text(
        json.dumps(
            {
                "selector": chosen_sel,
                "href": chosen_href,
                "frame": chosen_frame_name,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Click it and snapshot the list page.
    logger.info("acompanhamento_menu: clicking the link")
    # The link is in a frame — click via locator on the matching frame.
    target_frame = next(
        (f for f in page.frames if (f.name or "(main)") == chosen_frame_name),
        page.main_frame,
    )
    await target_frame.locator(chosen_sel).first.click()
    await page.wait_for_load_state("networkidle", timeout=15000)
    await snapshot(page, out_dir, "acompanhamento_especial_lista", also_frames=True)

    # If the list page has a "Novo" / "Listar Grupos" toolbar, capture those
    # affordances for documentation (no click).
    try:
        btns = await page.evaluate(
            r"""() => {
              const targets = document.querySelectorAll(
                'input[type="button"], button, a[onclick], a[href*="acompanhamento"]'
              );
              return Array.from(targets).slice(0, 40).map(el => ({
                tag: el.tagName,
                id: el.id || null,
                name: el.name || null,
                value: el.value || null,
                text: (el.innerText || el.textContent || '').trim().slice(0, 80),
                href: el.getAttribute('href'),
                onclick: el.getAttribute('onclick'),
                title: el.getAttribute('title'),
              }));
            }"""
        )
        (out_dir / "raw" / "lista_affordances.json").write_text(
            json.dumps(btns, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("acompanhamento_menu: %d affordances on list page", len(btns))
    except Exception as e:
        logger.warning("affordance dump failed: %s", e)


async def target_acompanhamento_especial_processo(page, out_dir: Path, context) -> None:
    """Open MODEL_PROCESS → process toolbar 'Acompanhamento Especial' button →
    snapshot the create/edit form → click CANCEL (never Salvar).

    The toolbar icon in SEI typically has title='Acompanhamento Especial' and
    lives in ifrConteudoVisualizacao; it opens a form in ifrVisualizacao.
    """
    await _ensure_logged_in(page, context)
    await _open_process(page, MODEL_PROCESS)
    await snapshot(page, out_dir, "process_before_acompanhamento", also_frames=True)

    # Find the toolbar icon. SEI icons are <a> wrapping <img title="...">.
    candidates_xpath = [
        'xpath=//a[.//img[@title="Acompanhamento Especial"]]',
        'xpath=//a[contains(@href, "acompanhamento_especial_cadastrar")]',
        'xpath=//a[contains(@onclick, "acompanhamento_especial")]',
    ]
    found_frame = None
    found_sel = None
    found_href = None
    for frame in [page.main_frame, *page.frames]:
        for sel in candidates_xpath:
            try:
                loc = frame.locator(sel).first
                if await loc.count() > 0:
                    found_frame = frame
                    found_sel = sel
                    found_href = await loc.get_attribute("href")
                    logger.info(
                        "acompanhamento_processo: toolbar icon sel=%s frame=%s href=%s",
                        sel,
                        frame.name or "(main)",
                        (found_href or "")[:120],
                    )
                    break
            except Exception as e:
                logger.debug("sel %s frame %s: %s", sel, frame.name, e)
        if found_sel is not None:
            break

    if found_sel is None:
        await snapshot(page, out_dir, "toolbar_icon_not_found", also_frames=True)
        raise RuntimeError("'Acompanhamento Especial' toolbar icon not found on process")

    # Persist discovered toolbar entry.
    (out_dir / "raw" / "toolbar_entry.json").write_text(
        json.dumps(
            {
                "selector": found_sel,
                "href": found_href,
                "frame": (found_frame.name or "(main)") if found_frame else None,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Navigate target frame (ifrVisualizacao) directly to href, same pattern as
    # target_incluir_externo — avoids click side-effects on the container frame.
    from urllib.parse import urljoin

    if found_href is None:
        # Fallback: click the icon (some icons use JS-only navigation)
        await found_frame.locator(found_sel).first.click()
        await page.wait_for_timeout(1500)
    else:
        absolute = urljoin(page.url, found_href)
        vis_frame = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
        if vis_frame is None:
            await page.goto(absolute, wait_until="networkidle")
        else:
            logger.info(
                "acompanhamento_processo: navigating ifrVisualizacao → %s", absolute[:120]
            )
            await vis_frame.goto(absolute, wait_until="networkidle")
    await snapshot(page, out_dir, "acompanhamento_especial_form", also_frames=True)

    # The icon opens `acompanhamento_gerenciar` — a LIST page for this process
    # (existing entries + Adicionar/Excluir buttons). To reach the actual
    # create/edit form, we need to click Adicionar → `acompanhamento_cadastrar`.
    vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None) or page.main_frame
    try:
        list_info = await vf.evaluate(
            r"""() => {
              const btns = document.querySelectorAll('input[type="button"], button');
              return Array.from(btns).map(b => ({
                id: b.id || null,
                value: b.value || null,
                text: (b.innerText || b.textContent || '').trim().slice(0, 60),
                onclick: b.getAttribute('onclick'),
              }));
            }"""
        )
        (out_dir / "raw" / "list_buttons.json").write_text(
            json.dumps(list_info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("list dump failed: %s", e)

    # Click Adicionar — its onclick does `location.href=...acompanhamento_cadastrar...`.
    # Grab the href from onclick attribute and navigate directly (avoid
    # relying on click-triggered navigation timing).
    adicionar_href = None
    try:
        adicionar_href = await vf.evaluate(
            r"""() => {
              const b = document.getElementById('btnAdicionar');
              if (!b) return null;
              const m = (b.getAttribute('onclick') || '').match(/location\.href='([^']+)'/);
              return m ? m[1] : null;
            }"""
        )
    except Exception as e:
        logger.warning("adicionar href extract failed: %s", e)

    if adicionar_href:
        from urllib.parse import urljoin

        absolute_add = urljoin(page.url, adicionar_href)
        logger.info("acompanhamento_processo: navigating to form → %s", absolute_add[:120])
        vis_frame2 = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
        if vis_frame2 is None:
            await page.goto(absolute_add, wait_until="networkidle")
        else:
            await vis_frame2.goto(absolute_add, wait_until="networkidle")
        await snapshot(page, out_dir, "acompanhamento_especial_cadastrar_form", also_frames=True)
    else:
        logger.warning("acompanhamento_processo: Adicionar href not found — skipping form capture")

    # Now dump form affordances. Look for: grupo dropdown, new-group button,
    # descrição textarea, and Salvar/Cancelar buttons.
    vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None) or page.main_frame
    try:
        form_info = await vf.evaluate(
            r"""() => {
              const out = { selects: [], textareas: [], buttons: [], inputs: [] };
              for (const s of document.querySelectorAll('select')) {
                out.selects.push({
                  id: s.id || null,
                  name: s.name || null,
                  options: Array.from(s.options).slice(0, 50).map(o => ({
                    value: o.value,
                    text: (o.textContent || '').trim().slice(0, 80),
                  })),
                });
              }
              for (const t of document.querySelectorAll('textarea')) {
                out.textareas.push({
                  id: t.id || null,
                  name: t.name || null,
                  rows: t.rows,
                  placeholder: t.placeholder || null,
                });
              }
              for (const b of document.querySelectorAll(
                'input[type="button"], input[type="submit"], button'
              )) {
                out.buttons.push({
                  id: b.id || null,
                  name: b.name || null,
                  value: b.value || null,
                  text: (b.innerText || b.textContent || '').trim().slice(0, 60),
                  onclick: b.getAttribute('onclick'),
                });
              }
              for (const i of document.querySelectorAll(
                'input[type="text"], input[type="hidden"]'
              )) {
                out.inputs.push({
                  id: i.id || null,
                  name: i.name || null,
                  type: i.type,
                  placeholder: i.placeholder || null,
                });
              }
              // Images/anchors with onclick — SEI often uses <img onclick=...>
              // for modal triggers (e.g. Novo Grupo de Acompanhamento).
              out.image_actions = [];
              for (const img of document.querySelectorAll('img[onclick]')) {
                out.image_actions.push({
                  id: img.id || null,
                  title: img.title || null,
                  alt: img.alt || null,
                  onclick: img.getAttribute('onclick'),
                  src: img.getAttribute('src'),
                });
              }
              out.anchor_actions = [];
              for (const a of document.querySelectorAll('a[onclick]')) {
                out.anchor_actions.push({
                  id: a.id || null,
                  title: a.title || null,
                  text: (a.innerText || a.textContent || '').trim().slice(0, 60),
                  onclick: a.getAttribute('onclick'),
                  href: a.getAttribute('href'),
                });
              }
              return out;
            }"""
        )
        (out_dir / "raw" / "form_affordances.json").write_text(
            json.dumps(form_info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(
            "acompanhamento_processo: form — selects=%d textareas=%d buttons=%d inputs=%d",
            len(form_info["selects"]),
            len(form_info["textareas"]),
            len(form_info["buttons"]),
            len(form_info["inputs"]),
        )
    except Exception as e:
        logger.warning("form dump failed: %s", e)

    # Cancel the form — NEVER Salvar (that would create a real Acompanhamento
    # Especial entry on this process).
    logger.info("acompanhamento_processo: clicking CANCEL (never Salvar)")
    try:
        cancel_loc = vf.locator('[name="btnCancelar"], #btnCancelar, button:has-text("Cancelar")').first
        if await cancel_loc.count() > 0:
            await cancel_loc.click()
            await page.wait_for_timeout(800)
            await snapshot(page, out_dir, "after_cancel", also_frames=True)
        else:
            logger.warning("cancel button not found — closing via navigation back")
            await page.go_back()
            await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception as e:
        logger.warning("cancel failed: %s", e)


async def target_acompanhamento_novo_grupo_modal(page, out_dir: Path, context) -> None:
    """Reach the cadastrar form, click the '+' icon (#imgNovoGrupoAcompanhamento)
    to open the 'Novo Grupo de Acompanhamento' modal, then snapshot the modal
    DOM (fields + buttons). CLOSES without saving — never creates a real group.

    The modal opens via infraAbrirJanelaModal(url, 700, 300) — it's a
    dialog inside the same page DOM, not a popup window.
    """
    await _ensure_logged_in(page, context)
    await _open_process(page, MODEL_PROCESS)

    # Reach the cadastrar form (re-use the same nav pattern).
    vis_frame = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    cv_frame = next((f for f in page.frames if f.name == "ifrConteudoVisualizacao"), None)
    if cv_frame is None:
        raise RuntimeError("ifrConteudoVisualizacao not found")
    toolbar_a = cv_frame.locator(
        'xpath=//a[.//img[@title="Acompanhamento Especial"]]'
    ).first
    await toolbar_a.wait_for(state="visible", timeout=10000)
    toolbar_href = await toolbar_a.get_attribute("href")
    if not toolbar_href:
        raise RuntimeError("toolbar icon has no href")
    from urllib.parse import urljoin

    absolute = urljoin(page.url, toolbar_href)
    logger.info("novo_grupo_modal: navigating to gerenciar → %s", absolute[:120])
    if vis_frame is None:
        await page.goto(absolute, wait_until="networkidle")
    else:
        await vis_frame.goto(absolute, wait_until="networkidle")

    # Now we're on gerenciar (list page). Extract Adicionar href and navigate
    # to cadastrar.
    vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None) or page.main_frame
    adicionar_href = await vf.evaluate(
        r"""() => {
          const b = document.getElementById('btnAdicionar');
          if (!b) return null;
          const m = (b.getAttribute('onclick') || '').match(/location\.href='([^']+)'/);
          return m ? m[1] : null;
        }"""
    )
    if not adicionar_href:
        raise RuntimeError("btnAdicionar not found on gerenciar page")
    absolute_add = urljoin(page.url, adicionar_href)
    vis_frame2 = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    if vis_frame2 is None:
        await page.goto(absolute_add, wait_until="networkidle")
    else:
        await vis_frame2.goto(absolute_add, wait_until="networkidle")
    await snapshot(page, out_dir, "cadastrar_form_before_modal", also_frames=True)

    # Click the '+' icon. cadastrarGrupoAcompanhamento() calls
    # infraAbrirJanelaModal — the modal is injected into the SAME page DOM
    # (no new window). Capture DOM state after click.
    vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None) or page.main_frame
    logger.info("novo_grupo_modal: clicking #imgNovoGrupoAcompanhamento")
    try:
        await vf.locator("#imgNovoGrupoAcompanhamento").click()
    except Exception as e:
        logger.error("click failed: %s", e)
        await snapshot(page, out_dir, "modal_click_failed", also_frames=True)
        raise

    # The modal may open in an iframe within the page, or as a div overlay.
    # Wait a bit for it to render, then snapshot + dump all new frames.
    await page.wait_for_timeout(2000)
    await snapshot(page, out_dir, "after_novo_grupo_click", also_frames=True)

    # Try to find the modal content. SEI's infraAbrirJanelaModal typically
    # injects an iframe (e.g. id="modal-body" or similar) inside a dialog.
    # Enumerate all frames and their URLs — the new one should have
    # acao=grupo_acompanhamento_cadastrar.
    frame_info = []
    for frame in page.frames:
        frame_info.append(
            {
                "name": frame.name,
                "url": frame.url,
                "is_main": frame is page.main_frame,
            }
        )
    (out_dir / "raw" / "all_frames_after_modal.json").write_text(
        json.dumps(frame_info, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("novo_grupo_modal: %d total frames after click", len(frame_info))

    # Find the modal frame — URL contains grupo_acompanhamento_cadastrar.
    modal_frame = next(
        (f for f in page.frames if "grupo_acompanhamento_cadastrar" in (f.url or "")),
        None,
    )
    if modal_frame is None:
        # Maybe the modal is not a frame but an overlay div in the same page —
        # search the DOM for elements with `grupo_acompanhamento` in any attr.
        logger.warning(
            "novo_grupo_modal: no frame matched grupo_acompanhamento_cadastrar; "
            "the modal may be inline. Dumping ifrVisualizacao + main_frame for inspection."
        )
        # Dump affordances from whatever is currently visible in vf.
        modal_frame = vf

    try:
        modal_form = await modal_frame.evaluate(
            r"""() => {
              const out = {
                url: location.href,
                title: document.title,
                inputs: [],
                textareas: [],
                selects: [],
                buttons: [],
                all_named_ids: [],
              };
              for (const i of document.querySelectorAll('input')) {
                out.inputs.push({
                  id: i.id || null,
                  name: i.name || null,
                  type: i.type,
                  value: i.value || null,
                  placeholder: i.placeholder || null,
                  maxlength: i.maxLength > 0 ? i.maxLength : null,
                });
              }
              for (const t of document.querySelectorAll('textarea')) {
                out.textareas.push({
                  id: t.id || null,
                  name: t.name || null,
                  rows: t.rows,
                });
              }
              for (const s of document.querySelectorAll('select')) {
                out.selects.push({ id: s.id, name: s.name, options: s.options.length });
              }
              for (const b of document.querySelectorAll(
                'input[type="button"], input[type="submit"], button'
              )) {
                out.buttons.push({
                  id: b.id || null,
                  name: b.name || null,
                  value: b.value || null,
                  text: (b.innerText || b.textContent || '').trim().slice(0, 60),
                  onclick: b.getAttribute('onclick'),
                  type: b.type || null,
                });
              }
              // Any element whose id includes 'rupo' (Grupo) for debug.
              for (const el of document.querySelectorAll('[id*="rupo"], [name*="rupo"]')) {
                out.all_named_ids.push({
                  tag: el.tagName,
                  id: el.id || null,
                  name: el.name || null,
                });
              }
              return out;
            }"""
        )
        (out_dir / "raw" / "novo_grupo_modal_form.json").write_text(
            json.dumps(modal_form, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(
            "novo_grupo_modal: modal url=%s inputs=%d textareas=%d buttons=%d",
            modal_form["url"][:80],
            len(modal_form["inputs"]),
            len(modal_form["textareas"]),
            len(modal_form["buttons"]),
        )
    except Exception as e:
        logger.warning("modal form dump failed: %s", e)

    # Try to close the modal without saving. Common SEI patterns:
    #   - button "Cancelar" inside the modal
    #   - 'X' close icon on the dialog
    # Fall back to navigating away (go_back) which discards the modal.
    try:
        cancel_btn = modal_frame.locator(
            '#btnCancelar, [name="btnCancelar"], button:has-text("Cancelar")'
        ).first
        if await cancel_btn.count() > 0:
            logger.info("novo_grupo_modal: clicking modal Cancelar")
            await cancel_btn.click()
            await page.wait_for_timeout(800)
        else:
            logger.info("novo_grupo_modal: no Cancelar — pressing Escape")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
    except Exception as e:
        logger.warning("modal close failed: %s", e)
    await snapshot(page, out_dir, "after_modal_close", also_frames=True)


async def target_ae_keyword_search(page, out_dir: Path, context) -> None:
    """Navigate to Acompanhamento Especial list → locate 'Palavras-chave para
    pesquisa:' input → submit a real search (default keyword `GRR20223876`,
    override via env `AE_SEARCH_KEYWORD`) → snapshot the results table and
    dump its row/cell structure.

    Purpose: capture the selectors needed by
    ``SEIClient.find_in_acompanhamento_especial`` so the cascade in
    ``graph/nodes.py:consultar_sei`` can try AE before the generic pesquisa
    rápida. READ-ONLY — a search does not mutate state.
    """
    import os

    keyword = os.getenv("AE_SEARCH_KEYWORD", "GRR20223876").strip()
    logger.info("ae_keyword_search: keyword=%s", keyword)

    await _ensure_logged_in(page, context)

    # Reuse the menu-navigation logic: find the 'Acompanhamento Especial' link
    # in any frame, save its selector metadata, then click it.
    menu_candidates = [
        'a[title="Acompanhamento Especial"]',
        'a:has-text("Acompanhamento Especial")',
        'a[href*="acompanhamento_especial_listar"]',
    ]
    chosen_sel = None
    chosen_frame = None
    for frame in [page.main_frame, *page.frames]:
        for sel in menu_candidates:
            try:
                loc = frame.locator(sel).first
                if await loc.count() > 0:
                    chosen_sel = sel
                    chosen_frame = frame
                    break
            except Exception:
                pass
        if chosen_sel is not None:
            break
    if chosen_sel is None:
        await snapshot(page, out_dir, "ae_menu_not_found", also_frames=True)
        raise RuntimeError("'Acompanhamento Especial' menu link not found")

    logger.info(
        "ae_keyword_search: clicking menu sel=%s frame=%s",
        chosen_sel,
        chosen_frame.name or "(main)",
    )
    await chosen_frame.locator(chosen_sel).first.click()
    await page.wait_for_load_state("networkidle", timeout=15000)
    await snapshot(page, out_dir, "ae_lista_before_search", also_frames=True)

    # Find the frame that actually holds the list page. SEI typically renders
    # it inside ifrVisualizacao (or ifrConteudoVisualizacao). We look for the
    # input whose label includes "Palavras-chave" or a name matching `txtPalavra`.
    search_frame = None
    search_input_sel = None
    for frame in [page.main_frame, *page.frames]:
        try:
            probe = await frame.evaluate(
                r"""() => {
                  // Find an input whose <label> or adjacent text mentions 'Palavra'.
                  const inputs = Array.from(document.querySelectorAll(
                    'input[type="text"], input:not([type])'
                  ));
                  for (const inp of inputs) {
                    let lbl = '';
                    if (inp.id) {
                      const l = document.querySelector(`label[for="${inp.id.replace(/"/g,'\\"')}"]`);
                      if (l) lbl = (l.innerText || l.textContent || '').trim();
                    }
                    if (!lbl) {
                      let p = inp.parentElement;
                      while (p && p.tagName !== 'LABEL' && p !== document.body) p = p.parentElement;
                      if (p && p.tagName === 'LABEL') lbl = (p.innerText || '').trim();
                    }
                    const name = inp.name || '';
                    const id = inp.id || '';
                    const hit = (
                      /palavra/i.test(lbl) ||
                      /palavra/i.test(name) ||
                      /palavra/i.test(id)
                    );
                    if (hit) {
                      return {
                        id: id || null,
                        name: name || null,
                        placeholder: inp.getAttribute('placeholder') || null,
                        label: lbl || null,
                      };
                    }
                  }
                  return null;
                }"""
            )
        except Exception as e:
            logger.debug("frame %s probe: %s", frame.name, e)
            continue
        if probe:
            search_frame = frame
            # Prefer #id, fallback to [name=...].
            if probe.get("id"):
                search_input_sel = f'#{probe["id"]}'
            elif probe.get("name"):
                search_input_sel = f'input[name="{probe["name"]}"]'
            logger.info(
                "ae_keyword_search: found input in frame=%s label=%r sel=%s",
                frame.name or "(main)",
                probe.get("label"),
                search_input_sel,
            )
            # Persist the probe for debugging.
            (out_dir / "raw" / "ae_palavras_input.json").write_text(
                json.dumps(probe, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            break

    if search_frame is None or search_input_sel is None:
        await snapshot(page, out_dir, "ae_input_not_found", also_frames=True)
        raise RuntimeError("'Palavras-chave para pesquisa:' input not found")

    # Fill and submit. Common SEI patterns for submit: Enter keypress, or a
    # sibling <input type="button"/button> with value/text "Pesquisar".
    logger.info("ae_keyword_search: filling %s with %r", search_input_sel, keyword)
    await search_frame.locator(search_input_sel).first.click()
    await search_frame.locator(search_input_sel).first.fill("")
    await search_frame.locator(search_input_sel).first.press_sequentially(keyword, delay=20)
    await snapshot(page, out_dir, "ae_lista_after_fill", also_frames=True)

    # Look for a Pesquisar button nearby first; fall back to Enter.
    submit_sel = None
    for cand in [
        'input[name="btnPesquisar"]',
        'button[name="btnPesquisar"]',
        '#btnPesquisar',
        'input[value="Pesquisar"]',
        'button:has-text("Pesquisar")',
    ]:
        try:
            if await search_frame.locator(cand).first.count() > 0:
                submit_sel = cand
                break
        except Exception:
            pass

    if submit_sel:
        logger.info("ae_keyword_search: clicking submit sel=%s", submit_sel)
        await search_frame.locator(submit_sel).first.click()
    else:
        logger.info("ae_keyword_search: no Pesquisar button found — pressing Enter")
        await search_frame.locator(search_input_sel).first.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=15000)
    await snapshot(page, out_dir, "ae_lista_results", also_frames=True)

    # Dump the results table structure: table.infraTable rows + cells.
    try:
        table_info = await search_frame.evaluate(
            r"""() => {
              const tables = Array.from(document.querySelectorAll('table'));
              const picked = tables
                .map(t => ({
                  className: t.className || '',
                  id: t.id || '',
                  rowCount: t.rows.length,
                  headers: t.rows[0]
                    ? Array.from(t.rows[0].cells).map(c => (c.innerText || '').trim().slice(0, 40))
                    : [],
                  sampleRow: t.rows[1]
                    ? Array.from(t.rows[1].cells).map(c => (c.innerText || '').trim().slice(0, 60))
                    : null,
                }))
                .filter(x => x.rowCount > 0);
              return picked;
            }"""
        )
        (out_dir / "raw" / "ae_results_tables.json").write_text(
            json.dumps(table_info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("ae_keyword_search: %d tables on results page", len(table_info))
    except Exception as e:
        logger.warning("results table dump failed: %s", e)

    # Also dump any anchors inside tables — process links are typically
    # <a href="controlador.php?acao=...&id_procedimento=...">NUM</a>.
    try:
        anchors = await search_frame.evaluate(
            r"""() => {
              const anchors = Array.from(document.querySelectorAll('table a[href]'));
              return anchors.slice(0, 30).map(a => ({
                text: (a.innerText || '').trim().slice(0, 80),
                href: a.getAttribute('href'),
                onclick: a.getAttribute('onclick'),
              }));
            }"""
        )
        (out_dir / "raw" / "ae_results_anchors.json").write_text(
            json.dumps(anchors, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("ae_keyword_search: %d anchors dumped", len(anchors))
    except Exception as e:
        logger.warning("anchor dump failed: %s", e)


TARGETS = {
    "login": target_login,
    "iniciar_processo": target_iniciar_processo,
    "iniciar_processo_save": target_iniciar_processo_save,
    "open_process": target_open_process,
    "incluir_externo": target_incluir_externo,
    "incluir_despacho": target_incluir_despacho,
    "despacho_editor": None,  # set below after defining the fn
    "acompanhamento_especial_menu": target_acompanhamento_especial_menu,
    "acompanhamento_especial_processo": target_acompanhamento_especial_processo,
    "acompanhamento_novo_grupo_modal": target_acompanhamento_novo_grupo_modal,
    "ae_keyword_search": target_ae_keyword_search,
}


def _load_test_process_state() -> dict:
    state_file = Path(
        "ufpr_automation/procedures_data/sei_capture/_state/test_process.json"
    )
    if not state_file.exists():
        raise FileNotFoundError(
            "Test process state missing. Run --target iniciar_processo_save first."
        )
    return json.loads(state_file.read_text(encoding="utf-8"))


async def target_despacho_editor(page, out_dir: Path, context) -> None:
    """Inside the existing test process, click Incluir Documento → Despacho,
    fill minimal fields (Texto Inicial = Nenhum, Nível de Acesso = Público),
    click Salvar, and capture the rich-text editor DOM that SEI opens
    (TinyMCE/CKEditor, possibly in a popup window).

    This leaves an EMPTY despacho draft in the test process. The human must
    delete the draft after capture is complete (click the despacho in the
    tree → '×' Excluir).
    """
    state = _load_test_process_state()
    proc_num = state["process_number"]
    logger.info("despacho_editor: using test process %s", proc_num)

    await _ensure_logged_in(page, context)
    await _open_process(page, proc_num)
    await snapshot(page, out_dir, "test_process_tree_view", also_frames=True)

    # Extract Incluir Documento href (same logic as target_incluir_externo).
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
        raise RuntimeError("Incluir Documento anchor not found")
    from urllib.parse import urljoin

    absolute = urljoin(page.url, href)
    target_frame = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    if target_frame is None:
        await page.goto(absolute, wait_until="networkidle")
    else:
        await target_frame.goto(absolute, wait_until="networkidle")
    await snapshot(page, out_dir, "documento_escolher_tipo", also_frames=True)

    # Click Despacho (escolher(5)).
    vf = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    if vf is None:
        vf = page.main_frame
    logger.info("despacho_editor: invoking escolher(5)")
    await vf.evaluate("() => escolher(5)")
    await page.wait_for_timeout(1500)
    await snapshot(page, out_dir, "despacho_initial_form", also_frames=True)

    # Fill minimum fields: Texto Inicial = Nenhum, Nível de Acesso = Público.
    vf2 = next((f for f in page.frames if f.name == "ifrVisualizacao"), None)
    if vf2 is None:
        vf2 = page.main_frame
    try:
        await vf2.locator("#lblNenhum").click()
    except Exception as e:
        logger.warning("lblNenhum click failed: %s", e)
    try:
        await vf2.locator("#lblPublico").click()
    except Exception as e:
        logger.warning("lblPublico click failed: %s", e)
    await page.wait_for_timeout(200)
    await snapshot(page, out_dir, "despacho_initial_form_filled", also_frames=True)

    # Register dialog handler before saving.
    dialog_texts: list[str] = []

    async def _dialog(d):
        dialog_texts.append(d.message)
        logger.warning("dialog[%s]: %s", d.type, d.message)
        await d.accept()

    page.on("dialog", _dialog)

    # Click Salvar in the ifrVisualizacao frame.
    # NOTE: Saving a Despacho DOES create a draft document in the process.
    # We accept this artifact — user will delete the empty draft after capture.
    logger.info("despacho_editor: clicking #btnSalvar (Confirmar/Salvar)")
    btn = vf2.locator("#btnSalvar").first
    # Playwright may open a popup here — wait for both options.
    popup = None
    try:
        async with context.expect_page(timeout=5000) as popup_info:
            await btn.click()
        popup = await popup_info.value
        logger.info("despacho_editor: editor opened in POPUP window: %s", popup.url)
    except Exception:
        logger.info("despacho_editor: no popup detected; editor may be inline")
        await page.wait_for_timeout(2000)

    if popup is not None:
        await popup.wait_for_load_state("networkidle", timeout=20000)
        # Snapshot the popup page.
        popup_html = await popup.content()
        (out_dir / "raw" / "despacho_editor_popup.html").write_text(
            popup_html, encoding="utf-8"
        )
        try:
            await popup.screenshot(
                path=str(out_dir / "raw" / "despacho_editor_popup.png"),
                full_page=True,
            )
        except Exception as e:
            logger.warning("popup screenshot failed: %s", e)
        # Dump frame HTML (editor is commonly inside an iframe of the popup).
        for frame in popup.frames:
            if frame is popup.main_frame:
                continue
            fname = _safe_name(frame.name or frame.url or "frame")
            try:
                fh = await frame.content()
                (out_dir / "raw" / f"despacho_editor_popup__frame_{fname}.html").write_text(
                    fh, encoding="utf-8"
                )
            except Exception as e:
                logger.warning("popup frame %s: %s", frame.name, e)
    else:
        await snapshot(page, out_dir, "despacho_editor_inline", also_frames=True)

    if dialog_texts:
        logger.error("despacho_editor: dialogs seen: %s", dialog_texts)


# Register post-definition.
TARGETS["despacho_editor"] = target_despacho_editor


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    from ufpr_automation.sei.browser import create_browser_context, launch_browser

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = Path("ufpr_automation/procedures_data/sei_capture") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("SEI drive: target=%s output=%s", args.target, out_dir)

    pw, browser = await launch_browser(headless=args.headless)
    try:
        context = await create_browser_context(browser, headless=args.headless)
        page = await context.new_page()

        target_fn = TARGETS.get(args.target)
        if target_fn is None:
            logger.error("unknown target %s. available: %s", args.target, list(TARGETS))
            return 2

        try:
            await target_fn(page, out_dir, context)
        except PermissionError as e:
            logger.error("ABORT forbidden click: %s", e)
            return 2

        print(f"\n--- target {args.target} OK ---")
        print(f"Output: {out_dir}")
    finally:
        try:
            await browser.close()
        finally:
            await pw.stop()
    return 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEI non-interactive capture driver")
    p.add_argument("--target", required=True, choices=sorted(TARGETS.keys()))
    p.add_argument("--output-dir", type=str, default=None)
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless (default: headed so user can watch)",
    )
    return p


def main() -> int:
    args = build_argparser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
