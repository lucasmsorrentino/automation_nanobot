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

# Limita quantos sub-agentes Tier 1 rodam concorrentemente (semáforo em
# graph/fleet.py). Complementa o singleton do SentenceTransformer em
# rag/_embedder.py — com ambos em vigor a RAM fica flat independente de N.
# Default 2. O default prático depende da RAM disponível: 1 se <8 GB livre,
# 2-3 com 16 GB, 4+ com 32 GB.
FLEET_MAX_CONCURRENT_SUBAGENTS=1 python -m ufpr_automation --channel gmail

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
#          o manifesto YAML. Default path: G:/Meu Drive/ufpr_automation_files/sei_selectors.yaml
#          (shared Drive — ~procedures_data/sei_capture/ local legacy fallback); override
#          via SEI_SELECTORS_PATH). Sprint 3 fix Ctrl+A+Delete aplicado a
#          save_despacho_draft em 2026-04-14; validação e2e live completa em
#          2026-04-16 (run_id c0357e8dd8f2, processo 23075.022027/2026-22, 3 ops
#          mode=live success=true, body do despacho confirmado limpo via
#          screenshot). Default em prod continua dry_run até Fleet smoke em batch.
#          Audit de cobertura de selectors vs POPs: ufpr_automation/sei/SELECTOR_AUDIT.md.
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

# Model cascading (Marco III) — set in .env:
# LLM_CLASSIFY_MODEL=ollama/qwen3:8b     # local model for classification
# LLM_DRAFT_MODEL=minimax/MiniMax-M2     # API model for drafting
# LLM_FALLBACK_MODEL=minimax/MiniMax-M2  # fallback if primary fails

# Run UFPR automation tests
pytest ufpr_automation/tests/ -v

# UFPR Aberta (Moodle) — scraper do curso "Conheça o SIGA!"
# 1ª vez: --headed para validar login; depois sessão persistida em session_data/ufpr_aberta_state.json
python -m ufpr_automation.ufpr_aberta --headed            # 1ª execução
python -m ufpr_automation.ufpr_aberta                     # headless (sessão salva)
python -m ufpr_automation.ufpr_aberta --course-id 42      # outro curso no Moodle
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

A specialized deployment automating bureaucratic email processing at UFPR (Universidade Federal do Paraná). Currently in **Marco IV in progress** — Marcos I/II/II.5/III ✅ complete (Hybrid Memory Tier 0 + LangGraph Fleet + AFlow + SEIWriter + GraphRAG TemplateRegistry + DSPy USE_DSPY gate). Marco IV delivers Estágios end-to-end: extended `Intent` model (`sei_action`, `required_attachments`, `blocking_checks`, `despacho_template`, `acompanhamento_especial_grupo`), `SEI_DOC_CATALOG.yaml`, **15-checker** registry in `procedures/checkers.py` (11 iniciais + 4 aditivo/conclusão: `sei_processo_tce_existente`, `aditivo_antes_vencimento_tce`, `duracao_total_ate_24_meses`, `relatorio_final_assinado_orientador`), `SEIWriter` with **live mode wired up** for `create_process`/`attach_document`/`save_despacho_draft` (via `sei/writer_selectors.py` + captured `sei_selectors.yaml`) plus a **dry-run skeleton** for `add_to_acompanhamento_especial` (POP-38; live path raises `NotImplementedError` pending fresh selector capture). Dry-run remains the default `SEI_WRITE_MODE`. **Sprint 3 validado em 2026-04-16** (run_id `c0357e8dd8f2`, processo fictício `23075.022027/2026-22`): 3 ops `mode=live` `success=true`, body do despacho limpo (fix Ctrl+A+Delete do `_clear_editor_body` confirmado). Side-effect: corrigido `sei/browser.py:auto_login` — sei.ufpr.br tem decoy `<input type="password" name="pwdSenha">` hidden competindo com o campo real `<input type="text" id="pwdSenha">`; selector agora é `input#pwdSenha` puro + `#sbmAcessar` como botão primário. **Remaining**: flipar `SEI_WRITE_MODE=live` como default em prod depois de Fleet smoke em batch pequeno (10 emails reais). Tasks abertas: POP-38 live wire-up (bloqueado em nova captura de selectors — spec em `ufpr_automation/sei/SELECTOR_AUDIT.md §1`; dry-run + unit tests já prontos), live-path mocks, BrowserPagePool wire-up em SEI/SIGA helpers (parked pending Fleet async refactor). See `TASKS.md` for the Marco IV priority list.

**SEI process lookup cascade** — ordem (mais precisa → menos precisa): (1) nº SEI UFPR `23075.*` explícito no texto/anexos → `SEIClient.search_process`, (2) GRR → `SEIClient.find_in_acompanhamento_especial(grr)` via `#txtPalavrasPesquisaAcompanhamento` + parse de `#tblAcompanhamentos` (AE curado por unit — descarta IFPR/MEC/arquivados), (3) AE por nome (extraído via `extract_candidate_names`): primeiro nome completo, depois curto (`shorten_name_first_last`, drop middle names). Motivação: secretarias frequentemente indexam o AE só pelo nome (ex. "Matheus Albers"), sem GRR — sem esse fallback, AE-GRR retorna 0 mesmo com o processo ativo lá. (4) fallback final: GRR → `find_processes_by_grr` via `#txtPesquisaRapida` + parse de `table.pesquisaResultado`. Quando volta N>1, `select_best_processo` desambigua em 2 fases: ano dominante (mais novo = ativo — regra do usuário) → desempate intra-ano por status/tipo/GRR/data. `lookup_mode` vira `"ae_grr"` | `"ae_name_full"` | `"ae_name_short"` | `"grr"` (pesquisa rápida) conforme o path que resolveu. **Cascade implementada nos 2 paths**: `_consult_sei_async` (batch do `consultar_sei`) **e** `_consult_sei_for_email` (Fleet per-email, que é o que roda em prod). Validado ao vivo 2026-04-22. `SIGAClient._navigate_to_student` bumpa pagination pra 300 antes do filter (filter é client-side, default era 20/página e escondia alunos fora da 1ª página). `extract_sei_process_number` e parser AE restritos a prefixo UFPR para ignorar IFPR/MEC.

**Supervisor eligibility (2026-04-22)** — novo checker `supervisor_formacao_compativel` (SOFT block) em `procedures/checkers.py` exige Declaração de Experiência do Supervisor (form PROGRAD) quando a formação do supervisor extraída do TCE não aparenta ser afim a Design. Base legal: Art. 9 Lei 11.788/2008 + Art. 10 Res. CEPE 46/10. Lista curada de ~28 áreas afins (`_SUPERVISOR_AREAS_AFINS_DESIGN`) com comparação accent-insensitive + case-insensitive. Extração em `playbook.py:extract_variables` via `_SUPERVISOR_NOME_RE` + `_SUPERVISOR_FORMACAO_RE` (labels "Supervisor:", "Formação:", "Cargo:", "Graduação:"). Pass silencioso quando o dado não foi extraído (outros checkers cuidam de TCE incompleto). Registrado em `blocking_checks` do intent `estagio_nao_obrig_acuse_inicial` — 16º checker no registry.

**Human-replied thread detection & learning corpus** — when the human coordinator replies manually from `design.grafico@ufpr.br` (CC'd to `design.grafico.ufpr@gmail.com`), the pipeline detects it via Gmail's `X-GM-THRID` IMAP extension (`gmail/client.py:thread_last_sender`) and:
1. Sets `EmailData.already_replied_by_us=True` in `perceber_gmail`.
2. `agir_gmail` and `agir_estagios` skip drafting for that thread.
3. The `capturar_corpus_humano` node (between `agir` and `registrar_procedimento`) copies the whole thread to the Gmail label `aprendizado/interacoes-secretaria-humano` (created on first use) and appends a `{thread_id, categoria, intent_name, labeled_at}` entry to `feedback_data/learning_corpus.jsonl`. Idempotent per `thread_id`; marks the CC'd reply as read.
4. Env vars: `INSTITUTIONAL_EMAIL` (default `design.grafico@ufpr.br`), `GMAIL_LEARNING_LABEL` (default `aprendizado/interacoes-secretaria-humano` — empty string disables corpus capture entirely).
5. Future Marco V item: `agent_sdk/human_corpus_harvester.py` will mine this label as few-shot for `intent_drafter.py` (see `TASKS.md` "Marco V futuro — Mineração do corpus de aprendizado humano").

**Hybrid Memory (Tier 0 / Tier 1)** — the pipeline now routes every incoming email through a zero-cost playbook before spending RAG + LLM cycles:

- **Tier 0 — `procedures/playbook.py`**: parses `workspace/PROCEDURES.md` (fenced ` ```intent ` YAML blocks) into `Intent` objects. Routing combines keyword regex (score 1.0) and e5-large cosine similarity (threshold 0.90) against precomputed passage embeddings. A hit extracts variables from the email (sender name, TCE nº, SEI nº, GRR, dates), validates `required_fields`, fills the intent `template`, and emits a fully-formed `EmailClassification` — **no RAG**. The Tier 0/1 boundary is defined by RAG (the expensive retrieval + context injection step), not LLM inference: intents may declare `llm_extraction_fields` to pull free-text fields (e.g. `lista_pendencias`) via a single bounded LLM call against the cheap CLASSIFY model, still inside Tier 0. Staleness: if `intent.last_update` is older than `ufpr.lance/`'s mtime the intent is treated as stale and falls back to Tier 1.
- **Tier 1 — RAG + LLM**: unchanged path (RAPTOR/flat retrieval + Reflexion → DSPy/LiteLLM classifier). Only emails that Tier 0 missed (or had missing required fields, or are stale) ever reach this tier.
- **Short-circuit semantics** in `graph/builder.py`: `perceber → tier0_lookup → (if all Tier 0 hit) rotear` skips `rag_retrieve` and `classificar` entirely for fully-resolved batches. Partial batches run RAG/LLM only on the residual set; `classificar` merges Tier 0 classifications back into state (LangGraph dict reducers overwrite, so merging is explicit).
- **System prompt slimming** — `llm/client.py` now injects `workspace/SOUL_ESSENTIALS.md` (≈160 lines: identity, tone, categories, signature template) instead of the full `SOUL.md`. Detailed normative content lives in PROCEDURES.md (Tier 0), `base_conhecimento/` (SEI/SIGA manuals, ficha do curso), and the RAG vector store. If `SOUL_ESSENTIALS.md` is absent the client falls back to full SOUL.md with a warning.

**Packages under `ufpr_automation/`:**

- **`gmail/`** — Gmail IMAP client for reading forwarded emails (primary channel). Uses App Password auth — no MFA, no Playwright. `client.py` provides `list_unread()` (with attachment download), `save_draft()`, `mark_read()`. `thread.py` splits email bodies into (new_reply, quoted_history) by detecting `Em … escreveu:` / `On … wrote:` / `-----Mensagem Original-----` / `>` quoting — used by the LLM prompt so the model can tell what the sender is asking *now* vs. what was said before in the thread. **`save_draft` anti-hallucination pipeline (2026-04-23)**: every draft body is passed through `normalize_signature_block(body, settings.ASSINATURA_EMAIL)` which (a) locates the LAST sign-off marker (`Atenciosamente`/`Att`/`Cordialmente`/`Saudações`/`Respeitosamente` on its own line), (b) cuts everything from there onwards, (c) strips any line containing a known hallucinated sector (`_HALLUCINATED_SECTORS` whitelist — started with "Núcleo de Estágios" after MiniMax-M2 invented it for the Paloma aditivo 2026-04-23 run), (d) appends the canonical `settings.ASSINATURA_EMAIL`. Idempotent. `save_draft` also dedupes within the recipient's thread before APPEND (`_delete_existing_drafts`): stale drafts from previous pipeline runs are removed so the reviewer sees exactly one current version per thread.
- **`attachments/`** — Attachment text extraction module. `extractor.py` handles PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl), plain text, and **OCR** (Tesseract via pytesseract) for scanned PDFs and images. Falls back to `needs_ocr=True` if Tesseract is not installed. Downloaded files saved to `ATTACHMENTS_DIR`.
- **`outlook/`** — Playwright-based scraping of OWA (Outlook Web Access, fallback channel). Includes automated login with credential filling and MFA number-match notification via Telegram Bot. `locators.py` provides resilient locator fallback chains (semantic -> text -> ID -> CSS).
- **`llm/`** — LLM client for email classification and draft generation. Uses LiteLLM (provider-agnostic); configured for MiniMax-M2. Includes **Self-Refine** (generate -> critique -> refine cycle), RAG context injection, attachment text injection, and **model cascading** (`router.py` — routes classification to cheap/local models and drafting to capable API models, with automatic fallback).
- **`config/`** — `.env`-based settings (UTF-8 aware for Windows). Centralized credentials for Gmail, OWA, SIGA, SEI. RAG store/docs paths (`RAG_STORE_DIR`, `RAG_DOCS_DIR`) and feedback/procedures paths (`FEEDBACK_DATA_DIR`, `PROCEDURES_DATA_DIR`) shared via Google Drive (`G:/Meu Drive/ufpr_rag/`) so the same state is seen across multiple machines (work ↔ home). Attachment settings (`ATTACHMENTS_DIR`, `ATTACHMENT_MAX_SIZE_MB`).
- **`core/`** — Domain model (`EmailData` with `AttachmentData` list, `EmailClassification` with confidence score). The `Categoria` Literal uses a hierarchical taxonomy with ` / ` as separator: `Estágios`, `Acadêmico / {Matrícula,Equivalência de Disciplinas,Aproveitamento de Disciplinas,Ajuste de Disciplinas}`, `Diplomação / {Diploma,Colação de Grau}`, `Extensão`, `Formativas`, `Requerimentos`, `Urgente`, `Correio Lixo`, `Outros` (13 values total). Legacy categories (Ofícios/Memorandos/Portarias/Informes) were retired; `dspy_modules/modules.py` keeps aliases that remap them to `Outros` for backward compatibility.
- **`rag/`** — RAG (Retrieval-Augmented Generation) module for institutional documents. `ingest.py` extracts text from 3,316 PDFs (PyMuPDF + Tesseract OCR fallback for scanned docs), chunks with legal-document-aware separators (LangChain), embeds with `multilingual-e5-large` (sentence-transformers), and indexes in LanceDB (34,285 chunks, 99.2% coverage). Supports `--ocr-only` for re-ingesting previously empty PDFs. `retriever.py` provides semantic search with metadata filters (conselho, tipo). `raptor.py` provides hierarchical RAPTOR indexing (GMM clustering + recursive summarization) with collapsed tree retrieval. RAG context is automatically injected into the LLM classification pipeline. Store shared via Google Drive (`RAG_STORE_DIR=G:/Meu Drive/ufpr_rag/store`).
- **`sei/`** — SEI (Sistema Eletrônico de Informações) integration via Playwright. **`client.py`** is READ-ONLY (search processes, extract documents, prepare despacho drafts via `TemplateRegistry`). **`writer.py`** is the WRITE layer (Marco III + IV): `SEIWriter` exposes ONLY `create_process`, `attach_document`, `save_despacho_draft`, and `add_to_acompanhamento_especial`. There are NO `sign()`, `send()`, `protocol()`, or `finalize()` methods — architectural absence is the safety mechanism. `_FORBIDDEN_SELECTORS` runtime guard + `_safe_click` enforce the boundary (raises `PermissionError` on any click matching "assinar/enviar processo/protocolar/btnAssinar/etc."). 6 regression tests in `test_sei_writer.py::TestWriterArchitecturalSafety` verify the absence + a static source scan ensures no `.click('text=Assinar')` is ever introduced. **`writer_selectors.py`** lazily loads `sei_selectors.yaml` (captured via `scripts/sei_drive.py`) and re-validates every leaf selector against `_FORBIDDEN_SELECTORS` at load time (belt-and-suspenders). Audit trail: screenshots + DOM dumps + JSONL log per write op in `SEI_WRITE_ARTIFACTS_DIR`. Login automático via credenciais `.env`. `browser.py` keeps only the SEI-specific login form + `is_logged_in` selectors; generic Playwright context/session lifecycle (launch, storage-state load/save) is shared with SIGA via **`ufpr_automation/_session_browser.py`**.
- **`siga/`** — SIGA (Sistema Integrado de Gestão Acadêmica) integration via Playwright. READ-ONLY: checks student status, enrollment, validates internship eligibility. Login goes through **Portal de Sistemas** (Keycloak SSO at `sistemas.ufpr.br`) → role selection ("Coordenação / Secretaria - Graduação") → SIGA home. `browser.py` handles the full SSO flow; `client.py` provides `check_student_status()`, `get_historico()` (IRA, reprovações by type per semester), `get_integralizacao()` (CH summary, discipline status, OD501/ODDA6 tracking), and `validate_internship_eligibility()` (matrícula ativa, >2 reprovações → soft block, currículo integralizado → hard block, graduation timing check). Selectors are grounded from live DOM capture (`scripts/siga_capture_estagios.py`). Vue.js SPA — tab content loads async; `_wait_tab_content()` polls for "Carregando..." spinner to disappear. Generic Playwright context/session lifecycle shared with SEI via `ufpr_automation/_session_browser.py`.
- **`procedures/`** — Two concerns: (1) **`playbook.py`** — the Tier 0 router described above. `Intent` (pydantic) + `Playbook` class (keyword + semantic lookup, lazy `sentence-transformers` load, precomputed embeddings, `is_stale()` vs RAG mtime). `parse_procedures_md()` reads fenced ` ```intent ` / ` ```yaml ` blocks from `workspace/PROCEDURES.md`; `extract_variables()` regex-extracts TCE nº, SEI nº, GRR, dates and sender name; `fill_template()` supports both `[UPPER_CASE]` and `{{ jinja_like }}` placeholders and leaves unknown ones in place for human review. `get_playbook()` is a module-level `lru_cache` singleton. (2) Procedure *logging* for learning — JSONL at `PROCEDURES_DATA_DIR` records steps, duration, outcome, SEI/SIGA consultations.
- **`graph/`** — LangGraph StateGraph orchestrator (Marco II + III). Nodes: perceber (Gmail/OWA) → **tier0_lookup (Hybrid Memory)** → **dispatch_tier1 (Fleet fan-out via `Send` API)** → process_one_email (RAG + classify + SEI/SIGA per-email, parallel) → rotear → registrar_feedback → agir → registrar_procedimento. `state.EmailState.tier0_hits` carries the stable_ids resolved by Tier 0 so the Fleet dispatcher only fans out the residual set. **`fleet.py`** contains `dispatch_tier1`, `process_one_email`, and `SubState`. **`browser_pool.py`** provides `BrowserPagePool` with `asyncio.Semaphore(POOL_SIZE)` for sharing Playwright pages across sub-agents (env: `FLEET_BROWSER_POOL_SIZE`, default 3). State reducers `Annotated[..., _merge_dict]` on `rag_contexts`/`classifications`/`sei_contexts`/`siga_contexts` ensure parallel branches merge instead of last-write-wins. Legacy nodes (`rag_retrieve`, `classificar`, `consultar_sei`, `consultar_siga`) remain in `nodes.py` for the AFlow `baseline` topology variant. **DSPy gate** in `nodes.py` (`_should_use_dspy`, `_compiled_prompt_paths`, `_has_compiled_prompt`) reads `settings.USE_DSPY` to choose between DSPy SelfRefineModule and LiteLLM. SQLite checkpointing for fault tolerance.
- **`dspy_modules/`** — DSPy Signatures and Modules for programmatic prompt optimization. `signatures.py` declares EmailClassifier, DraftCritic, DraftRefiner. `modules.py` composes them into SelfRefineModule. `metrics.py` provides quality metrics. `optimize.py` runs GEPA bootstrap or MIPROv2 optimization.
- **`feedback/`** — Human corrections store (append-only JSONL). Records original vs corrected classifications for DSPy prompt optimization. Storage location is configurable via `FEEDBACK_DATA_DIR` (default local, can point to Google Drive to share state across machines). `reflexion.py` implements Reflexion pattern: auto-analyzes errors, stores in vector store, retrieves past mistakes as negative context. CLI for stats and export. `web.py` provides Streamlit dashboard for reviewing classifications, approving/correcting drafts, and viewing learning statistics.
- **`graphrag/`** — Neo4j GraphRAG knowledge graph (Marco III). `client.py` wraps the Neo4j driver. `schema.py` defines node types (Orgao, Norma, TipoProcesso, Documento, Papel, Sistema, Template, Fluxo, Etapa, Pessoa, Curso, Disciplina, SigaAba) and relationships. `seed.py` populates the graph from institutional knowledge (SOUL.md, SEI/SIGA manuals, ClaudeCowork). After Marco III, `_seed_templates` also persists `Template.conteudo` and `Template.despacho_tipo` (the despacho bodies that used to live hardcoded in `sei/client.py`). `retriever.py` provides graph-aware retrieval: workflow matching, norm lookup, template selection, SIGA navigation hints, org contacts. **`templates.py`** (Marco III) — `TemplateRegistry` class with in-memory cache and `get_registry()` singleton; consumed by `sei/client.py:prepare_despacho_draft` and `sei/writer.py:save_despacho_draft` via lazy import to avoid circular dep. Fallback `campos_pendentes=["neo4j_unavailable"]` if Neo4j offline. Integrated into `process_one_email` (Fleet) alongside vector RAG.

- **`aflow/`** — AFlow topology evaluator (Marco III). NOT a neural search — a hand-authored variant registry + offline evaluator. `topologies.py` registers 5 variants (`baseline`, `fleet`, `skip_rag_high_tier0`, `no_self_refine`, `fleet_no_siga`). `evaluator.py:evaluate()` runs each topology against an eval set with pluggable `metric_fn` and `invoke_fn` (default stub returns expected categoria for unit tests). `optimizer.py:pick_best_topology()` picks by `(accuracy, -latency_mean_ms, -errors)` and writes a JSON report. `cli.py` is the CLI entrypoint. `graph/builder.py:build_graph` dispatches to `aflow.topologies.get_topology(name)` when `AFLOW_TOPOLOGY != "fleet"`, preserving default Fleet behavior. Cold start: if `feedback_data/` is empty, the optimizer falls back to synthetic examples from `dspy_modules/optimize.py`.
- **`scheduler.py`** — APScheduler-based pipeline scheduler. Runs LangGraph pipeline 3x/day (configurable via `SCHEDULE_HOURS`, `SCHEDULE_TZ`). CLI: `--schedule` (daemon) or `--schedule --once`.
- **`workspace/`** — Nanobot integration files: `SOUL.md` (full agent persona + normative detail), **`SOUL_ESSENTIALS.md`** (slim system-prompt slice — identity, tone, categories, signature — injected per LLM call), **`PROCEDURES.md`** (Tier 0 playbook of intents organized by SEI process type), `AGENTS.md`, `SKILL.md`, `config.json`.
- **`ufpr_aberta/`** — Moodle (UFPR Aberta) scraper — login independente (não-SSO), captura o curso "Conheça o SIGA!" (id=9) para authoring de `PROCEDURES.md`, guia de navegação do `siga/browser.py` e ingestão RAG opcional. `browser.py` faz login no Moodle (form nativo) e persiste sessão em `session_data/ufpr_aberta_state.json`. `scraper.py` lida com tema `format_tiles` (visita cada seção via `?section=N`, filtra atividades por `#region-main a.cm-link` — **não** usar `courseindex` sidebar pois lista o curso inteiro). CLI: `python -m ufpr_automation.ufpr_aberta [--headed] [--course-id 9]`. Credenciais em `.env` com nomes literais `LOGING_UFPR_ABERTA`/`SENHA_UFPR_ABERTA` (o "G" a mais é intencional — casa com o arquivo do usuário). Dumps crus vão para `G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\ufpr_aberta\` (HTML + PDFs + `_structure.json`). Markdown estruturado de **BLOCO 1** (alunos, 16 atividades) e **BLOCO 3** (secretarias/coord, 21 atividades) em `base_conhecimento/ufpr_aberta/`: `bloco_alunos.md`, `bloco_siga_secretarias.md`, `FLUXO_GERAL.md` (Mermaid cross-bloco).
- **`base_conhecimento/`** — Operational reference files used to author the playbook and train prompts: `manual_sei.txt`, `manual_siga.txt`, **`NAVEGACAO_SIGA.md`** (guia de navegação Playwright SIGA — consultar para tarefas de navegação), **`NAVEGACAO_SEI.md`** (guia de navegação Playwright SEI — consultar para tarefas de navegação), `FichaDoCurso.txt`, `procedimentos.md`, `ufpr_aberta/*.md` (ver acima), and **`SEI-tutotiais/`** — 60 POPs oficiais do SEI UFPR (POP-1 a POP-58 + PVA + Novidades 4.0 + organograma). A triagem A/B/C (relevância para Tier 0 atual vs. expansão vs. futuro) está em `SEI-tutotiais/README.md`. **Visão de longo prazo**: além de enriquecer o Tier 0 atual (Estágios), os POPs servem de base de conhecimento para um futuro **agente chat-driven full-SEI** — operações SEI sob demanda via chat ("abre processo X", "anexa Y", "encaminha para Z"). **Política atual (Marco IV)**: `_FORBIDDEN_SELECTORS` bloqueia assinar/protocolar/enviar processo; POPs desses fluxos (POP-22, POP-32, POP-54) são ingeridos no RAG com metadata `write_forbidden=true` para que o agente os **explique** mas não execute. **Marco futuro**: a execução desses fluxos está planejada — o boundary existe para blindar alucinações de LLM e para human-in-the-loop durante a maturação, não como veto permanente. Guia visual rápido do fluxo TCE (referência de apoio, não normativa): `G:\Meu Drive\ufpr_rag\docs\estagio\manual-de-estagios-versao-final.pdf` pgs impressas 81–83. **Regra `tipo_conferencia`**: `Nato Digital` quando a origem do doc é digital; `Cópia Autenticada Administrativamente` quando foi escaneado (dependeu de OCR). Estes arquivos são plain-text/PDF, não embedados no RAG por padrão — drive de authoring humano de `PROCEDURES.md`; subset `sei_pop` do RAG é opt-in via `rag/ingest.py --subset sei_pop`. **Staging de documentos crus pendentes de ingestão**: `G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\` — fonte de verdade do backlog de docs (PDFs, HTMLs, dumps UFPR Aberta, POPs novos, resoluções, etc.) que ainda não passaram pelo pipeline `rag/ingest.py`. Sempre consultar esse diretório antes de concluir que um doc "não existe na base" — ele pode estar apenas não-ingerido. Quando um doc for ingerido, mover de `ainda_n_ingeridos/` para a subpasta definitiva em `G:\Meu Drive\ufpr_rag\docs\` correspondente ao subset.
- **`ClaudeCowork/`** — Base de conhecimento from Claude Cowork: SEI manual, SIGA manual, course data, internship guides, email templates, scheduled skills (morning/afternoon email checks).

- **`base_conhecimento/NAVEGACAO_SIGA.md`** — **Guia de navegação SIGA**. Referência completa para navegação Playwright: login via Portal de Sistemas (Keycloak SSO), mapa de menus sidebar, 19 abas do perfil do discente com pane_ids e seletores, estrutura DOM do Histórico (IRA, reprovações) e Integralização (CH summary, OD501/ODDA6), fluxo de verificação de estágios. **Consultar este arquivo sempre que a tarefa envolver navegação no SIGA.**
- **`base_conhecimento/NAVEGACAO_SEI.md`** — **Guia de navegação SEI**. Referência completa: login direto, estrutura de framesets, formulários (Iniciar Processo, Incluir Documento Externo, Despacho) com seletores, operações do SEIWriter, tipos de processo mais comuns, fluxo de estágios no SEI, audit trail. **Consultar este arquivo sempre que a tarefa envolver navegação no SEI.**

The automation saves responses as drafts — never auto-sends (human-in-the-loop). See `ufpr_automation/ARCHITECTURE.md` for the planned 3-phase maturation roadmap (Marco I -> LangGraph -> GraphRAG/multi-agent).

## Configuration

- **`pyproject.toml`** — Package metadata, dependencies, Ruff config (line-length=100, target py311). Build backend: hatchling.
- **`.env`** (in `ufpr_automation/`) — Centralized credentials: Gmail (IMAP), OWA, SIGA, SEI, Telegram, LLM API keys. See `.env.example`.
- **`docker-compose.yml`** — Two services: `nanobot-gateway` (port 18790, 1 CPU) and `nanobot-cli`.
- **`nanobot/templates/`** — Default config templates copied during `nanobot onboard`.

## Sincronização entre PCs (RAG + Neo4j) — LEIA ANTES DE TOCAR EM RAG/NEO4J

> Este projeto roda em **2 PCs** (Lucas — casa + trabalho). Cada PC tem o RAG store e o Neo4j **localmente**; `G:/Meu Drive/ufpr_rag/store/` (Google Drive) é apenas o **canal de sincronização** entre eles, não o path operacional. `RAG_STORE_DIR` no `.env` deve apontar pra um diretório local — o que está no `.env` neste momento pode estar stale (copiado do outro PC).

### Verificação automática de drift (3 camadas)

1. **`SessionStart` hook do Claude Code** ([.claude/settings.json](.claude/settings.json)): toda vez que você abre uma sessão Claude Code neste projeto, `scripts/check_drive_status.ps1` roda e o output entra no contexto da conversa. Se o status for `STALE` (G: mais novo que local), Claude **vai te avisar** antes de sugerir qualquer operação em RAG/Neo4j.
2. **Pre-flight do pipeline** ([scheduler.py:_check_drive_freshness](ufpr_automation/scheduler.py)): toda execução agendada (08h/13h/17h) chama o check antes de processar emails. Se `STALE`, loga WARNING em `logs/scheduler.log` e segue (não aborta — perder triggers seria pior que processar com RAG levemente defasado).
3. **Manual a qualquer momento**: `powershell -ExecutionPolicy Bypass -File scripts\check_drive_status.ps1` — saída humano-legível com counts dos 2 lados e prescrição de ação.

Status possíveis (exit codes do `check_drive_freshness.py`): `SYNCED` (0), `STALE` (1), `AHEAD` (2), `NO_REMOTE` (3), `NO_LOCAL` (4), `CONFLICT` (5), `ERROR` (6).

### Scripts prontos (preferir aos comandos manuais)

```powershell
# Antes de começar trabalho — puxa G: → local + re-seeda Neo4j + compara manifest:
powershell -ExecutionPolicy Bypass -File scripts\sync_from_drive.ps1

# Depois de re-ingest / seed --clear / enrich / qualquer modificação — empurra local → G: + atualiza manifest:
powershell -ExecutionPolicy Bypass -File scripts\sync_to_drive.ps1
```

`sync_from_drive.ps1` faz: `robocopy /MIR G:→local` → `seed --clear` → `enrich` → gera `MANIFEST.json` local → compara contadores (chunks LanceDB, nós/rels Neo4j) com `G:/MANIFEST.json` e imprime `OK`/`DIFF` por linha. `sync_to_drive.ps1` faz o caminho inverso e atualiza ambos os manifests. Ambos leem `RAG_STORE_DIR` do `.env` local — não hardcoded.

**Manifest schema** (`G:\Meu Drive\ufpr_rag\store\MANIFEST.json`): `{schema_version, timestamp, machine, git_sha, lancedb: {total_chunks, store_size_mb, tables}, neo4j: {total_nodes, total_relationships, nodes_by_label, rels_by_type, normas_with_emissor}}`. Comparação é estrita em `total_chunks`/`total_nodes`/`total_relationships` — drift em qualquer um sinaliza re-seed pulado, edição manual no Neo4j Browser, ou dois PCs ingerindo em paralelo.

### Comandos brutos (fallback)

```bash
# G: → local
robocopy "G:\Meu Drive\ufpr_rag\store\ufpr.lance" "<RAG_STORE_DIR>\ufpr.lance" /MIR /COPY:DAT /R:3 /W:5
.venv/Scripts/python.exe -m ufpr_automation.graphrag.seed --clear

# local → G:
robocopy "<RAG_STORE_DIR>\ufpr.lance" "G:\Meu Drive\ufpr_rag\store\ufpr.lance" /MIR /COPY:DAT /R:3 /W:5
```

Não copie o binário do Neo4j — o outro PC re-seeda localmente do RAG sincronizado (mais simples e mais robusto que copiar o data dir do Neo4j Desktop).

**`RAG_DOCS_DIR`, `FEEDBACK_DATA_DIR`, `PROCEDURES_DATA_DIR`** ficam em `G:/Meu Drive/ufpr_rag/…` (compartilhamento nativo), não precisam de sync manual.

## Windows notes

- **RAG ingest — não rodar `ingest.py` apontando direto para G:**. LanceDB faz commit atômico renomeando `_versions/*.manifest`, e o Google Drive Desktop retorna `Função incorreta (os error 1)` nessa operação, abortando o ingest depois que todos os chunks já foram embedados. Fluxo correto validado em 2026-04-20: rodar ingest com `RAG_STORE_DIR=<path local>` e, ao terminar, espelhar local → G: com `robocopy "<local>\ufpr.lance" "G:\...\store\ufpr.lance" /E /COPY:DAT /R:3 /W:5` (bash MSYS: prefixar `MSYS_NO_PATHCONV=1` para não quebrar flags com `/`). Robocopy lida com Drive sync; LanceDB não. Ver seção "Sincronização entre PCs" acima.
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
