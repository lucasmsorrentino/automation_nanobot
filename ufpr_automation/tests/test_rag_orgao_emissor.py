"""Unit tests para o mapeamento doc -> orgao_emissor em rag/ingest.py.

Plano: ufpr_automation/PLANO_EXPANSAO_TIER0_E_ROLE.md (Frente 3).
"""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from ufpr_automation.rag.ingest import _infer_orgao_emissor


@pytest.mark.parametrize(
    "rel_path,expected",
    [
        # Pastas nivel-1 mapeadas diretamente
        ("cepe/resolucoes/res_46_10.pdf", "CEPE"),
        ("coun/atas/ata_2024.pdf", "COUN"),
        ("coplad/instrucoes-normativas/in_01_2023.pdf", "COPLAD"),
        ("concur/resolucoes/res_xxx.pdf", "CONCUR"),
        ("design_grafico/PPC.pdf", "CCDG"),
        ("design_grafico/ementasDG.pdf", "CCDG"),
        ("sei_pop/POP-1-Acessar-o-SEI.pdf", "UFPR"),
        ("ufpr_aberta/_course_home.html", "UFPR_ABERTA"),
        # Pasta estagio/ heterogenea — resolvida por filename
        ("estagio/Lei11788Estagio.pdf", "MEC"),
        ("estagio/resolucaoCEPE_estagio-46-10.pdf", "CEPE"),
        ("estagio/regulamento_estagio-DesignGrafico.pdf", "CCDG"),
        ("estagio/manual-de-estagios-versao-final.pdf", "PROGRAP"),
        ("estagio/Perguntas Frequentes – COAPPE(estagio).pdf", "COAPPE"),
        ("estagio/exemploDespachoTermo01.pdf", "CCDG"),
        ("estagio/exemploTermo01.pdf", "CCDG"),
        # Casos sem mapping: cai em DESCONHECIDO
        ("estagio/algum_doc_sem_pattern.pdf", "DESCONHECIDO"),
        ("ainda_n_ingeridos/algo.pdf", "DESCONHECIDO"),
    ],
)
def test_infer_orgao_emissor(rel_path: str, expected: str):
    """Verifica o mapeamento pasta+filename -> sigla do orgao."""
    # Aceita PurePosixPath via .parts — _infer_orgao_emissor usa só rel_path.parts e .name
    assert _infer_orgao_emissor(PurePosixPath(rel_path)) == expected
