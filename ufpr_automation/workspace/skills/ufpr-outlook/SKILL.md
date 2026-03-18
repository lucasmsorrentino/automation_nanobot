---
description: Automação do Outlook Web (OWA) via Playwright para e-mails UFPR
always: false
---

# Skill: UFPR Outlook Web Automation

## O que esta skill faz

Permite ao agente interagir com o Microsoft Outlook Web Access (OWA) da UFPR usando automação de navegador (Playwright). O acesso é feito via Web Scraping/RPA porque a governança de TI da UFPR bloqueia o uso da Microsoft Graph API.

## Comandos disponíveis

```bash
# Primeiro uso — login manual (abre navegador visível)
python -m ufpr_automation

# Execuções seguintes — usa sessão salva (headless)
python -m ufpr_automation

# Teste rápido do Playwright (sem login)
python -m ufpr_automation --dry-run

# Modo debug — captura DOM + screenshot
python -m ufpr_automation --debug
```

## Estrutura modular

```
ufpr_automation/
├── config/settings.py     # Configurações (via .env)
├── core/models.py         # EmailData dataclass
├── outlook/browser.py     # Gerenciamento do navegador + sessão
├── outlook/scraper.py     # Extração de e-mails (3 estratégias)
├── cli/commands.py        # Entry point CLI
├── utils/debug.py         # Captura de DOM para debug
└── workspace/             # Integração nanobot
```

## Fluxo de dados

1. **Perceber**: Playwright abre OWA → extrai e-mails não lidos
2. **Pensar**: (futuro) Envia conteúdo ao Gemini para classificação
3. **Agir**: (futuro) Redige resposta e salva como rascunho
4. **Notificar**: Alerta no terminal que há ações pendentes
