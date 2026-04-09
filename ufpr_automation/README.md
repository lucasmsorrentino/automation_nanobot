# 🤖 UFPR Automation

> Sistema de automação burocrática da Universidade Federal do Paraná. Lê e-mails institucionais, classifica via LLM, recupera contexto de normas (RAG vetorial + grafo Neo4j) e gera respostas como rascunho para revisão humana.

![Python](https://img.shields.io/badge/python-≥3.12-blue)
![Stack](https://img.shields.io/badge/stack-LangGraph%20%2B%20DSPy%20%2B%20RAPTOR%20%2B%20Neo4j-violet)
![Status](https://img.shields.io/badge/status-Marcos%20I%20%2B%20II%20%2B%20II.5%20✅-green)

## Sobre

Pipeline `Perceber → Pensar → Agir` orquestrado por **LangGraph**, alimentado por uma base vetorial de **34.285 chunks** de resoluções, atas e instruções normativas da UFPR (LanceDB + RAPTOR), enriquecida por um **grafo de conhecimento Neo4j** com 1.757 nós (hierarquia departamental, normas, fluxos, templates).

O sistema **nunca envia e-mails automaticamente** — sempre salva como rascunho para revisão humana.

> **Por que RPA via Playwright para OWA?** A governança de TI da UFPR bloqueia o registro de aplicativos para a Microsoft Graph API. O canal **Gmail IMAP** é o primário (forwarding do OWA). O canal OWA via Playwright existe como fallback.

## Arquitetura

| Camada | Componentes |
|---|---|
| **Canais** | `gmail/` (IMAP, primário) · `outlook/` (Playwright + auto-login + MFA Telegram, fallback) |
| **Anexos** | `attachments/` — PDF (PyMuPDF), DOCX, XLSX, OCR Tesseract para escaneados |
| **Memória vetorial** | `rag/` — LanceDB + RAPTOR hierárquico, multilingual-e5-large, 34K chunks |
| **Memória relacional** | `graphrag/` — Neo4j, 1.757 nós, normas com vigência (vigente/alterada/revogada) |
| **Memória episódica** | `feedback/reflexion.py` — análise + recall de erros passados |
| **LLM** | `llm/` — LiteLLM → MiniMax-M2, Self-Refine, model cascading (local/API/fallback) |
| **Otimização** | `dspy_modules/` — DSPy Signatures, GEPA / MIPROv2 |
| **Orquestrador** | `graph/` — LangGraph StateGraph + SQLite checkpointing |
| **Sistemas legados** | `sei/`, `siga/` — clients Playwright (read-only por enquanto) |
| **Procedimentos** | `procedures/store.py` — log JSONL para aprendizado contínuo |
| **Scheduler** | `scheduler.py` — APScheduler 3x/dia (configurável) |
| **Feedback UI** | `feedback/web.py` — Streamlit dashboard |
| **Persona/ICL** | `workspace/SOUL.md` — normas internas, fluxos, templates de e-mail |

Diagramas Mermaid completos em [`ARCHITECTURE.md`](ARCHITECTURE.md). Roadmap em [`TASKS.md`](TASKS.md).

## Quickstart

```bash
# 1. Instalar (na raiz do nanobot)
pip install -e ".[rag,marco2,marco3]"

# 2. Configurar credenciais
cp ufpr_automation/.env.example ufpr_automation/.env
# editar .env: GMAIL_*, MINIMAX_API_KEY, NEO4J_*, RAG_STORE_DIR, ...

# 3. Rodar pipeline (Gmail IMAP + LangGraph)
python -m ufpr_automation --channel gmail --langgraph

# 4. Ou rodar via scheduler (3x/dia)
python -m ufpr_automation --schedule
```

## CLI

| Comando | Descrição |
|---|---|
| `python -m ufpr_automation` | Pipeline (canal definido por `EMAIL_CHANNEL` no `.env`) |
| `python -m ufpr_automation --channel gmail --langgraph` | Pipeline LangGraph com Gmail IMAP |
| `python -m ufpr_automation --channel owa --headed --debug` | OWA Playwright visível com captura de DOM |
| `python -m ufpr_automation --perceber-only` | Apenas scraping, sem LLM (OWA only) |
| `python -m ufpr_automation --schedule [--once]` | Scheduler daemon (`--once` para rodar 1 vez) |

### RAG

```bash
# Ingerir documentos (PDF → chunks → embeddings → LanceDB)
python -m ufpr_automation.rag.ingest [--subset estagio | --dry-run | --ocr-only]

# Construir RAPTOR hierárquico
python -m ufpr_automation.rag.raptor [--max-levels 3]

# Buscar via CLI
python -m ufpr_automation.rag.retriever "prazo de estágio obrigatório" --conselho cepe --top-k 5

# REPL interativo
python -m ufpr_automation.rag.chat [--conselho cepe]

# Web UI (Streamlit, porta 8501)
streamlit run ufpr_automation/rag/web.py
```

### GraphRAG (Neo4j)

```bash
# Pré-requisito: Neo4j rodando em bolt://localhost:7687
docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/ufpr2026 neo4j:5

python -m ufpr_automation.graphrag.seed              # popular base
python -m ufpr_automation.graphrag.enrich            # extrair normas do RAG → Neo4j
```

### Feedback / DSPy

```bash
# Stats e revisão
python -m ufpr_automation.feedback stats
python -m ufpr_automation.feedback review

# Web UI (porta 8502)
streamlit run ufpr_automation/feedback/web.py

# Otimizar prompts
python -m ufpr_automation.dspy_modules.optimize --strategy gepa
```

## Configuração (`.env`)

Principais variáveis (ver `.env.example` para a lista completa):

```env
# Canal de e-mail
EMAIL_CHANNEL=gmail
GMAIL_EMAIL=...
GMAIL_APP_PASSWORD=...

# LLM
MINIMAX_API_KEY=...
LLM_MODEL=minimax/MiniMax-M2

# RAG (Google Drive compartilhado)
RAG_STORE_DIR=G:/Meu Drive/ufpr_rag/store
RAG_DOCS_DIR=G:/Meu Drive/ufpr_rag/docs

# GraphRAG
NEO4J_URI=bolt://localhost:7687
NEO4J_PASSWORD=...

# Scheduler
SCHEDULE_HOURS=8,13,17
SCHEDULE_TZ=America/Sao_Paulo

# OWA fallback (apenas se EMAIL_CHANNEL=owa)
OWA_EMAIL=...
OWA_PASSWORD=...
TELEGRAM_BOT_TOKEN=...    # MFA number-match
TELEGRAM_CHAT_ID=...
```

## Notas

- **Human-in-the-loop:** o sistema **nunca** envia e-mails. Sempre salva como rascunho.
- **Sessão Playwright (OWA):** persistida em `session_data/state.json`. Re-login automático quando expira.
- **Store RAG:** compartilhado via Google Drive (`G:/Meu Drive/ufpr_rag/store`). 167 MB, contém `ufpr_docs` (flat) + `ufpr_raptor` (hierárquico).
- **Cache de embeddings:** `multilingual-e5-large` em `~/.cache/huggingface/hub/`. Em uso intenso, set `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` para evitar 429.
- **Windows + UTF-8:** os CLIs `rag.chat` / `rag.retriever` reconfiguram `sys.stdout` para UTF-8 automaticamente.
- **Segurança:** o `.env` está no `.gitignore` — nunca comite credenciais.
- **Testes:** `pytest ufpr_automation/tests/ -v` (~160 testes).
