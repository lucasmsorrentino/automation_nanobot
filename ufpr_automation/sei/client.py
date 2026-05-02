"""SEI client for querying processes and preparing despacho drafts.

All operations are READ-ONLY. Despacho drafts are prepared locally using
templates from SOUL.md section 14 but NEVER submitted to SEI automatically.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ufpr_automation.sei.models import DespachoDraft, DespachoTipo, DocumentoSEI, ProcessoSEI
from ufpr_automation.utils.logging import logger


class SEIClient:
    """Client for read-only operations on SEI via Playwright.

    All methods are async and require an active Playwright page.
    No write operations are performed -- drafts are prepared locally only.
    """

    def __init__(self, page: Page):
        self._page = page

    async def search_process(self, numero_processo: str) -> ProcessoSEI | None:
        """Search for a process by number in SEI.

        Args:
            numero_processo: Process number in format XXXXX.XXXXXX/XXXX-XX

        Returns:
            ProcessoSEI with metadata, or None if not found.
        """
        try:
            logger.info("SEI: buscando processo %s", numero_processo)

            # Navigate to process search
            search_input = self._page.locator(
                'input#txtPesquisaRapida, input[name="txtPesquisaRapida"], '
                'input[placeholder*="Pesquisa"]'
            )
            if await search_input.count() == 0:
                logger.warning("SEI: campo de pesquisa rapida nao encontrado")
                return None

            await search_input.first.fill(numero_processo)
            await search_input.first.press("Enter")
            await self._page.wait_for_load_state("networkidle", timeout=15000)

            # Extract process metadata from the detail page
            processo = ProcessoSEI(numero=numero_processo)

            # Try to extract status
            status_el = self._page.locator(
                "#divInfraBarraComandosSuperior, .infraBarraLocalizacao, "
                '[id*="situacao"], [class*="situacao"]'
            )
            if await status_el.count() > 0:
                status_text = await status_el.first.text_content()
                if status_text:
                    processo.observacoes = status_text.strip()

            # Try to extract document list from the process tree
            processo.documentos = await self._extract_documents()

            # Extract interested parties
            interessados_el = self._page.locator('[id*="interessado"], [class*="interessado"]')
            if await interessados_el.count() > 0:
                for i in range(await interessados_el.count()):
                    text = await interessados_el.nth(i).text_content()
                    if text and text.strip():
                        processo.interessados.append(text.strip())

            logger.info(
                "SEI: processo %s encontrado — %d documento(s)",
                numero_processo,
                len(processo.documentos),
            )
            return processo

        except Exception as e:
            logger.error("SEI: falha ao buscar processo %s: %s", numero_processo, e)
            return None

    # IDs do <select id="selTipoProcedimentoPesquisa"> — validados live
    # contra https://sei.ufpr.br em 2026-04-30 via scripts/sei_drive.py.
    # Usar value (numerico, estavel) ao inves de label porque o texto pode
    # mudar de versao de SEI.
    TIPO_ESTAGIO_NAO_OBRIGATORIO = "478"
    TIPO_ESTAGIO_OBRIGATORIO = "100000767"
    TIPO_ESTAGIO_NO_EXTERIOR = "100000768"

    async def _navigate_to_pesquisa_geral(self) -> bool:
        """Click 'Pesquisa' menu link → carrega o form de pesquisa avancada.

        Idempotente: se ja esta no form, no-op.
        """
        # Se o form ja esta visivel (selTipoProcedimentoPesquisa presente),
        # nao precisa navegar.
        if await self._page.locator("#selTipoProcedimentoPesquisa").count() > 0:
            return True
        menu = self._page.locator('a[href*="protocolo_pesquisar"]').first
        if await menu.count() == 0:
            logger.warning("SEI: menu 'Pesquisa' (protocolo_pesquisar) nao encontrado")
            return False
        await menu.click()
        await self._page.wait_for_load_state("networkidle", timeout=15000)
        return await self._page.locator("#selTipoProcedimentoPesquisa").count() > 0

    async def find_processes_by_keyword_filtered(
        self,
        keyword: str,
        *,
        tipo_value: str | None = None,
        max_results: int = 20,
    ) -> list[ProcessoSEI]:
        """Pesquisa Geral filtrada por tipo + keyword (GRR ou nome).

        Selectors validados live 2026-04-30 contra ``https://sei.ufpr.br``:

        - menu link:    ``a[href*="protocolo_pesquisar"]``
        - tipo:         ``#selTipoProcedimentoPesquisa`` (option value=478 = estagio nao obrig)
        - texto busca:  ``#q``
        - submit:       ``#sbmPesquisar``
        - resultados:   ``td.pesquisaTituloEsquerda`` -> ``a.arvore img[title]``
                        com formato "TIPO Nº NUMERO - DOC (DOC_ID)"

        Resultados deduplicados por numero (cada processo aparece 1x mesmo
        quando a busca retorna varios documentos do mesmo processo).
        Restringido a UFPR (prefixo 23075.*).

        Args:
            keyword: GRR (preferido — exact match) ou nome do aluno.
            tipo_value: ID do tipo de processo. Default: estagio nao obrigatorio.
            max_results: limite de processos unicos retornados.
        """
        keyword = keyword.strip()
        if not keyword:
            return []
        tipo_value = tipo_value or self.TIPO_ESTAGIO_NAO_OBRIGATORIO
        try:
            if not await self._navigate_to_pesquisa_geral():
                return []
            await self._page.locator("#selTipoProcedimentoPesquisa").select_option(
                value=tipo_value
            )
            await self._page.locator("#q").fill(keyword)
            await self._page.locator("#sbmPesquisar").click()
            await self._page.wait_for_load_state("networkidle", timeout=20000)
            results = await self._parse_pesquisa_geral_results(max_results=max_results)
            logger.info(
                "SEI: pesquisa geral filtrada (tipo=%s) por %r -> %d processo(s)",
                tipo_value,
                keyword,
                len(results),
            )
            return results
        except Exception as e:
            logger.error(
                "SEI: find_processes_by_keyword_filtered(%s, tipo=%s) falhou: %s",
                keyword,
                tipo_value,
                e,
            )
            return []

    async def _parse_pesquisa_geral_results(
        self, *, max_results: int = 20
    ) -> list[ProcessoSEI]:
        """Parse das linhas da Pesquisa Geral (acao=protocolo_pesquisar).

        Cada hit eh um documento; deduplicamos por numero de processo. O
        ``title`` do ``<img class='arvore'>`` traz o formato cheio:
        ``"TIPO Nº NUMERO - DOC_NOME (DOC_ID)"``. Restringimos a UFPR
        (prefixo 23075.) pra evitar contaminacao IFPR/MEC.
        """
        title_re = re.compile(
            r"^(.*?)\s+Nº\s+(23075\.\d{6}/\d{4}-\d{2})"
        )
        cells = self._page.locator("td.pesquisaTituloEsquerda")
        count = await cells.count()
        seen: dict[str, ProcessoSEI] = {}
        # 4 docs por processo eh comum (despacho 68, 149, etc.) entao
        # iteramos ate ~4x max_results pra garantir que pegamos
        # max_results processos unicos.
        for i in range(min(count, max_results * 4)):
            try:
                cell = cells.nth(i)
                img = cell.locator("a.arvore img").first
                if await img.count() == 0:
                    continue
                title = (await img.get_attribute("title")) or ""
                m = title_re.match(title)
                if not m:
                    continue
                tipo = m.group(1).strip()
                numero = m.group(2)
                if numero in seen:
                    continue
                seen[numero] = ProcessoSEI(numero=numero, tipo=tipo)
                if len(seen) >= max_results:
                    break
            except Exception:
                continue
        return list(seen.values())

    async def find_processes_by_grr(
        self,
        grr: str,
        *,
        max_results: int = 20,
        tipo_value: str | None = None,
    ) -> list[ProcessoSEI]:
        """Search SEI por GRR via Pesquisa Geral filtrada por tipo.

        Refactor 2026-04-30: usa ``find_processes_by_keyword_filtered`` com
        ``#selTipoProcedimentoPesquisa`` em vez do ``#txtPesquisaRapida``
        antigo. A pesquisa rapida nao filtra por tipo, devolvia processos
        AGTIC/declaracoes/etc. associados ao GRR e o cascade ficava errado.
        """
        return await self.find_processes_by_keyword_filtered(
            grr, tipo_value=tipo_value, max_results=max_results
        )

    async def find_processes_by_nome(
        self,
        nome: str,
        *,
        max_results: int = 20,
        tipo_value: str | None = None,
    ) -> list[ProcessoSEI]:
        """Search SEI por nome do aluno via Pesquisa Geral filtrada por tipo.

        Util quando o GRR nao da hit (aluno antigo, processo arquivado,
        cadastro inconsistente). Risco de homonimo — caller deve filtrar
        por GRR no resultado se possivel.
        """
        return await self.find_processes_by_keyword_filtered(
            nome, tipo_value=tipo_value, max_results=max_results
        )

    async def find_in_acompanhamento_especial(
        self, keyword: str, *, max_results: int = 20
    ) -> list[ProcessoSEI]:
        """Search Acompanhamento Especial via 'Palavras-chave para pesquisa:'.

        Preferred over generic Pesquisa Rápida for Estágios because AE is
        curated per-unit (Secretaria DG): only processes that someone on
        the team tagged with a grupo — no IFPR/MEC contamination, no
        archived processes from other units.

        Selectors validated live 2026-04-22 via ``scripts/sei_drive.py
        --target ae_keyword_search``:

        - menu link: ``a:has-text("Acompanhamento Especial")`` (main frame)
        - input: ``#txtPalavrasPesquisaAcompanhamento``
        - submit: ``button:has-text("Pesquisar")``
        - table: ``#tblAcompanhamentos`` (class ``infraTableResponsiva infraTable``)
        - columns (8): checkbox, sort-toggle, Processo, Usuário, Data, Grupo,
          Observação, Ações

        Args:
            keyword: search term (GRR recommended for exact-match; also accepts
                nome, nº processo, ou qualquer texto que tenha sido colocado
                na observação do AE).
            max_results: cap on parsed rows.

        Returns:
            List of ``ProcessoSEI`` (empty if no match or on error).
        """
        keyword = keyword.strip()
        if not keyword:
            return []
        try:
            logger.info("SEI: busca AE por palavra-chave %r", keyword)
            menu = self._page.locator(
                'a[title="Acompanhamento Especial"], '
                'a:has-text("Acompanhamento Especial")'
            )
            if await menu.count() == 0:
                logger.warning("SEI: menu Acompanhamento Especial nao encontrado")
                return []
            await menu.first.click()
            await self._page.wait_for_load_state("networkidle", timeout=15000)

            search_input = self._page.locator("#txtPalavrasPesquisaAcompanhamento")
            if await search_input.count() == 0:
                logger.warning("SEI: input de palavras-chave AE nao encontrado")
                return []
            await search_input.first.fill(keyword)

            submit = self._page.locator(
                'button:has-text("Pesquisar"), input[value="Pesquisar"]'
            )
            if await submit.count() > 0:
                await submit.first.click()
            else:
                await search_input.first.press("Enter")
            await self._page.wait_for_load_state("networkidle", timeout=15000)

            results = await self._parse_ae_results_table(max_results=max_results)
            logger.info(
                "SEI: %d processo(s) em AE para palavra-chave %r",
                len(results),
                keyword,
            )
            return results
        except Exception as e:
            logger.error(
                "SEI: find_in_acompanhamento_especial(%s) falhou: %s", keyword, e
            )
            return []

    async def _parse_ae_results_table(
        self, *, max_results: int = 20
    ) -> list[ProcessoSEI]:
        """Parse ``#tblAcompanhamentos`` rows. Columns (from live capture):
        ``[checkbox, sort, Processo, Usuário, Data, Grupo, Observação, Ações]``.
        """
        results: list[ProcessoSEI] = []
        rows = self._page.locator("#tblAcompanhamentos tbody tr")
        count = await rows.count()
        for i in range(min(count, max_results)):
            try:
                row = rows.nth(i)
                cells = row.locator("td")
                n_cells = await cells.count()
                if n_cells < 7:
                    continue  # header or malformed
                cell_texts = [
                    ((await cells.nth(c).text_content()) or "").strip()
                    for c in range(n_cells)
                ]
                numero = ""
                for ct in cell_texts:
                    m = re.search(r"23075\.\d{6}/\d{4}-\d{2}", ct)
                    if m:
                        numero = m.group(0)
                        break
                if not numero:
                    continue
                processo = ProcessoSEI(numero=numero)
                if n_cells >= 8:
                    # Positional mapping validated 2026-04-22.
                    processo.ultima_movimentacao = cell_texts[4]
                    processo.tipo = cell_texts[5]
                    obs = cell_texts[6]
                    if obs:
                        processo.interessados = [obs]
                else:
                    for ct in cell_texts:
                        if not processo.tipo and "estágio" in ct.lower():
                            processo.tipo = ct
                        if not processo.ultima_movimentacao and re.search(
                            r"\d{2}/\d{2}/\d{4}", ct
                        ):
                            processo.ultima_movimentacao = ct
                        if not processo.interessados and "GRR" in ct.upper():
                            processo.interessados = [ct]
                results.append(processo)
            except Exception:
                continue
        return results

    async def _extract_numero_from_detail(self) -> str | None:
        """Extract the process number from the current detail page.

        SEI shows it in the header breadcrumb / title. Heuristic multi-selector.
        """
        for sel in (
            "#divInfraBarraLocalizacao",
            ".infraBarraLocalizacao",
            'h1, h2, [id*="Cabecalho"]',
        ):
            el = self._page.locator(sel)
            if await el.count() > 0:
                text = await el.first.text_content()
                if text:
                    m = re.search(r"\d{5}\.\d{6}/\d{4}-\d{2}", text)
                    if m:
                        return m.group(0)
        return None

    async def _parse_search_results_table(
        self, *, max_results: int = 20
    ) -> list[ProcessoSEI]:
        """Parse the SEI search-results table after a ``#txtPesquisaRapida``
        submission that returned multiple hits.

        The table has one row per process with columns in this order (per
        user feedback 2026-04-22): numero, usuário, data/hora, tipo,
        interessados (e.g.,
        ``23075.011886/2026-96 lucas.sorrentino 06/03/2026 13:54:55
        Estágio não obrigatório MARLON HENRIQUE GOMES FERNANDES - GRR20223876``).
        Selectors are heuristic — multiple fallbacks since no capture manifest
        exists yet for this view.
        """
        results: list[ProcessoSEI] = []
        # A tabela real de resultados da Pesquisa Rápida do SEI UFPR (validado
        # ao vivo 2026-04-22) tem ``class="pesquisaResultado"``. Os outros
        # seletores ficam como fallback pra tolerar variações de layout ou
        # skins futuras.
        rows = self._page.locator(
            "table.pesquisaResultado tbody tr, "
            "table.infraTable tbody tr, "
            "#tblProcessos tbody tr, "
            'table:has(a[href*="processo_exibir"]) tbody tr'
        )
        count = await rows.count()
        for i in range(min(count, max_results)):
            try:
                row = rows.nth(i)
                cells = row.locator("td")
                n_cells = await cells.count()
                if n_cells < 2:
                    continue
                cell_texts = [
                    ((await cells.nth(c).text_content()) or "").strip()
                    for c in range(n_cells)
                ]
                # Find the cell containing the process number pattern
                numero = ""
                for ct in cell_texts:
                    m = re.search(r"\d{5}\.\d{6}/\d{4}-\d{2}", ct)
                    if m:
                        numero = m.group(0)
                        break
                if not numero:
                    continue
                processo = ProcessoSEI(numero=numero)
                # Try to infer columns by heuristics, not by position.
                for ct in cell_texts:
                    if not processo.tipo and "estágio" in ct.lower():
                        processo.tipo = ct
                    if not processo.ultima_movimentacao and re.search(
                        r"\d{2}/\d{2}/\d{4}", ct
                    ):
                        processo.ultima_movimentacao = ct
                    if not processo.interessados and (
                        "GRR" in ct.upper() or ct.isupper() and len(ct) > 4
                    ):
                        processo.interessados = [ct]
                results.append(processo)
            except Exception:
                continue
        return results

    async def _extract_documents(self) -> list[DocumentoSEI]:
        """Extract document list from the current process view."""
        docs: list[DocumentoSEI] = []
        try:
            # SEI shows documents in a tree structure
            doc_links = self._page.locator(
                '#divArvore a[id^="anchor"], .infraArvore a, a[href*="documento_consultar"]'
            )
            count = await doc_links.count()
            for i in range(min(count, 50)):  # Cap at 50 docs
                link = doc_links.nth(i)
                text = await link.text_content()
                if text and text.strip():
                    doc = DocumentoSEI(tipo=text.strip())
                    # Try to get SEI number from title attribute
                    title = await link.get_attribute("title")
                    if title:
                        doc.numero_sei = title.strip()
                    docs.append(doc)
        except Exception as e:
            logger.debug("SEI: falha ao extrair documentos: %s", e)
        return docs

    @staticmethod
    def prepare_despacho_draft(
        tipo: DespachoTipo,
        dados: dict[str, str] | None = None,
    ) -> DespachoDraft:
        """Prepare a despacho draft using SOUL.md templates.

        This is a LOCAL operation -- nothing is submitted to SEI.
        Unfilled [BRACKET] fields are listed in campos_pendentes.

        The full template text (header + body + footer, already composed) is
        fetched from the Neo4j knowledge graph via TemplateRegistry. If Neo4j
        is unreachable, returns a DespachoDraft with an empty body and
        ``campos_pendentes=["neo4j_unavailable"]``.

        Args:
            tipo: Type of despacho (tce_inicial, aditivo, rescisao).
            dados: Optional dict mapping placeholder names to values.
                   e.g. {"NUMERO_TCE": "12345", "NOME COMPLETO": "JOAO SILVA"}

        Returns:
            DespachoDraft with the formatted text and pending fields.
        """
        from ufpr_automation.graphrag.templates import get_registry

        full_text = get_registry().get(tipo)
        if full_text is None:
            logger.error(
                "SEI: nao foi possivel obter template '%s' do Neo4j (grafo indisponivel)",
                tipo,
            )
            return DespachoDraft(
                tipo=tipo,
                conteudo="",
                campos_pendentes=["neo4j_unavailable"],
            )

        # Fill in provided data
        if dados:
            for key, value in dados.items():
                full_text = full_text.replace(f"[{key}]", value)

        # Find remaining unfilled brackets
        pendentes = re.findall(r"\[([^\]]+)\]", full_text)

        processo_sei = ""
        if dados and "NUMERO_PROCESSO_SEI" in dados:
            processo_sei = dados["NUMERO_PROCESSO_SEI"]

        return DespachoDraft(
            tipo=tipo,
            conteudo=full_text,
            processo_sei=processo_sei,
            campos_pendentes=pendentes,
            template_usado=(
                "SOUL.md secao 14."
                f"{['1', '2', '3'][['tce_inicial', 'aditivo', 'rescisao'].index(tipo)]}"
            ),
        )


def extract_sei_process_number(text: str) -> str | None:
    """Extract a **UFPR** SEI process number from text.

    UFPR uses prefix ``23075.*``. Processes from other organs (IFPR=23411,
    outras IFES) têm o mesmo layout mas NÃO são pesquisáveis no SEI UFPR —
    restringimos o regex pra evitar que um nº de outra instituição no corpo
    do email seja interpretado como se fosse nosso (regressão identificada
    no smoke 2026-04-22, processo 23411.005778/2026-16 era IFPR).

    Looks for pattern: ``23075.XXXXXX/YYYY-ZZ``.
    """
    match = re.search(r"23075\.\d{6}/\d{4}-\d{2}", text)
    return match.group(0) if match else None


def extract_grr(text: str) -> str | None:
    """Extract a GRR student registration number from text.

    Looks for patterns: GRXXXXXXX, GRR20XXXXXX, or just the number after GRR.
    """
    match = re.search(r"GRR?\s*(\d{7,9})", text, re.IGNORECASE)
    if match:
        return f"GRR{match.group(1)}"
    return None


# Institutional tokens — ANY token of a candidate name appearing in this
# set disqualifies the whole candidate. More robust than phrase-level
# stopwords because multi-word regex slices ("ARTES COMUNICACAO",
# "UNIVERSIDADE FEDERAL", "SETOR DE ARTES") all share these tokens.
# Portuguese-normalized (no accents) — we lowercase+strip accents before
# comparing.
_INSTITUTIONAL_TOKENS = {
    "UNIVERSIDADE",
    "FEDERAL",
    "PARANA",
    "SETOR",
    "ARTES",
    "COMUNICACAO",
    "DESIGN",
    "GRAFICO",
    "PRODUTO",
    "CURSO",
    "COORDENACAO",
    "COORDENADORIA",
    "SECRETARIA",
    "MINISTERIO",
    "EDUCACAO",
    "REITORIA",
    "PROREITORIA",
    "DEPARTAMENTO",
    "INSTITUTO",
    "CAMPUS",
    "GRADUACAO",
    "ENSINO",
    "PESQUISA",
    "EXTENSAO",
    "TERMO",
    "COMPROMISSO",
    "ADITIVO",
    "RESCISAO",
    "ESTAGIO",
    "ESTAGIOS",
    "OBRIGATORIO",
    "OBRIGATORIOS",
    "CONCEDENTE",
    "ESTAGIARIO",
    "ESTAGIARIA",
    "PROCESSO",
    "NUMERO",
    "TCE",
    "UFPR",
    "CIEE",
}


def _strip_accents(s: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )

# "Aluno:", "Estagiário:", "Estagiária:", "Estagiario(a):" — explicit label.
_NAME_LABEL_RE = re.compile(
    r"(?:aluno|estagi[aá]ri[oa](?:\s*\(\s*a\s*\))?)\s*[:\-]\s*"
    r"([A-ZÁÉÍÓÚÂÊÎÔÛÀÃÕÇ][A-ZÁÉÍÓÚÂÊÎÔÛÀÃÕÇa-záéíóúâêîôûàãõç\s]{4,80}?)"
    r"(?=\s*(?:\n|$|[,;\.]|CPF|GRR|RG|matr[ií]cula))",
    re.IGNORECASE,
)

# ALL-CAPS multi-word sequence (TCE PDFs capitalize names). At least 2 words,
# each ≥3 letters. Allow accented letters.
_ALLCAPS_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÂÊÎÔÛÀÃÕÇ]{3,}(?:[ \t]+[A-ZÁÉÍÓÚÂÊÎÔÛÀÃÕÇ]{3,}){1,4})\b"
)


def _is_stopword_name(candidate: str) -> bool:
    """Drop candidate if any of its tokens looks institutional.

    Accents are stripped before comparison (``PARANÁ`` → ``PARANA``) so
    the set matches both accented PDFs and ASCII-flattened email headers.
    """
    norm = _strip_accents(candidate.upper())
    tokens = re.findall(r"[A-Z]+", norm)
    return any(t in _INSTITUTIONAL_TOKENS for t in tokens)


def extract_candidate_names(text: str) -> list[str]:
    """Extract likely student names from email body + attachment text.

    Returns an ordered list of candidates, best-first, de-duplicated. Meant
    to feed the AE cascade after AE-GRR fails — sometimes the secretary
    entered the aluno's name (not the GRR) into the AE Observação field, so
    AE search by name is the only way to hit it.

    Priority:
        1. Label-based: text after ``Aluno:``, ``Estagiário(a):``, etc.
        2. ALL-CAPS multi-word sequences (typical shape of TCE PDFs).

    Stopword filter drops organizational strings ("UNIVERSIDADE FEDERAL DO
    PARANA", "COORDENACAO", "TERMO DE COMPROMISSO", etc.) that also match
    the all-caps heuristic but aren't people.

    Args:
        text: combined email body + attachment text.

    Returns:
        Up to 3 candidate names (empty if nothing looked name-like).
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _push(name: str) -> None:
        cleaned = re.sub(r"\s+", " ", name.strip())
        if len(cleaned) < 5:
            return
        if _is_stopword_name(cleaned):
            return
        key = cleaned.upper()
        if key in seen:
            return
        out.append(cleaned)
        seen.add(key)

    for m in _NAME_LABEL_RE.finditer(text):
        _push(m.group(1))

    for m in _ALLCAPS_NAME_RE.finditer(text):
        _push(m.group(1))

    return out[:3]


def shorten_name_first_last(name: str) -> str:
    """Reduce ``"MATHEUS KLEINE ALBERS"`` to ``"MATHEUS ALBERS"``.

    Many secretaries type the aluno's name into AE Observação as just
    first+last (dropping middle names). Searching the full captured name
    in AE misses those entries; searching first+last catches them.

    If the name has ≤2 words, returns it unchanged. Returns empty string
    for empty input.
    """
    parts = [p for p in (name or "").strip().split() if p]
    if len(parts) <= 2:
        return " ".join(parts)
    return f"{parts[0]} {parts[-1]}"


def extract_year_from_numero(numero: str) -> int | None:
    """Extract the 4-digit year from a SEI process number.

    SEI format: ``XXXXX.XXXXXX/YYYY-ZZ`` — the 4 digits after the slash
    are the year. Used for disambiguation when N > 1 processes come back
    from a GRR search (newer year = more likely the active one).
    """
    match = re.search(r"/(\d{4})-\d{2}", numero or "")
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _parse_br_datetime_to_ts(value: str) -> float:
    """Parse a ``DD/MM/YYYY HH:MM:SS`` (or date-only) Brazilian timestamp
    into a Unix epoch float. Returns 0.0 if the format doesn't match.
    Used as a tiebreaker for disambiguation.
    """
    from datetime import datetime

    if not value:
        return 0.0
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def select_best_processo(
    candidates: list[ProcessoSEI],
    *,
    email_subject: str = "",
    grr_hint: str | None = None,
) -> tuple[ProcessoSEI | None, float]:
    """Pick the most likely ProcessoSEI from a list of candidates.

    Estratégia de 2 fases, validada contra o exemplo real do usuário
    (2026-04-22): "o mais novo é o ativo", onde "novo" = ano do nº do
    processo mais recente.

    Fase 1 — **Ano dominante**: filtra só os candidatos do ano mais
    recente (parse regex ``/YYYY-ZZ`` do ``numero``). Candidatos de
    anos anteriores são descartados sem outra avaliação — é a regra de
    negócio explícita do usuário.

    Fase 2 — **Desempate intra-ano** por score aditivo:
      +20 status contém "em andamento" / "aberto" / "em trâmite"
      +15 tipo contém "Estágio não Obrig" (variantes acento)
      +10 interessados contém ``grr_hint`` ou seu sufixo numérico
      +5  ``ultima_movimentacao`` ou ``observacoes`` ≤180 dias atrás

    Retorna ``(best, confidence)``. Quando a Fase 2 não resolve (top 2
    empatam dentro de 5 pontos) retorna ``(None, score/100)`` para que
    o chamador roteie pra revisão humana.
    """
    if not candidates:
        return None, 0.0

    # Fase 0 — guard de tipo: descarta processos que claramente nao sao de
    # estagio (AGTIC eleicao, declaracoes diversas, colacao de grau, etc.)
    # antes de scorear. Sem este guard o cascade ja pegou processos errados
    # ao vivo (Leticia 2026-04-30: AGTIC '23075.059255/2025-77' aparecia
    # como "best" e o agir_estagios o tratava como SEI de estagio existente).
    # Match permissivo: aceita qualquer variante de "Estagio(s) Obrig/Nao Obrig"
    # com ou sem acento; quando o ``tipo`` nao foi extraido (parser SEI nao
    # encontrou a coluna), preserva o candidato — o caller fica responsavel
    # por re-pesquisar com filtro de tipo no formulario do SEI.
    _ESTAGIO_TIPO_RE = re.compile(r"est[áa]gios?", re.IGNORECASE)
    typed = [c for c in candidates if not c.tipo or _ESTAGIO_TIPO_RE.search(c.tipo)]
    if typed:
        candidates = typed

    # Fase 1 — filtrar por ano mais recente
    with_year = [(c, extract_year_from_numero(c.numero) or 0) for c in candidates]
    max_year = max(y for _, y in with_year)
    latest = [c for c, y in with_year if y == max_year]

    if len(latest) == 1:
        return latest[0], 1.0

    # Fase 2 — desempate intra-ano
    def _score(p: ProcessoSEI) -> float:
        total = 0.0
        status = (p.status or "").lower()
        if "andamento" in status or "aberto" in status or "trâmite" in status:
            total += 20
        tipo = (p.tipo or "").lower()
        if "estágio não obrig" in tipo or "estagio nao obrig" in tipo:
            total += 15
        if grr_hint:
            grr_digits = re.sub(r"\D", "", grr_hint)
            for i in p.interessados:
                if grr_hint.lower() in i.lower() or (grr_digits and grr_digits in i):
                    total += 10
                    break
        ts = _parse_br_datetime_to_ts(p.ultima_movimentacao or p.observacoes)
        if ts > 0:
            from datetime import datetime, timezone

            age_days = (datetime.now(timezone.utc).timestamp() - ts) / 86400.0
            if 0 <= age_days <= 180:
                total += 5
        return total

    scored = sorted(((c, _score(c)) for c in latest), key=lambda t: t[1], reverse=True)
    best, top_score = scored[0]
    if len(scored) > 1 and abs(scored[0][1] - scored[1][1]) < 5:
        return None, top_score / 100.0
    return best, top_score / 100.0
