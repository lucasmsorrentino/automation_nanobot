---
name: ufpr-outlook
description: Automação do Outlook Web (OWA) da UFPR via pipeline multi-agente (Perceber → Pensar → Agir)
metadata: {"nanobot":{"emoji":"📧","always":false}}
---

# Skill: UFPR Outlook Web Automation

## O que esta skill faz

Executa um pipeline de três agentes especializados para processar e-mails institucionais da UFPR:

| Fase | Agente | Responsabilidade |
|------|--------|-----------------|
| **Perceber** | `PerceberAgent` | Abre o OWA via Playwright, varre a inbox e extrai o corpo **completo** de cada e-mail não lido |
| **Pensar**   | `PensarAgent × N` | Classifica cada e-mail e gera rascunho de resposta com Gemini (N chamadas **em paralelo**) |
| **Agir**     | `AgirAgent` | Salva as respostas geradas como **rascunhos** no OWA — nunca envia automaticamente |

## Comandos disponíveis

```bash
# Pipeline completo (scraping + LLM + rascunhos)
python -m ufpr_automation

# Primeiro uso — abre navegador para login manual
python -m ufpr_automation --headed

# Apenas Perceber (scraping + corpos, sem LLM)
python -m ufpr_automation --perceber-only

# Debug — captura DOM + screenshot
python -m ufpr_automation --debug

# Teste do Playwright sem login
python -m ufpr_automation --dry-run
```

## Estrutura modular

```
ufpr_automation/
├── orchestrator.py          # Coordenador multi-agente
├── agents/
│   ├── perceber.py          # PerceberAgent (Playwright, sequencial)
│   ├── pensar.py            # PensarAgent (Gemini, paralelo via asyncio)
│   └── agir.py              # AgirAgent (Playwright, sequencial)
├── outlook/
│   ├── browser.py           # Ciclo de vida do navegador + sessão
│   ├── scraper.py           # Extração da lista de e-mails (3 estratégias)
│   ├── body_extractor.py    # Abertura e extração do corpo completo
│   └── responder.py         # Clica Reply + digita + salva rascunho
├── llm/
│   └── client.py            # GeminiClient (sync + async)
├── core/models.py           # EmailData, EmailClassification
└── workspace/               # Contexto nanobot (AGENTS.md, SOUL.md)
```

## Garantias de segurança

- O sistema **nunca envia e-mails automaticamente**.
- Toda ação resulta em um **rascunho** na pasta Rascunhos do OWA.
- O humano deve revisar e enviar manualmente.
