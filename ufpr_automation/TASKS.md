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

**Testes:** 429 passando (`pytest ufpr_automation/tests/ -v`)
**RAG:** 34.285 chunks (3.288/3.316 PDFs, 99,2% via PyMuPDF + OCR Tesseract)

## Pendente

### 🔴 PRIORIDADE — Marco IV: Estágios end-to-end (próxima sessão)

Fluxo objetivo: receber TCE → criar processo SEI → anexar TCE → lavrar Despacho → rascunhar email de acuse. Infraestrutura lógica pronta (modelo `Intent` estendido, `SEI_DOC_CATALOG.yaml`, checker registry com 11 checks, `SEIWriter` com dry-run), falta o fluxo Playwright ao vivo e o wire-up no graph.

**▶ SDD detalhado:** [`SDD_SEI_SELECTOR_CAPTURE.md`](SDD_SEI_SELECTOR_CAPTURE.md) — especificação completa pra rodar a sprint de captura via Claude Code (plano Max, sem API key).

- [ ] **Smoke test `SEIWriter` dry-run end-to-end** — criar teste que exercita `create_process` → `attach_document` → `save_despacho_draft` em modo dry-run com page mockada e valida o JSONL de audit. (Ficou pendente da sessão anterior por interrupção de tool, mas a implementação já compila.)
- [ ] **Captura de seletores Playwright em sessão SEI ao vivo** (BLOQUEANTE para live mode):
  - [ ] **Sprint 1 — Captura** (ver SDD §6): rodar Claude Code dirigindo Playwright headed contra SEI de teste, gerar `procedures_data/sei_capture/<ts>/sei_selectors.yaml` no schema da SDD §5
  - [ ] **Sprint 2 — Wire-up** (ver SDD §7): criar `sei/writer_selectors.py`, substituir os 3 `NotImplementedError` em `sei/writer.py` usando o YAML capturado
  - [ ] **Sprint 3 — Validação** (ver SDD §8): smoke dry_run + smoke live em SEI de teste com processo fictício
  - [ ] Flipar `SEI_WRITE_MODE=live` em produção depois das 3 sprints validadas
- [ ] **`get_doc_classification(label)` loader** para `workspace/SEI_DOC_CATALOG.yaml` em `procedures/doc_catalog.py` (novo módulo, lazy-cached como o Playbook)
- [ ] **`agir_estagios` node** novo em `graph/nodes.py`:
  - [ ] Input: email classificado como `Estágios` + intent com `sei_action != "none"`
  - [ ] Roda `completeness_check` do `procedures/checkers.py`
  - [ ] Se hard_blocks → rascunho de email com a lista de bloqueadores (sem tocar no SEI)
  - [ ] Se soft_blocks → rascunho de email pedindo justificativa formal (sem tocar no SEI)
  - [ ] Se pass → `SEIWriter.create_process` (se `sei_action == "create_process"`) → `attach_document(s)` → `save_despacho_draft(body_override=intent.despacho_template)` → rascunho de email de acuse com `NUMERO_PROCESSO_SEI`
- [ ] **Wire `agir_estagios` no `graph/builder.py`** — rotear Estágios por `agir_estagios` em vez de `agir_gmail` quando o intent do Tier 0 tem `sei_action != "none"`
- [ ] **Intent model smoke test** — `test_playbook.py::test_intent_extended_fields` verificando que os 5 campos novos (`sei_action`, `sei_process_type`, `required_attachments`, `blocking_checks`, `despacho_template`) parseiam do YAML
- [ ] **Test suite dos 11 checkers** — `test_checkers.py` novo cobrindo cada checker com contexto feliz + unhappy path
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
- [ ] **3 testes flaky LiteLLM** (`test_classify_email_*`, `test_partial_failure`) — pré-existentes, dependem de network ao MiniMax. Mockar com `responses` ou `litellm.testing` ao invés de chamar a API real.

### Marco IV — Playbook self-learning (backlog, pós-Estágios)
Loop de promoção Tier 1 → Tier 0 auto-gerado (discussão da sessão 2026-04-10). Requisitos e plano em 4 fases (IV.1 hotpath analyzer, IV.2 intent drafter com RAG, IV.3 gate de revisão humana, IV.4 métrica de regressão pós-promoção) documentados na thread. Depende de volume mínimo de `procedures_data/` acumulado em produção.

### Out of scope (decisão alinhada com a coordenação)
- ❌ **SIGA write ops** — permanece read-only por design.
- ❌ **SEI sign/send/protocol** — proibido arquiteturalmente. `SEIWriter` não expõe esses métodos; 6 testes regressivos garantem que nenhum `sign()`/`enviar()`/`protocolar()` apareça na classe.
