"""Scraper do Moodle UFPR Aberta.

Fluxo:
  1. login (browser.auto_login)
  2. abre course/view.php?id=<COURSE_ID>
  3. enumera seções (blocos)
  4. para cada bloco:
       - salva HTML da página da seção
       - para cada atividade: visita, salva HTML, baixa recursos (PDFs etc.)
  5. retorna estrutura dict { bloco_idx -> { titulo, atividades:[{nome, url, html_path, resources:[...]}] } }

Raw dump vai para RAW_DIR (G:/Meu Drive/ufpr_rag/docs/ainda_n_ingeridos/ufpr_aberta/).
Markdown estruturado (BLOCO 1 e 3) e responsabilidade do __main__.py — este
modulo so captura material bruto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.config.settings import UFPR_ABERTA_URL
from ufpr_automation.utils.logging import logger

DEFAULT_COURSE_ID = 9  # "Conheça o SIGA!"
RAW_ROOT = Path(r"G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\ufpr_aberta")


def _slug(text: str, maxlen: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "_", text)
    return text[:maxlen] or "sem_titulo"


@dataclass
class Resource:
    name: str
    url: str
    local_path: str | None = None


@dataclass
class Activity:
    name: str
    url: str
    mod_type: str = ""  # resource | page | url | folder | forum | ...
    html_path: str | None = None
    text: str = ""
    resources: list[Resource] = field(default_factory=list)


@dataclass
class Block:
    index: int
    title: str
    summary_html: str = ""
    activities: list[Activity] = field(default_factory=list)


def _raw_dir_for_block(block: Block) -> Path:
    d = RAW_ROOT / f"bloco_{block.index}_{_slug(block.title)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _extract_blocks(page: Page, course_url: str) -> list[Block]:
    """Tema format_tiles: home do curso mostra tiles; atividades só aparecem
    visitando ?id=<cid>&section=<N>. Estratégia:
      1. ler títulos dos tiles (<ul#multi_section_tiles> <h3>)
      2. visitar cada seção e enumerar .activity / a.aalink
    """
    blocks: list[Block] = []
    tiles = page.locator("ul#multi_section_tiles li.tile.tile-clickable")
    n_tiles = await tiles.count()
    logger.info("UFPR Aberta: %d tiles (blocos) encontrados", n_tiles)

    tile_info: list[tuple[str, str]] = []  # (title, section_url)
    for i in range(n_tiles):
        t = tiles.nth(i)
        title_loc = t.locator("h3").first
        title = (await title_loc.inner_text()).strip() if await title_loc.count() else f"tile_{i}"
        link_loc = t.locator("a.tile-link, a[href*='section=']").first
        section_url = ""
        if await link_loc.count():
            href = await link_loc.get_attribute("href")
            if href:
                section_url = href if href.startswith("http") else f"{UFPR_ABERTA_URL.rstrip('/')}/{href.lstrip('/')}"
        # fallback: deriva pelo data-section
        if not section_url:
            sec_num = await t.get_attribute("data-section")
            if sec_num:
                section_url = f"{course_url}&section={sec_num}"
        tile_info.append((title, section_url))

    for idx, (title, sec_url) in enumerate(tile_info, start=1):
        block = Block(index=idx, title=title)
        if not sec_url:
            logger.warning("Bloco '%s' sem URL de seção — pulando atividades", title)
            blocks.append(block)
            continue
        try:
            await page.goto(sec_url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=15000)
            # format_tiles carrega atividades via JS após load — espera um pouco
            await page.wait_for_timeout(2500)
        except Exception as e:
            logger.warning("Falha ao abrir seção %s: %s", sec_url, e)
            blocks.append(block)
            continue

        # salva HTML da página da seção para debug + authoring
        out = _raw_dir_for_block(block)
        (out / "_section_page.html").write_text(await page.content(), encoding="utf-8")

        # summary da seção
        summary = page.locator(".section .summary, .section_availability, .course-section .summary").first
        if await summary.count():
            block.summary_html = await summary.inner_html()

        # atividades — format_tiles renderiza em ul.format-tiles-cm-list.subtiles
        # dentro de #region-main. NÃO usar courseindex (sidebar lista o curso todo).
        acts = page.locator(
            "#region-main a.cm-link, #region-main li.activity a.aalink"
        )
        an = await acts.count()
        for j in range(an):
            a = acts.nth(j)
            href = await a.get_attribute("href")
            if not href:
                continue
            name_loc = a.locator("span.instancename").first
            if await name_loc.count():
                name = (await name_loc.inner_text()).strip()
            else:
                name = (await a.inner_text()).strip()
            # remove sufixos de tipo ("Arquivo", "URL" etc.)
            name = re.sub(r"\s+(Arquivo|URL|Página|Pasta|Fórum|Rótulo|Livro)\s*$", "", name)
            mod_type = ""
            m = re.search(r"/mod/([^/]+)/", href)
            if m:
                mod_type = m.group(1)
            block.activities.append(Activity(name=name, url=href, mod_type=mod_type))
        logger.info("Bloco %d '%s' — %d atividades", idx, title, len(block.activities))
        blocks.append(block)
    return blocks


async def _download_link(page: Page, url: str, dest_dir: Path) -> str | None:
    """Baixa arquivo via context.request (segue cookies da sessão)."""
    try:
        ctx = page.context
        resp = await ctx.request.get(url)
        if resp.status != 200:
            logger.warning("UFPR Aberta: download %s -> HTTP %s", url, resp.status)
            return None
        # Moodle usa /pluginfile.php/.../nome.pdf
        filename = Path(urlparse(url).path).name or "download.bin"
        # se veio content-disposition, tenta extrair
        cd = resp.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            filename = m.group(1)
        dest = dest_dir / filename
        body = await resp.body()
        dest.write_bytes(body)
        return str(dest)
    except Exception as e:
        logger.warning("UFPR Aberta: falha baixando %s: %s", url, e)
        return None


async def _scrape_activity(page: Page, activity: Activity, out_dir: Path) -> None:
    """Visita atividade, salva HTML e baixa resource files quando aplicável."""
    try:
        # mod/resource redireciona para arquivo binário — baixa direto.
        if activity.mod_type == "resource":
            path = await _download_link(page, activity.url, out_dir)
            if path:
                activity.resources.append(Resource(activity.name, activity.url, path))
            return

        await page.goto(activity.url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)

        html = await page.content()
        safe = _slug(activity.name)
        html_path = out_dir / f"{activity.mod_type or 'page'}__{safe}.html"
        html_path.write_text(html, encoding="utf-8")
        activity.html_path = str(html_path)

        # pega texto visível do main content
        main = page.locator("#region-main, [role='main'], #maincontent").first
        if await main.count():
            activity.text = (await main.inner_text()).strip()

        # coleta PDFs/anexos embutidos
        pdf_links = page.locator("a[href*='pluginfile.php']")
        pn = await pdf_links.count()
        for k in range(pn):
            href = await pdf_links.nth(k).get_attribute("href")
            name = (await pdf_links.nth(k).inner_text()).strip() or Path(urlparse(href or "").path).name
            if not href:
                continue
            path = await _download_link(page, href, out_dir)
            activity.resources.append(Resource(name=name, url=href, local_path=path))
    except Exception as e:
        logger.warning("UFPR Aberta: falha em atividade %s: %s", activity.name, e)


async def scrape_course(page: Page, course_id: int = DEFAULT_COURSE_ID) -> list[Block]:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    url = f"{UFPR_ABERTA_URL.rstrip('/')}/course/view.php?id={course_id}"
    logger.info("UFPR Aberta: carregando curso %s", url)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_load_state("networkidle", timeout=20000)

    # salva HTML da home do curso
    (RAW_ROOT / "_course_home.html").write_text(await page.content(), encoding="utf-8")

    blocks = await _extract_blocks(page, url)
    for block in blocks:
        out = _raw_dir_for_block(block)
        (out / "_section_summary.html").write_text(block.summary_html, encoding="utf-8")
        logger.info("UFPR Aberta: bloco %d '%s' — %d atividades",
                    block.index, block.title, len(block.activities))
        for act in block.activities:
            await _scrape_activity(page, act, out)
    return blocks
