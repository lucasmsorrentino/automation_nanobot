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
                '#divInfraBarraComandosSuperior, .infraBarraLocalizacao, '
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

    async def _extract_documents(self) -> list[DocumentoSEI]:
        """Extract document list from the current process view."""
        docs: list[DocumentoSEI] = []
        try:
            # SEI shows documents in a tree structure
            doc_links = self._page.locator(
                '#divArvore a[id^="anchor"], .infraArvore a, '
                'a[href*="documento_consultar"]'
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

    async def get_process_status(self, numero_processo: str) -> str:
        """Get the current status/tramitation of a process.

        Returns a human-readable status string.
        """
        processo = await self.search_process(numero_processo)
        if not processo:
            return f"Processo {numero_processo} nao encontrado no SEI."
        parts = [f"Processo: {processo.numero}"]
        if processo.status:
            parts.append(f"Status: {processo.status}")
        if processo.unidade_atual:
            parts.append(f"Unidade atual: {processo.unidade_atual}")
        if processo.documentos:
            parts.append(f"Documentos: {len(processo.documentos)}")
        if processo.observacoes:
            parts.append(f"Obs: {processo.observacoes[:200]}")
        return " | ".join(parts)

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
    """Extract a SEI process number from text.

    Looks for pattern: XXXXX.XXXXXX/XXXX-XX (5 digits, dot, 6 digits, slash, 4-XX)
    """
    match = re.search(r"\d{5}\.\d{6}/\d{4}-\d{2}", text)
    return match.group(0) if match else None


def extract_grr(text: str) -> str | None:
    """Extract a GRR student registration number from text.

    Looks for patterns: GRXXXXXXX, GRR20XXXXXX, or just the number after GRR.
    """
    match = re.search(r"GRR?\s*(\d{7,9})", text, re.IGNORECASE)
    if match:
        return f"GRR{match.group(1)}"
    return None
