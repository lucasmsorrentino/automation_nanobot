"""Regressão: nenhum template Tier 0 pode dizer ao remetente "procure a Coordenação".

Motivação: o agente É a Coordenação do Curso. Mandar o aluno procurar a Coordenação
em uma resposta assinada pela própria Coordenação é um anti-padrão de auto-referência
— quebra confiança e confunde o remetente. Quando faltar info, deve pedir diretamente
("responda este e-mail") ou citar outro setor (COAPPE, PRAE, AUI, etc.).

Plano de referência: ufpr_automation/PLANO_EXPANSAO_TIER0_E_ROLE.md (Frente 2).
"""

from __future__ import annotations

import re

import pytest

from ufpr_automation.procedures.playbook import get_playbook

# Padrões proibidos (case-insensitive) — só capturam quando o objeto é Coordenação
# ou Secretaria do Curso. "contate a UE/COAPPE", "contate a PRAE" etc. são OK.
_FORBIDDEN_PATTERNS = [
    re.compile(r"procur[ae]\s+a\s+coordena[çc][ãa]o", re.IGNORECASE),
    re.compile(r"entre\s+em\s+contato\s+com\s+a\s+coordena[çc][ãa]o", re.IGNORECASE),
    re.compile(r"contat[eo]\s+a\s+coordena[çc][ãa]o", re.IGNORECASE),
    re.compile(r"consult[ae]\s+a\s+coordena[çc][ãa]o", re.IGNORECASE),
    re.compile(r"consult[ae]\s+a\s+secretaria\s+do\s+curso", re.IGNORECASE),
    re.compile(r"procur[ae]\s+a\s+secretaria", re.IGNORECASE),
]


def _intents():
    return get_playbook().intents


@pytest.mark.parametrize("intent", _intents(), ids=lambda i: i.intent_name)
def test_intent_template_does_not_self_refer(intent):
    """Cada intent.template não pode conter o anti-padrão de auto-referência."""
    template = intent.template or ""
    for pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(template)
        assert match is None, (
            f"Intent '{intent.intent_name}' contém anti-padrão de auto-referência: "
            f"'{match.group(0)}'. O agente É a Coordenação — usar 'responda este "
            f"e-mail' ou citar outro setor (COAPPE, PRAE, AUI...). "
            f"Ver ufpr_automation/PLANO_EXPANSAO_TIER0_E_ROLE.md §Frente 2."
        )


@pytest.mark.parametrize("intent", _intents(), ids=lambda i: i.intent_name)
def test_intent_despacho_template_does_not_self_refer(intent):
    """Mesmo guard para despacho_template (peças SEI), quando existir."""
    despacho = getattr(intent, "despacho_template", None) or ""
    if not despacho:
        pytest.skip(f"intent '{intent.intent_name}' sem despacho_template")
    for pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(despacho)
        assert match is None, (
            f"Despacho do intent '{intent.intent_name}' contém anti-padrão: "
            f"'{match.group(0)}'."
        )
