# TASKS — Roadmap

> Para o histórico completo de tarefas executadas (Marcos I/II/II.5/III), consulte `git log` ou versões anteriores deste arquivo.

## Status atual

| Marco | Status | Resumo |
|---|---|---|
| **Marco I** — Protótipo | ✅ | Pipeline Perceber→Pensar→Agir, OWA Playwright + Gmail IMAP, auto-login MFA, anexos (PDF/DOCX/XLSX), salva como rascunho |
| **Marco II** — Roteamento Agêntico | ✅ | LangGraph StateGraph, RAG (LanceDB + RAPTOR), Self-Refine, DSPy (gate `USE_DSPY` tri-state), Reflexion, Locator chain, Model cascading |
| **Marco II.5** — SEI/SIGA + Scheduler | ✅ | Módulos SEI/SIGA (read-only, Playwright), pipeline expandido, ProcedureStore, scheduler (3x/dia), Streamlit feedback UI |
| **Marco III** — Cognição Relacional | ✅ | GraphRAG/Neo4j (1.757 nós, 2.296 rels), **LangGraph Fleet** (sub-agentes paralelos via `Send` API + reducers), **AFlow** (5 topologias hand-authored + evaluator), **SEIWriter** (attach + draft only, sem sign/send/protocol), **TemplateRegistry** (despachos via Neo4j) |
| **Marco IV — em andamento** | 🟡 | Estágios end-to-end: `Intent` estendido (`sei_action`, `required_attachments`, `blocking_checks`, `despacho_template`), `SEI_DOC_CATALOG.yaml`, 11 checkers registrados, `SEIWriter` com **live mode wired up** (`create_process`/`attach_document`/`save_despacho_draft` via `sei/writer_selectors.py` + `sei_selectors.yaml`), scripts de captura (`scripts/sei_drive.py`) e smokes live (`scripts/smoke_create_process_live.py`, `scripts/smoke_writer_live_e2e.py`). **Restante:** rodar smoke live em SEI de teste para validar (Sprint 3) antes de flipar `SEI_WRITE_MODE=live` em produção. |

**Testes:** 625 passando, 0 falhas (`pytest ufpr_automation/tests/ -v`)
**RAG:** 34.285 chunks (3.288/3.316 PDFs, 99,2% via PyMuPDF + OCR Tesseract)

## Pendente

### 🔴 PRIORIDADE — Marco IV: Estágios end-to-end (próxima sessão)

Fluxo objetivo: receber TCE → criar processo SEI → anexar TCE → lavrar Despacho → rascunhar email de acuse. Infraestrutura lógica pronta (modelo `Intent` estendido, `SEI_DOC_CATALOG.yaml`, checker registry com 11 checks, `SEIWriter` com dry-run), falta o fluxo Playwright ao vivo e o wire-up no graph.

**▶ SDD detalhado:** [`SDD_SEI_SELECTOR_CAPTURE.md`](SDD_SEI_SELECTOR_CAPTURE.md) — especificação completa pra rodar a sprint de captura via Claude Code (plano Max, sem API key).

- [x] **Smoke test `SEIWriter` dry-run end-to-end** — `test_sei_writer.py::TestSEIWriterDryRunEndToEnd` exercita `create_process` → `attach_document` → `save_despacho_draft` em dry-run, valida JSONL de audit (3 records em ordem, mode=dry_run).
- [x] **Captura de seletores Playwright em sessão SEI ao vivo** (Sprints 1+2 concluídas):
  - [x] **Sprint 1 — Captura** (ver SDD §6): `scripts/sei_drive.py` (driver não-interativo) + manifesto gerado em `procedures_data/sei_capture/20260413_192020/sei_selectors.yaml` (schema SDD §5)
  - [x] **Sprint 2 — Wire-up** (ver SDD §7): `sei/writer_selectors.py` carrega + valida o YAML (fails fast se selector colide com `_FORBIDDEN_SELECTORS`); os 3 `NotImplementedError` em `sei/writer.py` substituídos por fluxos Playwright completos (`create_process`, `attach_document`, `save_despacho_draft`)
  - [ ] **Sprint 3 — Validação** (ver SDD §8): rodar `scripts/smoke_writer_live_e2e.py` em SEI de teste com processo fictício (dummy_tce.pdf) para validar o fluxo end-to-end
  - [ ] Flipar `SEI_WRITE_MODE=live` em produção depois do Sprint 3 validado
- [x] **`get_doc_classification(label)` loader** — `procedures/doc_catalog.py` com `lru_cache`, case-insensitive lookup, `list_labels()`, `reload_catalog()`. 8 testes em `test_doc_catalog.py`.
- [x] **`agir_estagios` node** em `graph/nodes.py` + wired em `builder.py`:
  - [x] Input: email classificado como `Estágios` + intent com `sei_action != "none"`
  - [x] Roda `run_checks` do `procedures/checkers.py`
  - [x] Se hard_blocks → rascunho de email com a lista de bloqueadores (sem tocar no SEI)
  - [x] Se soft_blocks → rascunho de email pedindo justificativa formal (sem tocar no SEI)
  - [x] Se pass → `SEIWriter.create_process` → `attach_document(s)` → `save_despacho_draft(body_override=intent.despacho_template)` → acuse com `NUMERO_PROCESSO_SEI`
  - [x] 4 testes em `test_agir_estagios.py`
- [x] **Intent model smoke test** — `test_playbook.py::test_intent_extended_fields_default_empty`, `test_intent_extended_fields_parse_from_yaml`, `test_intent_sei_action_rejects_invalid_literal`
- [x] **Test suite dos 11 checkers** — `test_checkers.py` com 42 testes cobrindo happy + unhappy path, `CheckSummary` aggregation, human-readable output
- [x] **Atualizar `SOUL.md §8.1` e `§11`** — "2 dias úteis" (era "10 dias"), "> 1 reprovação → justificativa formal" (era "> 50%"), regra "jornada antes do meio-dia exige integralização prévia"

### Validação manual em produção
- [ ] Validar login automático no SEI com sessão ativa e credenciais reais
- [ ] Validar login automático no SIGA com sessão ativa e credenciais reais
- [ ] Refinar seletores Playwright SEI/SIGA após inspeção do DOM real
- [ ] Rodar scheduler 1 dia completo em produção
- [ ] Coletar feedback via Streamlit e verificar ReflexionMemory
- [ ] Re-seed Neo4j para refletir Coordenadora correta (Stephania) + templates: `python -m ufpr_automation.graphrag.seed --clear`
- [ ] Smoke do Fleet em batch real: `AFLOW_TOPOLOGY=fleet python -m ufpr_automation --channel gmail --langgraph --limit 10`

### Marco III — refinamentos pendentes
- [~] **`BrowserPagePool` wire-up** — **reavaliado, parked**. O pool em `graph/browser_pool.py` foi desenhado para um mundo async (compartilha `BrowserContext` entre sub-agentes via `asyncio.Semaphore`), mas `process_one_email` do Fleet é sync — LangGraph dispara os sub-agentes em thread pool, cada um com seu próprio event loop, e `BrowserContext` do Playwright é bound ao loop que o criou. Auditoria revelou que o custo real é menor do que parecia: `sei/browser.py` e `siga/browser.py` já reusam `storage_state` via `create_browser_context`/`save_session_state`, então em steady-state (sessão válida no disco) o Fleet com N Estágios faz 2N spawns de Chromium mas **0 logins**. Dor restante: (a) race no primeiro login do dia (N sub-agentes tentando `auto_login` em paralelo quando a session file está ausente/expirada), (b) overhead de spawn de Chromium. Refactor correto pra usar o pool exige tornar todo o Fleet async (cascata em `_classify_*`, retriever, graph context, reflexion) — custo alto, benefício marginal. Melhor alternativa: pre-warm node sync antes do dispatch que faz 1 login quando session está stale. Item abaixo cobre isso.
- [ ] **Pre-warm SEI/SIGA sessions antes do Fleet dispatch** (opcional, endereça race do primeiro login): node `prewarm_sessions` entre `perceber` e `tier0_lookup` — regex-scan dos emails por padrão SEI/GRR; se casar e session file ausente/≥6h, faz 1 login sync. Ativar só se medição em produção mostrar que o race do login é dor real.
- [x] **AFlow ablations reais (todas as 3)**: `no_self_refine` (skips `self_refine_async`), `fleet_no_siga` (skips SIGA consult), `skip_rag_high_tier0` (agora real — `Playbook.best_semantic_score()` + `tier0_lookup` emite `tier0_near_miss_scores` no state; `rag_retrieve` skipa emails com score > `SKIP_RAG_NEAR_MISS_THRESHOLD` (default 0.80)). 4 testes de ablation + 1 teste de near-miss emission.
- [ ] **Ollama/Qwen3-8B**: cascade pronto em `llm/router.py`, falta deploy operacional do modelo local.
- [x] **3 testes flaky LiteLLM** — corrigido: mocks agora patcham `cascaded_completion` / `cascaded_completion_sync` no namespace do client (antes patchavam `litellm` que o router reimportava internamente). Todos offline, <1s.

### Marco V — Automações via Claude Code CLI (plano Max, sem API)

▶ **SDD detalhado:** [`SDD_CLAUDE_CODE_AUTOMATIONS.md`](SDD_CLAUDE_CODE_AUTOMATIONS.md) — 6 specs + roadmap em 7 fases + padrão arquitetural reutilizável + anti-patterns

Conjunto de automações que rodam o `claude` CLI como subprocess sob plano Max (custo zero adicional). Estrita separação do path crítico online (LangGraph + LiteLLM continua intacto). Ordem de adoção:

- [x] **Fase 1 — Infra compartilhada** — `agent_sdk/runner.py` (`run_claude_oneshot`, `is_claude_available`, `ClaudeRunResult`, audit JSONL), 15 testes em `test_agent_sdk_runner.py`
- [x] **Fase 2 — Intent Drafter** (Marco IV.2 do plano antigo, agora consolidado aqui) — `agent_sdk/intent_drafter.py` (clustering + Claude CLI invocation + YAML validation + idempotency), `skills/intent_drafter.md` briefing, 21 testes em `test_intent_drafter.py`
- [x] **Fase 3 — Feedback Review Chat** — `agent_sdk/feedback_chat.py` (prepare_session lê `last_run.jsonl`, summariza por categoria/ação/confiança, escreve bootstrap+meta+summary em session dir, `launch_claude` com fallback gracioso se CLI indisponível), `skills/feedback_chat_bootstrap.md` briefing, **test regressivo garante `feedback/web.py` não importa `agent_sdk/`** (Streamlit continua standalone). 14 testes em `test_feedback_chat.py`.
- [x] **Fase 4 — Classification Debugger** — `agent_sdk/debug_classification.py` (Tier 0 replay, procedure log trace, feedback lookup, fix proposals), CLI `--stable-id` + `--last N`, Markdown reports, 14 testes em `test_debug_classification.py`
- [x] **Fase 5 — RAG Quality Auditor** — `agent_sdk/rag_auditor.py` (ground truth YAML loader, per-query recall/latency, per-subset aggregation, baseline diff + hard thresholds), seed `eval_sets/rag_ground_truth.yaml` (8 queries, expand to 20-30), atomic baseline update só em sucesso, 17 testes em `test_rag_auditor.py`
- [x] **Fase 6 — PROCEDURES Staleness Checker** — `agent_sdk/procedures_staleness.py` (checks blocking_checks registration, SOUL.md §X references, last_update age, SEI action consistency), Markdown report output, 19 testes em `test_procedures_staleness.py`
- [x] **Fase 7 — Maintainer Tool polish** — `agent_sdk/skills/maintainer.md` (comandos comuns + anti-padrões), 5 slash commands em `.claude/commands/` (`/run-pipeline-once`, `/feedback-stats`, `/check-tier0`, `/test-suite`, `/rag-query`), `.claude/settings.json` com allow/deny pre-aprovado (read-only seguro), 26 testes regressivos em `test_maintainer_polish.py`

### Out of scope (decisão alinhada com a coordenação)
- ❌ **SIGA write ops** — permanece read-only por design.
- ❌ **SEI sign/send/protocol** — proibido arquiteturalmente. `SEIWriter` não expõe esses métodos; 6 testes regressivos garantem que nenhum `sign()`/`enviar()`/`protocolar()` apareça na classe.
