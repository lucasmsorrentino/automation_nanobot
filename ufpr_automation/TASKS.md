# TASKS — Roadmap

> Para o histórico completo de tarefas executadas (Marcos I/II/II.5/III), consulte `git log` ou versões anteriores deste arquivo.

## Status atual

| Marco | Status | Resumo |
|---|---|---|
| **Marco I** — Protótipo | ✅ | Pipeline Perceber→Pensar→Agir, OWA Playwright + Gmail IMAP, auto-login MFA, anexos (PDF/DOCX/XLSX), salva como rascunho |
| **Marco II** — Roteamento Agêntico | ✅ | LangGraph StateGraph, RAG (LanceDB + RAPTOR), Self-Refine, DSPy (gate `USE_DSPY` tri-state), Reflexion, Locator chain, Model cascading |
| **Marco II.5** — SEI/SIGA + Scheduler | ✅ | Módulos SEI/SIGA (read-only, Playwright), pipeline expandido, ProcedureStore, scheduler (3x/dia), Streamlit feedback UI |
| **Marco III** — Cognição Relacional | ✅ | GraphRAG/Neo4j (1.757 nós, 2.296 rels), **LangGraph Fleet** (sub-agentes paralelos via `Send` API + reducers), **AFlow** (5 topologias hand-authored + evaluator), **SEIWriter** (attach + draft only, sem sign/send/protocol), **TemplateRegistry** (despachos via Neo4j) |

**Testes:** 429 passando (`pytest ufpr_automation/tests/ -v`)
**RAG:** 34.285 chunks (3.288/3.316 PDFs, 99,2% via PyMuPDF + OCR Tesseract)

## Pendente

### Validação manual em produção
- [ ] Validar login automático no SEI com sessão ativa e credenciais reais
- [ ] Validar login automático no SIGA com sessão ativa e credenciais reais
- [ ] Refinar seletores Playwright SEI/SIGA após inspeção do DOM real
- [ ] Rodar scheduler 1 dia completo em produção
- [ ] Coletar feedback via Streamlit e verificar ReflexionMemory
- [ ] Compilar prompts DSPy: `python -m ufpr_automation.dspy_modules.optimize --strategy gepa` (gera `dspy_modules/optimized/gepa_optimized.json`, ativa `USE_DSPY=auto`)
- [ ] Re-seed Neo4j para popular `Template.conteudo`: `python -m ufpr_automation.graphrag.seed`
- [ ] Smoke do Fleet em batch real: `AFLOW_TOPOLOGY=fleet python -m ufpr_automation --channel gmail --limit 10`
- [ ] Validar `SEIWriter.attach_document` em staging do SEI (selectors precisam ser refinados após inspeção do DOM real — skeleton com guards arquitetural já está pronto)

### Marco III — refinamentos pendentes
- [ ] **`BrowserPagePool` wire-up**: pool de Playwright pages criado em `graph/browser_pool.py` mas `_consult_sei_for_email`/`_consult_siga_for_email` ainda spawnam browser próprio. Refator para reaproveitar pages do pool.
- [ ] **AFlow ablations reais**: `topology_skip_rag_high_tier0`, `topology_no_self_refine`, `topology_fleet_no_siga` estão registradas como aliases de baseline/fleet no MVP. Implementar a lógica real de cada ablation para permitir comparações de latência/custo.
- [ ] **SEIWriter DOM walking**: skeleton com `_FORBIDDEN_SELECTORS` + `_safe_click` pronto, mas selectors do SEI real precisam ser adicionados (comentários `# NOTE:` marcam os pontos).
- [ ] **Ollama/Qwen3-8B**: cascade pronto em `llm/router.py`, falta deploy operacional do modelo local.
- [ ] **3 testes flaky LiteLLM** (`test_classify_email_*`, `test_partial_failure`) — pré-existentes, dependem de network ao MiniMax. Mockar com `responses` ou `litellm.testing` ao invés de chamar a API real.

### Out of scope (decisão alinhada com a coordenação)
- ❌ **SIGA write ops** — permanece read-only por design.
- ❌ **SEI sign/send/protocol** — proibido arquiteturalmente. `SEIWriter` não expõe esses métodos; 6 testes regressivos garantem que nenhum `sign()`/`enviar()`/`protocolar()` apareça na classe.
