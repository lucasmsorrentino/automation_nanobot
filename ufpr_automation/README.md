# 🤖 UFPR Automation — Sistema de Automação Burocrática

<div align="center">
  <h3>Marco I — Protótipo de Ingestão Assistida</h3>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.12-blue" alt="Python">
    <img src="https://img.shields.io/badge/framework-nanobot-orange" alt="nanobot">
    <img src="https://img.shields.io/badge/RPA-Playwright-green" alt="Playwright">
    <img src="https://img.shields.io/badge/LLM-LiteLLM_%2B_MiniMax-violet" alt="LiteLLM + MiniMax">
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
| **Pensar** | LLM (MiniMax via LiteLLM) classifica cada e-mail e redige resposta em paralelo (asyncio.gather) | ✅ Implementado |
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
│   ├── pensar.py            # PensarAgent — classificação LLM via LiteLLM (paralelo)
│   └── agir.py              # AgirAgent — salva rascunhos no OWA
│
├── orchestrator.py          # 🎯 Coordenador Perceber → Pensar → Agir
│
├── llm/                     # 🧠 Integração LLM
│   └── client.py            # LLMClient via LiteLLM (sync + async)
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
│   ├── config.json          # Config do provider LLM
│   └── skills/
│       └── ufpr-outlook/
│           └── SKILL.md     # Skill do nanobot
│
├── rag/                     # 🔍 RAG — Retrieval-Augmented Generation
│   ├── __init__.py
│   ├── ingest.py            # Pipeline: PDF → texto → chunks → embeddings → LanceDB
│   ├── retriever.py         # Busca vetorial semântica com filtros
│   ├── chat.py              # CLI interativo (REPL) para consultas
│   ├── web.py               # Interface web (Streamlit) para consultas
│   └── store/               # Dados LanceDB (git-ignored, gerado automaticamente)
│
├── docs/                    # 📜 Corpus de documentos institucionais (git-ignored)
│   ├── cepe/                # CEPE: atas, resoluções, instruções normativas
│   ├── coun/                # COUN: atas, resoluções, instruções normativas
│   ├── coplad/              # COPLAD: atas, resoluções, instruções normativas
│   ├── concur/              # CONCUR: atas, resoluções
│   └── estagio/             # Manuais, leis e regulamentos de estágio
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

# LLM (MiniMax via LiteLLM)
MINIMAX_API_KEY=sua_chave_aqui
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

## 🔍 RAG — Base de Conhecimento Vetorial

O módulo RAG indexa os documentos institucionais da UFPR (resoluções, atas, instruções normativas, manuais de estágio) em um banco vetorial local (LanceDB) para busca semântica.

### Instalação

```bash
pip install -e ".[rag]"
```

### Uso

```bash
# Indexar todos os documentos
python -m ufpr_automation.rag.ingest

# Indexar apenas um subset
python -m ufpr_automation.rag.ingest --subset estagio
python -m ufpr_automation.rag.ingest --subset cepe/resolucoes

# Ver estatísticas sem indexar
python -m ufpr_automation.rag.ingest --dry-run

# Busca semântica via CLI
python -m ufpr_automation.rag.retriever "prazo máximo para estágio obrigatório"
python -m ufpr_automation.rag.retriever "rescisão de contrato" --conselho cepe --top-k 5

# Interface interativa (terminal)
python -m ufpr_automation.rag.chat
python -m ufpr_automation.rag.chat --conselho cepe    # com filtro pré-definido

# Interface web (Streamlit)
streamlit run ufpr_automation/rag/web.py               # abre em http://localhost:8501
```

### Uso via Python

```python
from ufpr_automation.rag.retriever import Retriever

r = Retriever()
results = r.search("regulamento de estágio", conselho="cepe", top_k=3)
context = r.search_formatted("prazo de estágio obrigatório")  # texto pronto para LLM
```

### Como adicionar novos documentos

1. **Coloque os PDFs** na estrutura de pastas `ufpr_automation/docs/`:

```
docs/
├── {conselho}/              # cepe, coun, coplad, concur (ou novo conselho)
│   ├── atas/
│   ├── resolucoes/
│   └── instrucoes-normativas/
└── estagio/                 # ou qualquer pasta temática
```

Os metadados (conselho, tipo) são extraídos automaticamente do caminho:
- `docs/cepe/resolucoes/res-42.pdf` → conselho=cepe, tipo=resolucoes
- `docs/estagio/manual.pdf` → conselho=estagio, tipo=estagio
- `docs/prograd/portarias/port-01.pdf` → conselho=prograd, tipo=portarias

2. **Rode o ingest** — o sistema é idempotente (pula arquivos já indexados):

```bash
# Só o subset novo
python -m ufpr_automation.rag.ingest --subset prograd/portarias

# Ou tudo (detecta e pula os já indexados)
python -m ufpr_automation.rag.ingest
```

3. **Pronto** — os novos documentos já aparecem nas buscas.

> **Nota:** Para reindexar um documento atualizado, apague a pasta `ufpr_automation/rag/store/` e rode o ingest novamente.

---

## 🏗️ Fases de Maturidade

| | Marco I | Marco II (Atual) | Marco III |
|---|---|---|---|
| **Orquestrador** | nanobot | LangGraph | LangGraph Fleet |
| **Memória** | ICL (System Prompt) | Vector RAG (LanceDB) | GraphRAG (Neo4j) |
| **Autonomia** | Rascunho + Humano | Auto (baixo risco) | Totalmente autônomo |
| **Sistemas** | OWA | OWA | OWA + SIGA + SEI |

> Veja o diagrama completo em [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 🔧 Stack Tecnológica

- **Python** ≥ 3.12
- **Playwright** — Automação de navegador (RPA)
- **nanobot** — Framework de agente AI (loop Perceber-Pensar-Agir)
- **LiteLLM + MiniMax-M2** — Motor cognitivo (provider-agnostic via LiteLLM, facilmente cambiável)
- **python-telegram-bot** — Notificação MFA via Telegram Bot
- **python-dotenv** — Gerenciamento de variáveis de ambiente
- **PyMuPDF** — Extração de texto de PDFs
- **LanceDB** — Banco vetorial local (zero servidor)
- **sentence-transformers** — Embeddings multilíngue (`multilingual-e5-large`)
- **LangChain Text Splitters** — Chunking semântico para documentos legais

---

## 📝 Notas Importantes

- **Login automático**: Credenciais são lidas do `.env`. O número MFA é enviado via Telegram para aprovação remota no Microsoft Authenticator.
- **Sessão do browser**: Salva em `session_data/state.json`. Se expirar, o login automático é re-executado automaticamente.
- **Seletores OWA**: O scraper usa 3 estratégias de fallback. Use `--debug` quando seletores pararem de funcionar.
- **Segurança**: Nunca comite o `.env` — ele já está no `.gitignore`.
- **Human-in-the-loop**: O sistema **nunca** envia e-mails automaticamente — sempre salva como rascunho.
