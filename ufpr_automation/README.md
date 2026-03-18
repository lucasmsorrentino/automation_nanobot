# 🤖 UFPR Automation — Sistema de Automação Burocrática

<div align="center">
  <h3>Marco I — Protótipo de Ingestão Assistida</h3>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.12-blue" alt="Python">
    <img src="https://img.shields.io/badge/framework-nanobot-orange" alt="nanobot">
    <img src="https://img.shields.io/badge/RPA-Playwright-green" alt="Playwright">
    <img src="https://img.shields.io/badge/LLM-Gemini_1.5_Pro-violet" alt="Gemini">
  </p>
</div>

---

## 📋 Sobre

Sistema de automação burocrática para a **Universidade Federal do Paraná (UFPR)** que utiliza RPA (Robotic Process Automation) via Playwright para acessar o **Outlook Web Access (OWA)** e integração com LLMs para classificação e redação de respostas a e-mails institucionais.

> **Por que RPA?** A governança de TI da UFPR bloqueia o registro de aplicativos para a Microsoft Graph API. A integração com o e-mail é feita obrigatoriamente via Web Scraping do OWA usando Playwright.

### Ciclo Perceber → Pensar → Agir

| Fase | Descrição | Status |
|------|-----------|--------|
| **Perceber** | Playwright navega até o OWA, extrai e-mails não lidos (remetente, assunto, corpo) | ✅ Implementado |
| **Pensar** | Gemini classifica o e-mail e redige resposta seguindo normas UFPR (ICL) | 🔜 Próximo passo |
| **Agir** | Playwright clica em "Responder", digita a resposta e salva como **rascunho** | 🔜 Próximo passo |
| **Notificar** | Alerta no terminal que há ações pendentes para revisão humana | ✅ Implementado |

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
├── outlook/                 # 📧 Integração OWA via Playwright
│   ├── __init__.py
│   ├── browser.py           # Ciclo de vida do navegador + sessão
│   └── scraper.py           # Extração de e-mails (3 estratégias)
│
├── cli/                     # 💻 Interface de linha de comando
│   ├── __init__.py
│   └── commands.py          # Entry point com argparse
│
├── utils/                   # 🔧 Utilitários
│   ├── __init__.py
│   └── debug.py             # Captura DOM + screenshot para debug
│
├── docs/                    # 📚 Documentação complementar
│   └── CHANNEL_PLUGIN_GUIDE.md
│
├── workspace/               # 🐈 Integração com nanobot

│   ├── AGENTS.md            # Personalidade do agente
│   ├── SOUL.md              # Normas UFPR (ICL context)
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

Edite o `.env` com sua API key do Gemini e URLs do OWA:

```env
GEMINI_API_KEY=sua_chave_aqui
OWA_URL=https://outlook.office365.com/mail/
```

### 3. Primeiro Uso — Login Manual

```bash
python -m ufpr_automation
```

O navegador abrirá em modo visível. Faça login no OWA da UFPR manualmente. A sessão será salva automaticamente em `session_data/state.json`.

### 4. Execuções Seguintes — Headless

```bash
python -m ufpr_automation
```

O script detecta a sessão salva e executa em background (headless), imprimindo os e-mails no terminal.

---

## 💻 Comandos CLI

| Comando | Descrição |
|---------|-----------|
| `python -m ufpr_automation` | Execução padrão (auto-detecta sessão) |
| `python -m ufpr_automation --dry-run` | Testa Playwright sem login |
| `python -m ufpr_automation --headed` | Força modo com janela visível |
| `python -m ufpr_automation --debug` | Captura DOM + screenshot para debug |

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
- **python-dotenv** — Gerenciamento de variáveis de ambiente

---

## 📝 Notas Importantes

- **Sessão do browser**: Salva em `session_data/state.json`. Se expirar, delete o arquivo e execute novamente.
- **Seletores OWA**: O scraper usa 3 estratégias de fallback. Use `--debug` quando seletores pararem de funcionar.
- **Segurança**: Nunca comite o `.env` — ele já está no `.gitignore`.
- **Human-in-the-loop**: O sistema **nunca** envia e-mails automaticamente — sempre salva como rascunho.
