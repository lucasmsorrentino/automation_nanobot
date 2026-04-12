# TASKS — Roadmap

> Para o histórico completo de tarefas executadas (Marcos I/II/II.5/III), consulte `git log` ou versões anteriores deste arquivo.

## Status atual

| Marco | Status | Resumo |
|---|---|---|
| **Marco I** — Protótipo | ✅ | Pipeline Perceber→Pensar→Agir, OWA Playwright + Gmail IMAP, auto-login MFA, anexos (PDF/DOCX/XLSX), salva como rascunho |
| **Marco II** — Roteamento Agêntico | ✅ | LangGraph StateGraph, RAG (LanceDB + RAPTOR), Self-Refine, DSPy (gate `USE_DSPY` tri-state), Reflexion, Locator chain, Model cascading |
| **Marco II.5** — SEI/SIGA + Scheduler | ✅ | Módulos SEI/SIGA (read-only, Playwright), pipeline expandido, ProcedureStore, scheduler (3x/dia), Streamlit feedback UI |
| **Marco III** — Cognição Relacional | ✅ | GraphRAG/Neo4j (1.757 nós, 2.296 rels), **LangGraph Fleet** (sub-agentes paralelos via `Send` API + reducers), **AFlow** (5 topologias hand-authored + evaluator), **SEIWriter** (attach + draft only, sem sign/send/protocol), **TemplateRegistry** (despachos via Neo4j) |
| **Marco IV — em andamento** | 🟡 | Estágios end-to-end: `Intent` estendido (`sei_action`, `required_attachments`, `blocking_checks`, `despacho_template`), `SEI_DOC_CATALOG.yaml`, 11 checkers registrados, `SEIWriter.create_process` skeleton + dry-run em todas as 3 ops, extração de vars do TCE anexado. **Bloqueado em:** captura de seletores Playwright para flipar `SEI_WRITE_MODE=live`. |

**Testes:** 490 passando, 0 falhas (`pytest ufpr_automation/tests/ -v`) — lazy-import Playwright, cascade mock fix, datetime.utcnow() fix
**RAG:** 34.285 chunks (3.288/3.316 PDFs, 99,2% via PyMuPDF + OCR Tesseract)

## Pendente

### 🔴 PRIORIDADE — Marco IV: Estágios end-to-end (próxima sessão)

Fluxo objetivo: receber TCE → criar processo SEI → anexar TCE → lavrar Despacho → rascunhar email de acuse. Infraestrutura lógica pronta (modelo `Intent` estendido, `SEI_DOC_CATALOG.yaml`, checker registry com 11 checks, `SEIWriter` com dry-run), falta o fluxo Playwright ao vivo e o wire-up no graph.

**▶ SDD detalhado:** [`SDD_SEI_SELECTOR_CAPTURE.md`](SDD_SEI_SELECTOR_CAPTURE.md) — especificação completa pra rodar a sprint de captura via Claude Code (plano Max, sem API key).

- [x] **Smoke test `SEIWriter` dry-run end-to-end** — `test_sei_writer.py::TestSEIWriterDryRunEndToEnd` exercita `create_process` → `attach_document` → `save_despacho_draft` em dry-run, valida JSONL de audit (3 records em ordem, mode=dry_run).
- [ ] **Captura de seletores Playwright em sessão SEI ao vivo** (BLOQUEANTE para live mode):
  - [ ] **Sprint 1 — Captura** (ver SDD §6): rodar Claude Code dirigindo Playwright headed contra SEI de teste, gerar `procedures_data/sei_capture/<ts>/sei_selectors.yaml` no schema da SDD §5
  - [ ] **Sprint 2 — Wire-up** (ver SDD §7): criar `sei/writer_selectors.py`, substituir os 3 `NotImplementedError` em `sei/writer.py` usando o YAML capturado
  - [ ] **Sprint 3 — Validação** (ver SDD §8): smoke dry_run + smoke live em SEI de teste com processo fictício
  - [ ] Flipar `SEI_WRITE_MODE=live` em produção depois das 3 sprints validadas
- [x] **`get_doc_classification(label)` loader** — `procedures/doc_catalog.py` com `lru_cache`, case-insensitive lookup, `list_labels()`, `reload_catalog()`. 8 testes em `test_doc_catalog.py`.
- [ ] **`agir_estagios` node** novo em `graph/nodes.py`:
  - [ ] Input: email classificado como `Estágios` + intent com `sei_action != "none"`
  - [ ] Roda `completeness_check` do `procedures/checkers.py`
  - [ ] Se hard_blocks → rascunho de email com a lista de bloqueadores (sem tocar no SEI)
  - [ ] Se soft_blocks → rascunho de email pedindo justificativa formal (sem tocar no SEI)
  - [ ] Se pass → `SEIWriter.create_process` (se `sei_action == "create_process"`) → `attach_document(s)` → `save_despacho_draft(body_override=intent.despacho_template)` → rascunho de email de acuse com `NUMERO_PROCESSO_SEI`
- [ ] **Wire `agir_estagios` no `graph/builder.py`** — rotear Estágios por `agir_estagios` em vez de `agir_gmail` quando o intent do Tier 0 tem `sei_action != "none"`
- [x] **Intent model smoke test** — `test_playbook.py::test_intent_extended_fields_default_empty`, `test_intent_extended_fields_parse_from_yaml`, `test_intent_sei_action_rejects_invalid_literal`
- [x] **Test suite dos 11 checkers** — `test_checkers.py` com 42 testes cobrindo happy + unhappy path, `CheckSummary` aggregation, human-readable output
- [ ] **Atualizar `SOUL.md §8.1` e `§11`** com as correções da sessão: "2 dias úteis" ao invés de "10 dias" de antecedência; "> 1 reprovação exige justificativa formal" ao invés de "> 50%"; nova regra "jornada antes do meio-dia exige integralização prévia"

### Validação manual em produção
- [ ] Validar login automático no SEI com sessão ativa e credenciais reais
- [ ] Validar login automático no SIGA com sessão ativa e credenciais reais
- [ ] Refinar seletores Playwright SEI/SIGA após inspeção do DOM real
- [ ] Rodar scheduler 1 dia completo em produção
- [ ] Coletar feedback via Streamlit e verificar ReflexionMemory
- [ ] Re-seed Neo4j para refletir Coordenadora correta (Stephania) + templates: `python -m ufpr_automation.graphrag.seed --clear`
- [ ] Smoke do Fleet em batch real: `AFLOW_TOPOLOGY=fleet python -m ufpr_automation --channel gmail --langgraph --limit 10`

### Marco III — refinamentos pendentes
- [ ] **`BrowserPagePool` wire-up**: pool de Playwright pages criado em `graph/browser_pool.py` mas `_consult_sei_for_email`/`_consult_siga_for_email` ainda spawnam browser próprio. Refator para reaproveitar pages do pool.
- [ ] **AFlow ablations reais**: `topology_skip_rag_high_tier0`, `topology_no_self_refine`, `topology_fleet_no_siga` estão registradas como aliases de baseline/fleet no MVP. Implementar a lógica real de cada ablation para permitir comparações de latência/custo.
- [ ] **Ollama/Qwen3-8B**: cascade pronto em `llm/router.py`, falta deploy operacional do modelo local.
- [x] **3 testes flaky LiteLLM** — corrigido: mocks agora patcham `cascaded_completion` / `cascaded_completion_sync` no namespace do client (antes patchavam `litellm` que o router reimportava internamente). Todos offline, <1s.

### Marco V — Automações via Claude Code CLI (plano Max, sem API)

▶ **SDD detalhado:** [`SDD_CLAUDE_CODE_AUTOMATIONS.md`](SDD_CLAUDE_CODE_AUTOMATIONS.md) — 6 specs + roadmap em 7 fases + padrão arquitetural reutilizável + anti-patterns

Conjunto de automações que rodam o `claude` CLI como subprocess sob plano Max (custo zero adicional). Estrita separação do path crítico online (LangGraph + LiteLLM continua intacto). Ordem de adoção:

- [ ] **Fase 1 — Infra compartilhada** (`agent_sdk/runner.py` + skills + audit) — bloqueia tudo abaixo
- [ ] **Fase 2 — Intent Drafter** (Marco IV.2 do plano antigo, agora consolidado aqui) — auto-aprendizado do Tier 0 playbook
- [ ] **Fase 3 — Feedback Review Chat** — adiciona via conversacional **ao lado** do Streamlit (Streamlit continua como fallback obrigatório quando claude/Anthropic indisponível ou pra batch triage visual; ver SDD §4.7-4.8)
- [ ] **Fase 4 — Classification Debugger** — diagnóstico interativo de classificações erradas via stable_id
- [ ] **Fase 5 — RAG Quality Auditor** — monitora drift do RAG mensalmente contra ground truth curado
- [ ] **Fase 6 — PROCEDURES Staleness Checker** — detecta intents desalinhados com SOUL.md/Neo4j
- [ ] **Fase 7 — Maintainer Tool polish** — slash commands + skills curados pra DX

### Out of scope (decisão alinhada com a coordenação)
- ❌ **SIGA write ops** — permanece read-only por design.
- ❌ **SEI sign/send/protocol** — proibido arquiteturalmente. `SEIWriter` não expõe esses métodos; 6 testes regressivos garantem que nenhum `sign()`/`enviar()`/`protocolar()` apareça na classe.
