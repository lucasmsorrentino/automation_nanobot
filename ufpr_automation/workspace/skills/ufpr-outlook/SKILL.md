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
| **Pensar**   | `PensarAgent × N` | Classifica cada e-mail e gera rascunho de resposta via LiteLLM (N chamadas **em paralelo**) |
| **Agir**     | `AgirAgent` | Salva as respostas geradas como **rascunhos** no OWA — nunca envia automaticamente |

## Comandos disponíveis

```bash
# Pipeline completo (login automático + scraping + LLM + rascunhos)
python -m ufpr_automation

# Forçar modo com janela visível
python -m ufpr_automation --headed

# Apenas Perceber (scraping + corpos, sem LLM)
python -m ufpr_automation --perceber-only

# Debug — captura DOM + screenshot
python -m ufpr_automation --debug

# Teste do Playwright sem login
python -m ufpr_automation --dry-run
```

## Login automático

O sistema preenche credenciais (`OWA_EMAIL`, `OWA_PASSWORD` do `.env`) automaticamente na página da Microsoft. Quando o MFA de **number matching** é detectado, o número de 2 dígitos é enviado via **Telegram Bot** (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). O usuário aprova no Microsoft Authenticator pelo celular. Se a sessão expirar, o login é re-executado automaticamente sem intervenção.

## Estrutura modular

```
ufpr_automation/
├── orchestrator.py          # Coordenador multi-agente
├── agents/
│   ├── perceber.py          # PerceberAgent (Playwright, sequencial)
│   ├── pensar.py            # PensarAgent (LiteLLM, paralelo via asyncio)
│   └── agir.py              # AgirAgent (Playwright, sequencial)
├── outlook/
│   ├── browser.py           # Ciclo de vida do navegador + sessão
│   ├── scraper.py           # Extração da lista de e-mails (3 estratégias)
│   ├── body_extractor.py    # Abertura e extração do corpo completo
│   └── responder.py         # Clica Reply + digita + salva rascunho
├── llm/
│   └── client.py            # LLMClient via LiteLLM (sync + async)
├── core/models.py           # EmailData, EmailClassification
└── workspace/               # Contexto nanobot (AGENTS.md, SOUL.md)
```

## Garantias de segurança

- O sistema **nunca envia e-mails automaticamente**.
- Toda ação resulta em um **rascunho** na pasta Rascunhos do OWA.
- O humano deve revisar e enviar manualmente.
