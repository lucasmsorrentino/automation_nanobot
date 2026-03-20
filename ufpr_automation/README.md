# 🤖 UFPR Automation — Sistema de Automação Burocrática

<div align="center">
  <h3>Marco I — Protótipo de Ingestão Assistida</h3>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.12-blue" alt="Python">
    <img src="https://img.shields.io/badge/framework-nanobot-orange" alt="nanobot">
    <img src="https://img.shields.io/badge/RPA-Playwright-green" alt="Playwright">
    <img src="https://img.shields.io/badge/LLM-Gemini_1.5_Pro-violet" alt="Gemini">
    <img src="https://img.shields.io/badge/MFA-Telegram_Bot-blue" alt="Telegram MFA">
  </p>
</div>

---

## 📋 Sobre

Sistema de automação burocrática para a **Universidade Federal do Paraná (UFPR)** que utiliza RPA (Robotic Process Automation) via Playwright para acessar o **Outlook Web Access (OWA)** e integração com LLMs para classificação e redação de respostas a e-mails institucionais.

> **Por que RPA?** A governança de TI da UFPR bloqueia o registro de aplicativos para a Microsoft Graph API. A integração com o e-mail é feita obrigatoriamente via Web Scraping do OWA usando Playwright.

### Ciclo Perceber → Pensar → Agir

| Fase | Descrição | Status |
|------|-----------|--------|
| **Perceber** | Playwright navega até o OWA, extrai e-mails não lidos com corpo completo | ✅ Implementado |
| **Pensar** | Gemini classifica cada e-mail e redige resposta em paralelo (asyncio.gather) | ✅ Implementado |
| **Agir** | Playwright clica em "Responder", digita a resposta e salva como **rascunho** | ✅ Implementado |
| **Notificar** | Relatório no terminal com resumo das ações executadas | ✅ Implementado |

---

## 🗂️ Estrutura do Projeto

```
ufpr_automation/
├── __init__.py              # Package init
├── __main__.py              # python -m ufpr_automation
├── .env.example             # Template de variáveis de ambiente
├── ARCHITECTURE.md          # 📐 Diagrama de Arquitetura (Mermaid)
│
├── config/                  # ⚙️ Configurações
│   ├── __init__.py
│   └── settings.py          # URLs, timeouts, API keys (via .env)
│
├── core/                    # 🧩 Modelos de domínio
│   ├── __init__.py
│   └── models.py            # EmailData dataclass
│
├── agents/                  # 🤖 Agentes do pipeline
│   ├── perceber.py          # PerceberAgent — scraping + corpo completo
│   ├── pensar.py            # PensarAgent — classificação Gemini (paralelo)
│   └── agir.py              # AgirAgent — salva rascunhos no OWA
│
├── orchestrator.py          # 🎯 Coordenador Perceber → Pensar → Agir
│
├── llm/                     # 🧠 Integração LLM
│   └── client.py            # GeminiClient (sync + async)
│
├── outlook/                 # 📧 Integração OWA via Playwright
│   ├── browser.py           # Ciclo de vida do navegador + sessão
│   ├── scraper.py           # Extração de e-mails (3 estratégias)
│   ├── body_extractor.py    # Abertura e extração do corpo completo
│   └── responder.py         # Clica Reply + digita + salva rascunho
│
├── cli/                     # 💻 Interface de linha de comando
│   └── commands.py          # Entry point com argparse
│
├── utils/                   # 🔧 Utilitários
│   └── debug.py             # Captura DOM + screenshot para debug
│
├── workspace/               # 🐈 Integração com nanobot
│   ├── AGENTS.md            # Personalidade do agente
│   ├── SOUL.md              # Normas UFPR — ICL context (19 seções)
│   ├── config.json          # Config do provider Gemini
│   └── skills/
│       └── ufpr-outlook/
│           └── SKILL.md     # Skill do nanobot
│
├── INICIO.md                # Especificação da arquitetura
└── TASKS.md                 # Tarefas e roadmap
```

---

## 🚀 Quickstart

### 1. Ambiente Virtual

```bash
cd nanobot
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -e .
pip install playwright
python -m playwright install chromium
```

### 2. Configurar Variáveis de Ambiente

```bash
cp ufpr_automation/.env.example ufpr_automation/.env
```

Edite o `.env` com suas credenciais e chaves:

```env
# Login automático
OWA_EMAIL=seu.email@ufpr.br
OWA_PASSWORD=sua_senha_aqui

# Notificação MFA via Telegram
TELEGRAM_BOT_TOKEN=token_do_botfather
TELEGRAM_CHAT_ID=seu_chat_id

# LLM
GEMINI_API_KEY=sua_chave_aqui
```

### 3. Primeiro Uso — Login Automático com MFA via Telegram

```bash
python -m ufpr_automation
```

O sistema preenche e-mail e senha automaticamente na página da Microsoft. Quando o MFA de **number matching** aparecer, o número de 2 dígitos é enviado para o seu **Telegram** — basta aprovar no Microsoft Authenticator pelo celular. A sessão é salva em `session_data/state.json`.

> **Sem credenciais?** Se `OWA_EMAIL`/`OWA_PASSWORD` não estiverem configurados, o sistema abre o navegador para login manual (comportamento legado).

### 4. Execuções Seguintes — Headless

```bash
python -m ufpr_automation
```

O script detecta a sessão salva e executa em background (headless). Se a sessão expirar, o login automático é executado novamente — sem necessidade de intervenção manual.

---

## 💻 Comandos CLI

| Comando | Descrição |
|---------|-----------|
| `python -m ufpr_automation` | Pipeline completo (scraping + LLM + rascunhos) |
| `python -m ufpr_automation --perceber-only` | Apenas scraping + extração de corpo, sem LLM |
| `python -m ufpr_automation --headed` | Força modo com janela visível |
| `python -m ufpr_automation --debug` | Captura DOM + screenshot para debug |
| `python -m ufpr_automation --dry-run` | Testa Playwright sem login |

---

## 🏗️ Fases de Maturidade

| | Marco I (Atual) | Marco II | Marco III |
|---|---|---|---|
| **Orquestrador** | nanobot | LangGraph | LangGraph Fleet |
| **Memória** | ICL (System Prompt) | Vector RAG | GraphRAG (Neo4j) |
| **Autonomia** | Rascunho + Humano | Auto (baixo risco) | Totalmente autônomo |
| **Sistemas** | OWA | OWA | OWA + SIGA + SEI |

> Veja o diagrama completo em [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 🔧 Stack Tecnológica

- **Python** ≥ 3.12
- **Playwright** — Automação de navegador (RPA)
- **nanobot** — Framework de agente AI (loop Perceber-Pensar-Agir)
- **Gemini 1.5 Pro** — Motor cognitivo (facilmente cambiável)
- **python-telegram-bot** — Notificação MFA via Telegram Bot
- **python-dotenv** — Gerenciamento de variáveis de ambiente

---

## 📝 Notas Importantes

- **Login automático**: Credenciais são lidas do `.env`. O número MFA é enviado via Telegram para aprovação remota no Microsoft Authenticator.
- **Sessão do browser**: Salva em `session_data/state.json`. Se expirar, o login automático é re-executado automaticamente.
- **Seletores OWA**: O scraper usa 3 estratégias de fallback. Use `--debug` quando seletores pararem de funcionar.
- **Segurança**: Nunca comite o `.env` — ele já está no `.gitignore`.
- **Human-in-the-loop**: O sistema **nunca** envia e-mails automaticamente — sempre salva como rascunho.
