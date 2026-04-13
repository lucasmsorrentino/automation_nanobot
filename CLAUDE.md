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

# Scheduler — automatic pipeline execution (3x/day)
python -m ufpr_automation --schedule           # start scheduler daemon (8h, 13h, 17h)
python -m ufpr_automation --schedule --once    # run pipeline once now and exit

# Feedback — human corrections store (feeds DSPy optimization)
python -m ufpr_automation.feedback stats    # show feedback statistics
python -m ufpr_automation.feedback export   # export as JSON for DSPy training
python -m ufpr_automation.feedback review   # interactive review of last pipeline run
python -m ufpr_automation.feedback add      # manually add a correction
streamlit run ufpr_automation/feedback/web.py  # Streamlit feedback web UI (port 8502)

# OCR for attachments (requires Tesseract installed on the system)
pip install -e ".[ocr]"                    # install pytesseract + Pillow

# RAG — Vector store for institutional documents
pip install -e ".[rag]"                                        # install RAG deps
python -m ufpr_automation.rag.ingest                           # ingest all docs
python -m ufpr_automation.rag.ingest --subset estagio          # ingest only estágio
python -m ufpr_automation.rag.ingest --subset cepe/resolucoes  # ingest specific subset
python -m ufpr_automation.rag.ingest --dry-run                 # extract + chunk stats only
python -m ufpr_automation.rag.ingest --ocr-only                # re-ingest only previously empty PDFs (OCR)
python -m ufpr_automation.rag.ingest --no-ocr                  # disable Tesseract OCR fallback
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

# DSPy gate (Marco III) — controla uso do DSPy no classificar:
# USE_DSPY=auto  (default) — usa DSPy só se gepa_optimized.json existir
# USE_DSPY=on    — exige prompt compilado (raise se ausente)
# USE_DSPY=off   — sempre LiteLLM direto
USE_DSPY=auto python -m ufpr_automation --channel gmail --limit 5

# LangGraph pipeline (Marco II)
python -m ufpr_automation --channel gmail --langgraph           # use LangGraph orchestrator

# LangGraph Fleet (Marco III) — paraleliza Tier 1 via Send API
# Default já é Fleet. Configura tamanho do pool de browsers Playwright:
FLEET_BROWSER_POOL_SIZE=5 python -m ufpr_automation --channel gmail

# AFlow topology evaluator (Marco III) — 5 topologias hand-authored + evaluator
python -m ufpr_automation.aflow.cli --topologies all --limit 20            # eval all variants
python -m ufpr_automation.aflow.cli --topologies baseline,fleet --limit 10
AFLOW_TOPOLOGY=baseline python -m ufpr_automation --channel gmail   # força baseline em runtime
AFLOW_TOPOLOGY=fleet    python -m ufpr_automation --channel gmail   # default

# SEI write ops (Marco III + IV) — NUNCA sign/send/protocol
# Marco IV expandiu a API para 3 métodos:
#   create_process, attach_document, save_despacho_draft
python -c "from ufpr_automation.sei.writer import SEIWriter; print([m for m in dir(SEIWriter) if not m.startswith('_')])"

# SEI_WRITE_MODE (Marco IV) — dry_run (default, safe) | live
# dry_run: loga intenção + screenshot, NÃO clica em nada no SEI
# live:    fluxo Playwright completo (usa sei/writer_selectors.py para carregar
#          o manifesto YAML capturado em procedures_data/sei_capture/<ts>/sei_selectors.yaml;
#          override do path via SEI_SELECTORS_PATH). Sprint 3 de validação pendente
#          antes de usar em produção — ver smokes em scripts/smoke_writer_live_e2e.py.
SEI_WRITE_MODE=dry_run python -m ufpr_automation --channel gmail --langgraph

# Listar checkers de completeness registrados (Marco IV)
python -c "from ufpr_automation.procedures.checkers import registered_checkers; print('\n'.join(registered_checkers()))"

# Ver catálogo de classificações de documentos SEI (Marco IV)
cat ufpr_automation/workspace/SEI_DOC_CATALOG.yaml

# GraphRAG — Neo4j knowledge graph (Marco III, requires neo4j running on bolt://localhost:7687)
pip install -e ".[marco3]"
python -m ufpr_automation.graphrag.seed                         # populate base knowledge graph
python -m ufpr_automation.graphrag.seed --clear                 # clear graph + re-seed
python -m ufpr_automation.graphrag.seed --dry-run               # show connection + stats only
python -m ufpr_automation.graphrag.enrich                       # extract norms from RAG → Neo4j (with lineage)
python -m ufpr_automation.graphrag.enrich --dry-run             # extract only, print stats
python -m ufpr_automation.graphrag.enrich --conselho cepe       # filter by conselho

# Model cascading (Marco III) — set in .env:
# LLM_CLASSIFY_MODEL=ollama/qwen3:8b     # local model for classification
# LLM_DRAFT_MODEL=minimax/MiniMax-M2     # API model for drafting
# LLM_FALLBACK_MODEL=minimax/MiniMax-M2  # fallback if primary fails

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

A specialized deployment automating bureaucratic email processing at UFPR (Universidade Federal do Paraná). Currently in **Marco IV in progress** — Marcos I/II/II.5/III ✅ complete (Hybrid Memory Tier 0 + LangGraph Fleet + AFlow + SEIWriter + GraphRAG TemplateRegistry + DSPy USE_DSPY gate). Marco IV delivers Estágios end-to-end: extended `Intent` model (`sei_action`, `required_attachments`, `blocking_checks`, `despacho_template`), `SEI_DOC_CATALOG.yaml`, 11-checker registry in `procedures/checkers.py`, `SEIWriter` with **live mode wired up** (`create_process`/`attach_document`/`save_despacho_draft` via `sei/writer_selectors.py` + captured `sei_selectors.yaml`), dry-run mode still available as default. **Remaining**: Sprint 3 validation — run `scripts/smoke_writer_live_e2e.py` against a test SEI instance before flipping `SEI_WRITE_MODE=live` in production. Refinements pending: BrowserPagePool wire-up in SEI/SIGA helpers. See `TASKS.md` for the Marco IV priority list.

**Hybrid Memory (Tier 0 / Tier 1)** — the pipeline now routes every incoming email through a zero-cost playbook before spending RAG + LLM cycles:

- **Tier 0 — `procedures/playbook.py`**: parses `workspace/PROCEDURES.md` (fenced ` ```intent ` YAML blocks) into `Intent` objects. Routing combines keyword regex (score 1.0) and e5-large cosine similarity (threshold 0.90) against precomputed passage embeddings. A hit extracts variables from the email (sender name, TCE nº, SEI nº, GRR, dates), validates `required_fields`, fills the intent `template`, and emits a fully-formed `EmailClassification` — **no RAG, no classifier LLM call**. Staleness: if `intent.last_update` is older than `ufpr.lance/`'s mtime the intent is treated as stale and falls back to Tier 1.
- **Tier 1 — RAG + LLM**: unchanged path (RAPTOR/flat retrieval + Reflexion → DSPy/LiteLLM classifier). Only emails that Tier 0 missed (or had missing required fields, or are stale) ever reach this tier.
- **Short-circuit semantics** in `graph/builder.py`: `perceber → tier0_lookup → (if all Tier 0 hit) rotear` skips `rag_retrieve` and `classificar` entirely for fully-resolved batches. Partial batches run RAG/LLM only on the residual set; `classificar` merges Tier 0 classifications back into state (LangGraph dict reducers overwrite, so merging is explicit).
- **System prompt slimming** — `llm/client.py` now injects `workspace/SOUL_ESSENTIALS.md` (≈160 lines: identity, tone, categories, signature template) instead of the full `SOUL.md`. Detailed normative content lives in PROCEDURES.md (Tier 0), `base_conhecimento/` (SEI/SIGA manuals, ficha do curso), and the RAG vector store. If `SOUL_ESSENTIALS.md` is absent the client falls back to full SOUL.md with a warning.

**Packages under `ufpr_automation/`:**

- **`gmail/`** — Gmail IMAP/SMTP client for reading forwarded emails (primary channel). Uses App Password auth — no MFA, no Playwright. `client.py` provides `list_unread()` (with attachment download), `save_draft()`, `send_reply()`, `mark_read()`. `thread.py` splits email bodies into (new_reply, quoted_history) by detecting `Em … escreveu:` / `On … wrote:` / `-----Mensagem Original-----` / `>` quoting — used by the LLM prompt so the model can tell what the sender is asking *now* vs. what was said before in the thread.
- **`attachments/`** — Attachment text extraction module. `extractor.py` handles PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl), plain text, and **OCR** (Tesseract via pytesseract) for scanned PDFs and images. Falls back to `needs_ocr=True` if Tesseract is not installed. Downloaded files saved to `ATTACHMENTS_DIR`.
- **`outlook/`** — Playwright-based scraping of OWA (Outlook Web Access, fallback channel). Includes automated login with credential filling and MFA number-match notification via Telegram Bot. `locators.py` provides resilient locator fallback chains (semantic -> text -> ID -> CSS).
- **`llm/`** — LLM client for email classification and draft generation. Uses LiteLLM (provider-agnostic); configured for MiniMax-M2. Includes **Self-Refine** (generate -> critique -> refine cycle), RAG context injection, attachment text injection, and **model cascading** (`router.py` — routes classification to cheap/local models and drafting to capable API models, with automatic fallback).
- **`config/`** — `.env`-based settings (UTF-8 aware for Windows). Centralized credentials for Gmail, OWA, SIGA, SEI. RAG store/docs paths (`RAG_STORE_DIR`, `RAG_DOCS_DIR`) and feedback/procedures paths (`FEEDBACK_DATA_DIR`, `PROCEDURES_DATA_DIR`) shared via Google Drive (`G:/Meu Drive/ufpr_rag/`) so the same state is seen across multiple machines (work ↔ home). Attachment settings (`ATTACHMENTS_DIR`, `ATTACHMENT_MAX_SIZE_MB`).
- **`core/`** — Domain model (`EmailData` with `AttachmentData` list, `EmailClassification` with confidence score). The `Categoria` Literal uses a hierarchical taxonomy with ` / ` as separator: `Estágios`, `Acadêmico / {Matrícula,Equivalência de Disciplinas,Aproveitamento de Disciplinas,Ajuste de Disciplinas}`, `Diplomação / {Diploma,Colação de Grau}`, `Extensão`, `Formativas`, `Requerimentos`, `Urgente`, `Correio Lixo`, `Outros` (13 values total). Legacy categories (Ofícios/Memorandos/Portarias/Informes) were retired; `dspy_modules/modules.py` keeps aliases that remap them to `Outros` for backward compatibility.
- **`rag/`** — RAG (Retrieval-Augmented Generation) module for institutional documents. `ingest.py` extracts text from 3,316 PDFs (PyMuPDF + Tesseract OCR fallback for scanned docs), chunks with legal-document-aware separators (LangChain), embeds with `multilingual-e5-large` (sentence-transformers), and indexes in LanceDB (34,285 chunks, 99.2% coverage). Supports `--ocr-only` for re-ingesting previously empty PDFs. `retriever.py` provides semantic search with metadata filters (conselho, tipo). `raptor.py` provides hierarchical RAPTOR indexing (GMM clustering + recursive summarization) with collapsed tree retrieval. RAG context is automatically injected into the LLM classification pipeline. Store shared via Google Drive (`RAG_STORE_DIR=G:/Meu Drive/ufpr_rag/store`).
- **`sei/`** — SEI (Sistema Eletrônico de Informações) integration via Playwright. **`client.py`** is READ-ONLY (search processes, extract documents, prepare despacho drafts via `TemplateRegistry`). **`writer.py`** is the WRITE layer (Marco III + IV): `SEIWriter` exposes ONLY `create_process`, `attach_document`, and `save_despacho_draft`. There are NO `sign()`, `send()`, `protocol()`, or `finalize()` methods — architectural absence is the safety mechanism. `_FORBIDDEN_SELECTORS` runtime guard + `_safe_click` enforce the boundary (raises `PermissionError` on any click matching "assinar/enviar processo/protocolar/btnAssinar/etc."). 6 regression tests in `test_sei_writer.py::TestWriterArchitecturalSafety` verify the absence + a static source scan ensures no `.click('text=Assinar')` is ever introduced. **`writer_selectors.py`** lazily loads `sei_selectors.yaml` (captured via `scripts/sei_drive.py`) and re-validates every leaf selector against `_FORBIDDEN_SELECTORS` at load time (belt-and-suspenders). Audit trail: screenshots + DOM dumps + JSONL log per write op in `SEI_WRITE_ARTIFACTS_DIR`. Login automático via credenciais `.env`.
- **`siga/`** — SIGA (Sistema Integrado de Gestão Acadêmica) integration via Playwright. READ-ONLY: checks student status, enrollment, validates internship eligibility per SOUL.md section 11 rules.
- **`procedures/`** — Two concerns: (1) **`playbook.py`** — the Tier 0 router described above. `Intent` (pydantic) + `Playbook` class (keyword + semantic lookup, lazy `sentence-transformers` load, precomputed embeddings, `is_stale()` vs RAG mtime). `parse_procedures_md()` reads fenced ` ```intent ` / ` ```yaml ` blocks from `workspace/PROCEDURES.md`; `extract_variables()` regex-extracts TCE nº, SEI nº, GRR, dates and sender name; `fill_template()` supports both `[UPPER_CASE]` and `{{ jinja_like }}` placeholders and leaves unknown ones in place for human review. `get_playbook()` is a module-level `lru_cache` singleton. (2) Procedure *logging* for learning — JSONL at `PROCEDURES_DATA_DIR` records steps, duration, outcome, SEI/SIGA consultations.
- **`graph/`** — LangGraph StateGraph orchestrator (Marco II + III). Nodes: perceber (Gmail/OWA) → **tier0_lookup (Hybrid Memory)** → **dispatch_tier1 (Fleet fan-out via `Send` API)** → process_one_email (RAG + classify + SEI/SIGA per-email, parallel) → rotear → registrar_feedback → agir → registrar_procedimento. `state.EmailState.tier0_hits` carries the stable_ids resolved by Tier 0 so the Fleet dispatcher only fans out the residual set. **`fleet.py`** contains `dispatch_tier1`, `process_one_email`, and `SubState`. **`browser_pool.py`** provides `BrowserPagePool` with `asyncio.Semaphore(POOL_SIZE)` for sharing Playwright pages across sub-agents (env: `FLEET_BROWSER_POOL_SIZE`, default 3). State reducers `Annotated[..., _merge_dict]` on `rag_contexts`/`classifications`/`sei_contexts`/`siga_contexts` ensure parallel branches merge instead of last-write-wins. Legacy nodes (`rag_retrieve`, `classificar`, `consultar_sei`, `consultar_siga`) remain in `nodes.py` for the AFlow `baseline` topology variant. **DSPy gate** in `nodes.py` (`_should_use_dspy`, `_compiled_prompt_paths`, `_has_compiled_prompt`) reads `settings.USE_DSPY` to choose between DSPy SelfRefineModule and LiteLLM. SQLite checkpointing for fault tolerance.
- **`dspy_modules/`** — DSPy Signatures and Modules for programmatic prompt optimization. `signatures.py` declares EmailClassifier, DraftCritic, DraftRefiner. `modules.py` composes them into SelfRefineModule. `metrics.py` provides quality metrics. `optimize.py` runs GEPA bootstrap or MIPROv2 optimization.
- **`feedback/`** — Human corrections store (append-only JSONL). Records original vs corrected classifications for DSPy prompt optimization. Storage location is configurable via `FEEDBACK_DATA_DIR` (default local, can point to Google Drive to share state across machines). `reflexion.py` implements Reflexion pattern: auto-analyzes errors, stores in vector store, retrieves past mistakes as negative context. CLI for stats and export. `web.py` provides Streamlit dashboard for reviewing classifications, approving/correcting drafts, and viewing learning statistics.
- **`graphrag/`** — Neo4j GraphRAG knowledge graph (Marco III). `client.py` wraps the Neo4j driver. `schema.py` defines node types (Orgao, Norma, TipoProcesso, Documento, Papel, Sistema, Template, Fluxo, Etapa, Pessoa, Curso, Disciplina, SigaAba) and relationships. `seed.py` populates the graph from institutional knowledge (SOUL.md, SEI/SIGA manuals, ClaudeCowork). After Marco III, `_seed_templates` also persists `Template.conteudo` and `Template.despacho_tipo` (the despacho bodies that used to live hardcoded in `sei/client.py`). `retriever.py` provides graph-aware retrieval: workflow matching, norm lookup, template selection, SIGA navigation hints, org contacts. **`templates.py`** (Marco III) — `TemplateRegistry` class with in-memory cache and `get_registry()` singleton; consumed by `sei/client.py:prepare_despacho_draft` and `sei/writer.py:save_despacho_draft` via lazy import to avoid circular dep. Fallback `campos_pendentes=["neo4j_unavailable"]` if Neo4j offline. Integrated into `process_one_email` (Fleet) alongside vector RAG.

- **`aflow/`** — AFlow topology evaluator (Marco III). NOT a neural search — a hand-authored variant registry + offline evaluator. `topologies.py` registers 5 variants (`baseline`, `fleet`, `skip_rag_high_tier0`, `no_self_refine`, `fleet_no_siga`). `evaluator.py:evaluate()` runs each topology against an eval set with pluggable `metric_fn` and `invoke_fn` (default stub returns expected categoria for unit tests). `optimizer.py:pick_best_topology()` picks by `(accuracy, -latency_mean_ms, -errors)` and writes a JSON report. `cli.py` is the CLI entrypoint. `graph/builder.py:build_graph` dispatches to `aflow.topologies.get_topology(name)` when `AFLOW_TOPOLOGY != "fleet"`, preserving default Fleet behavior. Cold start: if `feedback_data/` is empty, the optimizer falls back to synthetic examples from `dspy_modules/optimize.py`.
- **`scheduler.py`** — APScheduler-based pipeline scheduler. Runs LangGraph pipeline 3x/day (configurable via `SCHEDULE_HOURS`, `SCHEDULE_TZ`). CLI: `--schedule` (daemon) or `--schedule --once`.
- **`workspace/`** — Nanobot integration files: `SOUL.md` (full agent persona + normative detail), **`SOUL_ESSENTIALS.md`** (slim system-prompt slice — identity, tone, categories, signature — injected per LLM call), **`PROCEDURES.md`** (Tier 0 playbook of intents organized by SEI process type), `AGENTS.md`, `SKILL.md`, `config.json`.
- **`base_conhecimento/`** — Operational reference files used to author the playbook and train prompts: `manual_sei.txt`, `manual_siga.txt`, `FichaDoCurso.txt`, `procedimentos.md`. These are plain-text, not embedded into RAG (they drive human-readable authoring of `PROCEDURES.md`).
- **`ClaudeCowork/`** — Base de conhecimento from Claude Cowork: SEI manual, SIGA manual, course data, internship guides, email templates, scheduled skills (morning/afternoon email checks).

The automation saves responses as drafts — never auto-sends (human-in-the-loop). See `ufpr_automation/ARCHITECTURE.md` for the planned 3-phase maturation roadmap (Marco I -> LangGraph -> GraphRAG/multi-agent).

## Configuration

- **`pyproject.toml`** — Package metadata, dependencies, Ruff config (line-length=100, target py311). Build backend: hatchling.
- **`.env`** (in `ufpr_automation/`) — Centralized credentials: Gmail (IMAP), OWA, SIGA, SEI, Telegram, LLM API keys. See `.env.example`.
- **`docker-compose.yml`** — Two services: `nanobot-gateway` (port 18790, 1 CPU) and `nanobot-cli`.
- **`nanobot/templates/`** — Default config templates copied during `nanobot onboard`.

## Windows notes

- **RAG store on Google Drive**: `RAG_STORE_DIR=G:/Meu Drive/ufpr_rag/store`. Requires Google Drive for Desktop installed and running (mounts at `G:` by default). First access to a file may trigger on-demand download.
- **HuggingFace offline mode**: the `multilingual-e5-large` model is cached at `~/.cache/huggingface/hub/`. To avoid 429 rate-limit errors from HuggingFace on repeated RAG queries, set before running any `ufpr_automation.rag.*` command:
  ```bash
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
  ```
- **UTF-8 stdout**: RAG CLI entrypoints (`retriever`, `chat`) auto-reconfigure `sys.stdout` to UTF-8 on Windows to handle documents containing characters outside cp1252 (e.g. ligatures). Other scripts printing document text should do the same or the user must set `PYTHONIOENCODING=utf-8`.

## Branching

- `main` — Production releases
- `nightly` — Experimental / breaking changes
- Feature branches: `feat/<name>`
- Current branch `feat/marco-i-unified` — Marco I+II+III unified implementation (LangGraph + DSPy + RAPTOR + Gmail + model cascading + Neo4j GraphRAG).
