# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_loop.py -v

# Run a single test function
pytest tests/test_loop.py::test_function_name -v

# Lint
ruff check nanobot/
ruff format nanobot/

# Run the CLI
nanobot onboard          # first-time setup
nanobot agent -m "..."   # send a message
nanobot gateway          # start the gateway server
nanobot status           # show current status

# Run UFPR automation
python -m ufpr_automation               # full pipeline (uses EMAIL_CHANNEL from .env)
python -m ufpr_automation --channel gmail  # force Gmail IMAP channel
python -m ufpr_automation --channel owa    # force OWA Playwright channel
python -m ufpr_automation --debug       # capture DOM + screenshot (OWA only)
python -m ufpr_automation --headed      # force visible browser (OWA only)
python -m ufpr_automation --perceber-only  # scrape only, no LLM (OWA only)

# Feedback — human corrections store (feeds DSPy in Marco II)
python -m ufpr_automation.feedback stats    # show feedback statistics
python -m ufpr_automation.feedback export   # export as JSON for DSPy training

# RAG — Vector store for institutional documents
pip install -e ".[rag]"                                        # install RAG deps
python -m ufpr_automation.rag.ingest                           # ingest all docs
python -m ufpr_automation.rag.ingest --subset estagio          # ingest only estágio
python -m ufpr_automation.rag.ingest --subset cepe/resolucoes  # ingest specific subset
python -m ufpr_automation.rag.ingest --dry-run                 # extract + chunk stats only
python -m ufpr_automation.rag.retriever "query em português"   # semantic search CLI
python -m ufpr_automation.rag.retriever "query" --conselho cepe --top-k 5
python -m ufpr_automation.rag.chat                             # interactive CLI (REPL)
python -m ufpr_automation.rag.chat --conselho cepe             # with pre-filter
streamlit run ufpr_automation/rag/web.py                        # Streamlit web UI (port 8501)

# RAPTOR — hierarchical RAG index (requires rag extras)
python -m ufpr_automation.rag.raptor                            # build RAPTOR tree
python -m ufpr_automation.rag.raptor --max-levels 3             # custom depth
python -m ufpr_automation.rag.raptor --dry-run                  # cluster stats only

# DSPy — prompt optimization (requires marco2 extras)
pip install -e ".[marco2]"
python -m ufpr_automation.dspy_modules.optimize --strategy gepa  # bootstrap (no data)
python -m ufpr_automation.dspy_modules.optimize --strategy mipro # requires 20+ feedback
python -m ufpr_automation.dspy_modules.optimize --evaluate-only  # evaluate current prompts

# LangGraph pipeline (Marco II)
python -m ufpr_automation --channel gmail --langgraph           # use LangGraph orchestrator

# Run UFPR automation tests
pytest ufpr_automation/tests/ -v
```

## Architecture

This repo contains two projects:

### nanobot (core framework)

An ultra-lightweight AI agent framework. The agent implements a simple sense → think → act loop.

**Key packages under `nanobot/`:**

- **`agent/`** — The core loop (`loop.py` ~23KB). Receives a message, builds context with system prompt + history, calls the LLM with available tools, executes tool calls, sends response back, persists session. Also contains memory consolidation, subagent spawning, and skills integration.
- **`providers/`** — 20+ LLM providers (OpenRouter, Anthropic, OpenAI, Azure, DeepSeek, Groq, Gemini, Ollama, etc.). Registry-based — no if-elif chains. Adding a provider requires only a `ProviderSpec` and a `ProvidersConfig` field.
- **`channels/`** — 11+ chat platform integrations (Telegram, Discord, Slack, WhatsApp, Feishu, DingTalk, QQ, Matrix, WeChat, Wecom, Email). Base class architecture; community plugins supported. Most use WebSocket/Socket.IO — no public IP required.
- **`tools/`** — Built-in agent tools: shell (with `restrictToWorkspace`), filesystem (path traversal protected), web search (Brave/Tavily/Jina/SearXNG/DuckDuckGo), web fetch (readability), cron (croniter), MCP (Model Context Protocol), spawn (background subagents), message (send to channels).
- **`session/`** — Conversation state grouped by channel+user.
- **`bus/`** — Message routing between channels and agent.
- **`cron/`** — Scheduled task execution.
- **`heartbeat/`** — Proactive periodic task wake-up.
- **`skills/`** — Bundled skills (GitHub, weather, Tmux, memory, summarize, skill-creator, cron).
- **`config/`** — Pydantic-based config schema and loader.
- **`cli/`** — Typer-based CLI (`nanobot` entrypoint).
- **`security/`** — Network access control.

**Data flow:** Channel receives message → Bus routes → Session groups by conversation → Agent loop (`loop.py`) processes → Tools execute → Response sent back via channel.

### ufpr_automation (sub-project)

A specialized deployment automating bureaucratic email processing at UFPR (Universidade Federal do Paraná). Currently in **Marco II (LangGraph + DSPy)** phase.

**Packages under `ufpr_automation/`:**

- **`gmail/`** — Gmail IMAP/SMTP client for reading forwarded emails (primary channel). Uses App Password auth — no MFA, no Playwright. `client.py` provides `list_unread()` (with attachment download), `save_draft()`, `send_reply()`, `mark_read()`.
- **`attachments/`** — Attachment text extraction module. `extractor.py` handles PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl), and plain text. Images/scanned PDFs flagged with `needs_ocr=True` for future OCR support. Downloaded files saved to `ATTACHMENTS_DIR`.
- **`outlook/`** — Playwright-based scraping of OWA (Outlook Web Access, fallback channel). Includes automated login with credential filling and MFA number-match notification via Telegram Bot. `locators.py` provides resilient locator fallback chains (semantic -> text -> ID -> CSS).
- **`llm/`** — LLM client for email classification and draft generation. Uses LiteLLM (provider-agnostic); configured for MiniMax-M2. Includes **Self-Refine** (generate -> critique -> refine cycle), RAG context injection, and attachment text injection.
- **`config/`** — `.env`-based settings (UTF-8 aware for Windows). Centralized credentials for Gmail, OWA, SIGA, SEI. Configurable RAG store/docs paths (`RAG_STORE_DIR`, `RAG_DOCS_DIR`). Attachment settings (`ATTACHMENTS_DIR`, `ATTACHMENT_MAX_SIZE_MB`).
- **`core/`** — Domain model (`EmailData` with `AttachmentData` list, `EmailClassification` with confidence score).
- **`rag/`** — RAG (Retrieval-Augmented Generation) module for institutional documents. `ingest.py` extracts text from 3,316 PDFs (PyMuPDF), chunks with legal-document-aware separators (LangChain), embeds with `multilingual-e5-large` (sentence-transformers), and indexes in LanceDB. `retriever.py` provides semantic search with metadata filters (conselho, tipo). `raptor.py` provides hierarchical RAPTOR indexing (GMM clustering + recursive summarization) with collapsed tree retrieval. RAG context is automatically injected into the LLM classification pipeline. Store path configurable via `RAG_STORE_DIR` env var for sharing across machines.
- **`graph/`** — LangGraph StateGraph orchestrator (Marco II). Nodes: perceber (Gmail/OWA) -> rag_retrieve (RAPTOR/flat + Reflexion) -> classificar (DSPy/LiteLLM) -> rotear (confidence routing) -> agir (save drafts). SQLite checkpointing for fault tolerance.
- **`dspy_modules/`** — DSPy Signatures and Modules for programmatic prompt optimization. `signatures.py` declares EmailClassifier, DraftCritic, DraftRefiner. `modules.py` composes them into SelfRefineModule. `metrics.py` provides quality metrics. `optimize.py` runs GEPA bootstrap or MIPROv2 optimization.
- **`feedback/`** — Human corrections store (append-only JSONL). Records original vs corrected classifications for DSPy prompt optimization. `reflexion.py` implements Reflexion pattern: auto-analyzes errors, stores in vector store, retrieves past mistakes as negative context. CLI for stats and export.
- **`workspace/`** — Nanobot integration files: `SOUL.md` (agent persona + internship regulations knowledge), `AGENTS.md`, `SKILL.md`, `config.json`.

The automation saves responses as drafts — never auto-sends (human-in-the-loop). See `ufpr_automation/ARCHITECTURE.md` for the planned 3-phase maturation roadmap (Marco I -> LangGraph -> GraphRAG/multi-agent).

## Configuration

- **`pyproject.toml`** — Package metadata, dependencies, Ruff config (line-length=100, target py311). Build backend: hatchling.
- **`.env`** (in `ufpr_automation/`) — Centralized credentials: Gmail (IMAP), OWA, SIGA, SEI, Telegram, LLM API keys. See `.env.example`.
- **`docker-compose.yml`** — Two services: `nanobot-gateway` (port 18790, 1 CPU) and `nanobot-cli`.
- **`nanobot/templates/`** — Default config templates copied during `nanobot onboard`.

## Branching

- `main` — Production releases
- `nightly` — Experimental / breaking changes
- Feature branches: `feat/<name>`
- Current branch `feat/marco-i-unified` — Marco I unified implementation with auto-login + MFA via Telegram.
