# TASKS — Roadmap

> Para o histórico completo de tarefas executadas (Marcos I/II/II.5/III), consulte `git log` ou versões anteriores deste arquivo.

## Status atual

| Marco | Status | Resumo |
|---|---|---|
| **Marco I** — Protótipo | ✅ | Pipeline Perceber→Pensar→Agir, OWA Playwright + Gmail IMAP, auto-login MFA, anexos (PDF/DOCX/XLSX), salva como rascunho |
| **Marco II** — Roteamento Agêntico | ✅ | LangGraph StateGraph, RAG (LanceDB + RAPTOR), Self-Refine, DSPy (gate `USE_DSPY` tri-state), Reflexion, Locator chain, Model cascading |
| **Marco II.5** — SEI/SIGA + Scheduler | ✅ | Módulos SEI/SIGA (read-only, Playwright), pipeline expandido, ProcedureStore, scheduler (3x/dia), Streamlit feedback UI |
| **Marco III** — Cognição Relacional | ✅ | GraphRAG/Neo4j (1.757 nós, 2.296 rels), **LangGraph Fleet** (sub-agentes paralelos via `Send` API + reducers), **AFlow** (5 topologias hand-authored + evaluator), **SEIWriter** (attach + draft only, sem sign/send/protocol), **TemplateRegistry** (despachos via Neo4j) |
| **Marco IV — em andamento** | 🟡 | Estágios end-to-end: `Intent` estendido (`sei_action`, `required_attachments`, `blocking_checks`, `despacho_template`, `acompanhamento_especial_grupo`), `SEI_DOC_CATALOG.yaml`, **15 checkers** registrados (11 iniciais + 4 aditivo/conclusão), `SEIWriter` com **live mode wired up** para TODOS os 4 métodos write (`create_process`/`attach_document`/`save_despacho_draft`/`add_to_acompanhamento_especial` via `sei/writer_selectors.py` + `sei_selectors.yaml` + defaults in-source para POP-38). **POP-38 Fase 2 concluída em 2026-04-21** — live path de `add_to_acompanhamento_especial` implementado: navega toolbar → trata os 2 casos (já tem grupo → `gerenciar_processo` → `#btnAdicionar`, nunca teve grupo → `cadastrar` direto); seleciona `#selGrupoAcompanhamento` por texto visível; se grupo não existe, clica `#imgNovoGrupoAcompanhamento`, aguarda iframe modal `grupo_acompanhamento_cadastrar`, preenche `#txtNome`, submit modal, aguarda modal fechar, re-seleciona no outer form; preenche `#txaObservacao` (opcional); submit `button[name="sbmCadastrarAcompanhamento"]`. `_safe_frame_click` guard preserva `_FORBIDDEN_SELECTORS`. Cobertura em `test_sei_writer.py` + `test_sei_writer_acompanhamento_live.py` (8 testes do live path: dry-run não submete, grupo existente, grupo novo via modal, regressão forbidden selectors). Scripts de captura (`scripts/sei_drive.py`) e smokes live (`scripts/smoke_create_process_live.py`, `scripts/smoke_writer_live_e2e.py`). **Sprint 3 validado em 2026-04-16** (run_id `c0357e8dd8f2`, processo fictício `23075.022027/2026-22`): 3 ops live `success=true`, despacho body limpo (fix Ctrl+A+Delete confirmado via screenshot). Side-effect: `sei/browser.py:auto_login` corrigido — sei.ufpr.br tem 2 elementos `pwdSenha` (hidden decoy `type=password name=pwdSenha` + visible real `type=text id=pwdSenha`), `.first` resolvia para o decoy; fix usa `input#pwdSenha` puro + `#sbmAcessar` como botão primário. **Fleet smoke em batch real validado em 2026-04-18** (4 smokes consecutivos via `--channel gmail --langgraph --limit 10`): smoke #1 + #2 revelaram 2 bugs (intent `sei_action="attach_document"` inválido → corrigido para `append_to_existing`; `perceber_gmail` não chamava `extract_text_from_attachment` — regressão silenciosa do pipeline linear legado); smoke #3 validou extração de anexos (aditivo: 4 campos faltando → 2; acuse_inicial: 4 → 1); smoke #4 com `numero_tce` movido para opcional (feedback do Lucas: nem todo TCE tem número) produziu **primeiro Tier 0 hit end-to-end** (intent `estagio_nao_obrig_acuse_inicial`, keyword score 1.00) e **primeiro `agir_estagios` fire real** — resultou em SOFT BLOCK (3 pendências), portanto SEIWriter live não foi acionado (caminho correto: rascunho de email pedindo justificativa). SEIWriter live create_process ainda não exercitado via pipeline; aguardando email de aluno 100% ok nos checkers. **Restante:** flipar `SEI_WRITE_MODE=live` como default em prod depois de primeiro create_process real end-to-end pelo pipeline. Regex `_ADITIVO_RE` + datas em extenso (helper `_parse_br_date`) **adicionado em 2026-04-19** — Tier 0 de aditivo agora extrai `numero_aditivo` e `data_termino_novo` do PDF. |

**Testes:** 885 passando, **0 falhas** (`pytest ufpr_automation/tests/ -v`) — cobertura recente expandida: raptor (+10), siga eligibility rewrite (+24, replaces 12), aflow tie-break (+4), POP-38 skeleton (+3), OD501/ODDA6 graduation timing (+4), gmail client helpers (+22), LLM client _extract_json/_build_messages/self-refine (+16), checker helpers _parse_br_date/_working_days_between (+11), perceber_gmail attachment extraction regression (+1), Estágios intents não exigem numero_tce (+1), aditivo extraction: numero_aditivo + data_termino_novo (numérico + extenso) + _parse_br_date helper (+10), nome_aluno_maiusculas + nome_concedente_maiusculas em extract_variables (+2, pra despacho templates), **Tier 0 reformulado: boundary = RAG (não LLM). `Intent.llm_extraction_fields` dispara LLM bounded no cheap CLASSIFY model, sem RAG, ainda dentro do Tier 0. Primeiro uso: `estagio_nao_obrig_pendencia.lista_pendencias`. (+5 testes)**, **POP-38 live path (2026-04-21)**: `add_to_acompanhamento_especial` live wired-up com fake-Playwright em `test_sei_writer_acompanhamento_live.py` — 8 cenários (dry-run sem submit, grupo existente, grupo novo via modal, regressão forbidden selectors). Fix: `test_empty_state` patched para não depender de G: drive. AsyncMock RuntimeWarnings suprimidas via `filterwarnings` em `pyproject.toml`.
**RAG:** 35.084 chunks (backlog ingerido em 2026-04-20: +111 PDFs / +799 chunks — `sei_pop` 61 PDFs/179 chunks, `design_grafico` 5/294, `ufpr_aberta` 45/326, 0 erros). Root cause do bloqueio original **não era** paging file / `OS error 1455` — era o LanceDB fazendo commit atômico (rename de `_versions/*.manifest`) direto em `G:/Meu Drive/...`, que o Google Drive Desktop responde com `Função incorreta (os error 1)`. **Workaround validado**: rodar ingest com `RAG_STORE_DIR=C:/Users/Lucas/rag_store_local` (store local) e depois espelhar local → G: com `robocopy /E /COPY:DAT` (robocopy lida com Drive sync; LanceDB não). Próximos ingests devem seguir esse padrão.

## Pendente

### 🔵 Refator (branch `refactor/codebase-simplification`) — Ondas 2-5 pendentes

Branch criada em 2026-04-30 a partir de `dev@c16b338`. Auditoria via 6 agents Explore identificou ~1700 LOC removíveis sem mudança de comportamento. Onda 1 (cleanup seguro, ~500 LOC) iniciada nesta sessão. Ondas 2-5 ficam pendentes pra sessões dedicadas.

**Onda 2 — Deletar AFlow inteiro** ✅ executada 2026-05-02 na branch `refactor/onda-2-delete-aflow` (PR pendente). −~1700 LOC líquido entre código + tests. Decisão tomada: **opção A** (deletar limpo).
- **Justificativa**: AFlow é hand-authored topology evaluator MVP que nunca foi exercitado em produção. 4 das 5 topologias (`baseline`, `skip_rag_high_tier0`, `no_self_refine`, `fleet_no_siga`) são CLI-only ablation study; default sempre é `fleet`. Evaluator (`python -m ufpr_automation.aflow.cli`) nunca foi rodado contra eval set. Função de avaliação (necessária pra fazer sentido) nunca foi escrita.
- **Passos** (assumindo A):
  1. `grep -r "AFLOW_TOPOLOGY=" .env*` — confirmar que ninguém usa não-`fleet`. Se aparecer, pausar e conversar.
  2. `rm -r ufpr_automation/aflow/`
  3. Em `graph/builder.py:76-98` remover bloco `topology_override`
  4. Em `nodes.py:617`, `nodes.py:827`, `fleet.py:198` remover `if AFLOW_TOPOLOGY == "..."` checks
  5. Em `config/settings.py` remover `AFLOW_TOPOLOGY`, `AFLOW_METRIC`, `AFLOW_EVAL_LIMIT`
  6. `tests/test_aflow.py` → deletar; verificar se outros tests importam de aflow
  7. CLAUDE.md → remover seção AFlow (linhas ~98-101 + bloco tabela 106-115)
  8. ARCHITECTURE.md → remover linha 47 (caixinha AFLOW) + seção 277+
  9. Junto: deletar legacy batch nodes em nodes.py (`rag_retrieve` 597-690, `classificar` 842-890, `consultar_sei` 1000-1070, `consultar_siga` 1215-1254 — ~360 LOC). Existem só pra `baseline`, com AFlow morto ficam órfãos.
  10. Junto (desbloqueado pela #9): mover `rag/raptor.py` → `rag/advanced/raptor.py` (deveria ter ido na Onda 1.4 mas estava bloqueado pelo `rag_retrieve` em `nodes.py:562` que importava lazy). Atualizar CLI command em README/CLAUDE.md (`python -m ufpr_automation.rag.advanced.raptor`). Mover `tests/test_raptor.py` se necessário pra refletir o novo path.
- **Verificação**: `pytest -q` (espera ~1050 passing); smoke Letícia produz mesmo output; 1 run agendado real (08h/13h/17h) com pelo menos 5 emails.

**Onda 3 — Deletar DSPy modules** (~240 LOC, 2-3h, risco médio)
- **Justificativa**: gate `USE_DSPY=auto` procura `dspy_modules/gepa_optimized.json` que **nunca foi gerado** (otimização requer 20+ feedback samples; corpus está vazio). Path real é sempre LiteLLM via `_classify_with_litellm`. Deletar = 0 mudança runtime.
- **Sequência crítica** (uma ordem errada quebra coisas):
  1. **Migrar `Categoria` legacy alias map**: em `dspy_modules/modules.py` há dict mapeando `"Ofícios"`/`"Memorandos"`/`"Portarias"`/`"Informes"` → `"Outros"`. Mover pra `core/models.py` como `_LEGACY_CATEGORIA_ALIAS` + aplicar em parser do LLM client ou em `EmailClassification.__post_init__`.
  2. Em `nodes.py` remover `_compiled_prompt_paths()`, `_has_compiled_prompt()`, `_should_use_dspy()`, `_classify_with_dspy()` (700-770). No callsite, deixar só LiteLLM path.
  3. Deletar `dspy_modules/optimize.py`, `signatures.py`, `modules.py`, `metrics.py`. `__init__.py` vazio ou deletar package se não houver imports residuais.
  4. Deletar `tests/test_dspy_*` (verificar quais existem). Atualizar tests não-DSPy que mockavam `_should_use_dspy` pro path único.
  5. `pyproject.toml`: remover `dspy` do `[marco2]` extra (mantém `langgraph` + `apscheduler`).
  6. CLAUDE.md: remover seção DSPy gate.
  7. `config/settings.py`: remover `USE_DSPY` env var.
- **Verificação crítica**: `grep -r "import dspy" ufpr_automation/ tests/` deve retornar zero.
- **Risco**: residual em alguma referência a `_should_use_dspy` ou `Categoria` alias map não migrado.

**Onda 4 — Cross-module consolidation** (~100 LOC, 3-4h, risco médio)
4 commits independentes, do menos arriscado pro mais:
- **4.1 IMAP context manager** (gmail) 30min: criar `_with_imap_connection(fn)` em `gmail/client.py`; aplicar em `apply_labels`/`mark_read`/`list_unread` (3 try/except/logout idênticos). Risco: baixo.
- **4.2 `_FORBIDDEN_SELECTORS` consolidation** 30min: criar `ufpr_automation/_guard_selectors.py` com lista + `_is_forbidden(selector)`. `sei/writer.py:53-71` e `siga/selectors.py:55-67` importam ao invés de duplicar. Risco: baixo (defesa em camadas).
- **4.3 Selector YAML loader unification** 60min: criar `_selectors_loader.py` com `load_selectors_yaml(path, defaults, manifest_type)` + `lru_cache`. `sei/writer_selectors.py` e `siga/selectors.py` reduzem pra ~30 LOC cada. Risco: médio.
- **4.4 Browser lifecycle** 60-90min: mover `has_credentials`/`has_saved_session`/`launch_browser`/`create_browser_context`/`save_session_state` pro `_session_browser.py` parametrizados. `sei/browser.py` e `siga/browser.py` viram thin wrappers só com `auto_login` e `is_logged_in`. Risco: médio (toca login path) — smoke ao vivo + simulação de session expirada (`rm session_data/sei_state.json`).

**Onda 5 — Decompor long functions** (~0 LOC delta, 4-6h, risco médio-alto, **opcional**)
Refactor mecânico (extract method), do mais seguro pro mais arriscado:
1. `agir_gmail()` 163L → extrair `_label_email()` (30min, baixo)
2. `tier0_lookup()` 130L → extrair `_tier0_lookup_one_email(email, playbook, ...)` (45min, baixo)
3. SIGA `validate_internship_eligibility()` 97L → `_check_matricula()` + `_check_curriculum()` + `_check_graduation_timing()` + `_check_reprovacoes()` (60min, baixo)
4. LLM `_build_messages()` 60L → `_inject_rag_context()` + `_inject_attachments()` (45min, médio)
5. SEI `find_in_acompanhamento_especial()` 67L + `find_processes_by_keyword_filtered()` 56L → sub-helpers (60min, baixo)
6. SIGA `auto_login()` 82L (Keycloak) → `_fill_keycloak_credentials()` + `_select_role_card()` + `_wait_siga_home()` (60min, médio — toca auth)
7. **`agir_estagios()` 318L → `_run_blocking_checks_for_email` + `_draft_blocked_response_for_email` + `_execute_sei_chain_for_email`** (90-120min, mais arriscado — toca SEI write chain). Smoke completo + verificação manual de cada hard/soft block.

**Sequenciamento recomendado entre ondas**: Onda 1 (esta sessão) → push + 1 dia repouso + smoke. Onda 2 (sessão dedicada). Onda 3 (sessão dedicada). Pausa de 1 semana com pipeline em produção. Ondas 4-5 conforme paciência.

**Combinações a evitar**: Onda 2 + Onda 4.4 (AFlow + browser lifecycle juntos = muita superfície). Onda 5.7 (`agir_estagios`) sem ter feito 1-4 antes.

**Reverter qualquer onda**: `git revert <commit-sha>` ou `git reset --hard <ref>`. Cada onda é commit autocontido por design.

---

### 🔴 PRIORIDADE — Marco IV: Estágios end-to-end (próxima sessão)

Fluxo objetivo: receber TCE → criar processo SEI → anexar TCE → lavrar Despacho → rascunhar email de acuse. Infraestrutura lógica pronta (modelo `Intent` estendido, `SEI_DOC_CATALOG.yaml`, checker registry com 11 checks, `SEIWriter` com dry-run), falta o fluxo Playwright ao vivo e o wire-up no graph.

**▶ SDD detalhado:** [`SDD_SEI_SELECTOR_CAPTURE.md`](SDD_SEI_SELECTOR_CAPTURE.md) — especificação completa pra rodar a sprint de captura via Claude Code (plano Max, sem API key).

- [x] **Smoke test `SEIWriter` dry-run end-to-end** — `test_sei_writer.py::TestSEIWriterDryRunEndToEnd` exercita `create_process` → `attach_document` → `save_despacho_draft` em dry-run, valida JSONL de audit (3 records em ordem, mode=dry_run).
- [x] **Captura de seletores Playwright em sessão SEI ao vivo** (Sprints 1+2 concluídas):
  - [x] **Sprint 1 — Captura** (ver SDD §6): `scripts/sei_drive.py` (driver não-interativo) + manifesto gerado em `procedures_data/sei_capture/20260413_192020/sei_selectors.yaml` (schema SDD §5)
  - [x] **Sprint 2 — Wire-up** (ver SDD §7): `sei/writer_selectors.py` carrega + valida o YAML (fails fast se selector colide com `_FORBIDDEN_SELECTORS`); os 3 `NotImplementedError` em `sei/writer.py` substituídos por fluxos Playwright completos (`create_process`, `attach_document`, `save_despacho_draft`)
  - [x] **Sprint 3 — Validação** (ver SDD §8): `scripts/smoke_writer_live_e2e.py` rodado em 2026-04-16 — run_id `c0357e8dd8f2`, processo fictício `23075.022027/2026-22` (anular manualmente na UI do SEI). 3 ops `mode=live` `success=true` em `audit.jsonl`; inspeção visual do screenshot `draft_editor_filled.png` confirma que o corpo do despacho é **apenas** o texto do smoke (fix Ctrl+A+Delete do `_clear_editor_body` funcional). Side-effect: fix real em `sei/browser.py:auto_login` — selector `input[type="password"]` resolvia para decoy hidden; `input#pwdSenha` + `#sbmAcessar` agora corretos.
  - [x] ~~Flipar `SEI_WRITE_MODE=live` em produção~~ — `.env` do user em live desde 2026-04-23; default em código flipado para `"live"` em 2026-04-24 (`config/settings.py:271`). Fallback `dry_run` fica disponível via env var explícita pra smokes offline/CI.
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
- [x] **Skip drafting + corpus de aprendizado humano** (2026-04-22) — quando o coordenador responde manualmente de `design.grafico@ufpr.br` (CC para `design.grafico.ufpr@gmail.com`), o pipeline: (a) detecta via `thread_last_sender` (Gmail `X-GM-THRID`) que a thread já foi tratada, (b) seta `EmailData.already_replied_by_us=True`, (c) `agir_gmail` e `agir_estagios` pulam o rascunho, (d) novo node `capturar_corpus_humano` copia a thread inteira para o label Gmail `aprendizado/interacoes-secretaria-humano` e registra `feedback_data/learning_corpus.jsonl` (`{thread_id, categoria, intent_name, labeled_at}`). Idempotente por `thread_id`; marca a mensagem CC'd como lida pra não re-processar. Env vars: `INSTITUTIONAL_EMAIL` (default `design.grafico@ufpr.br`), `GMAIL_LEARNING_LABEL`. 16 testes novos (5 thread fetch/copy + 2 agir_gmail skip + 4 corpus + 1 agir_estagios skip + 4 thread_last_sender). **Futuro (Marco V)**: mineração das threads deste label como few-shot do `intent_drafter.py` para gerar `PROCEDURES_CANDIDATES.md` com base em respostas reais do humano — ver seção "Marco V futuro" abaixo.

### Histórico de conclusões

Seções "✅ Concluído" mais antigas (2026-04-22 em diante) movidas para [COMPLETED_TASKS.md](COMPLETED_TASKS.md) pra reduzir ruído no roadmap atual. Para histórico completo (Marcos I/II/II.5/III), `git log`.

### Bugs descobertos no smoke 2026-04-22 (não críticos)
- [x] ~~**SIGA login timeout Keycloak SSO**~~ — corrigido commits `56c8224`/`8bbe917`: trocadas 3 chamadas `wait_for_load_state("networkidle", 20s)` por waits element-based (`a:has-text('Discentes')`). Bug secundário de locator CSS inválido (`input#username, text=...`) também corrigido.
- [x] ~~**SIGA "aluno não encontrado" para GRR válido**~~ — corrigido commit `dc8039c`: campo de busca é client-side, filtrava só 20 alunos/página (default). Fix: setar pagination para 300 antes do filter.
- [x] ~~**`extract_sei_process_number` matchava IFPR/MEC**~~ — corrigido commit `dc8039c`: regex restrito a `23075.*`.
- [x] ~~**Fleet OOM com N ≥ ~5 sub-agentes carregando `multilingual-e5-large` concorrentemente**~~ — corrigido commit `76ed482`: singleton `get_shared_embedder()` em `rag/_embedder.py` (lru_cache, thread-safe porque `SentenceTransformer.encode` é thread-safe para inferência). Usado por `Retriever`, `ReflexionMemory` e `RaptorRetriever`. 4 testes em `test_shared_embedder.py` + regressão 65 tests. Reversão trivial: deletar `_embedder.py` e restaurar chamadas `SentenceTransformer(...)` diretas nos 3 construtores. Complementado por `FLEET_MAX_CONCURRENT_SUBAGENTS` (default 2): semáforo em `graph/fleet.py:process_one_email` que serializa os sub-agentes além do pool Send do LangGraph. Env var tunável; o usuário setou `=1` em 2026-04-23 até expandir a RAM disponível.
- [x] ~~**DSPy + Fleet thread conflict**~~ — corrigido commit `421d2a4`: `_classify_with_dspy` agora usa `with dspy.settings.context(lm=lm):` em vez de `dspy.configure(lm=lm)`. `settings.context` é thread-local (documentado em `dspy/dsp/utils/settings.py:54-62`: *"Any thread can use dspy.context. It propagates to child threads..."*) — cada sub-agente Fleet seta o próprio LM sem mutar o estado global. Validado ao vivo no smoke 2026-04-23 16:14 — 4 sub-agents carregaram DSPy simultaneamente sem crash (4× `DSPy: loaded optimized module from gepa_optimized.json`). Teste de regressão em `test_dspy_thread_safety.py` (5 threads concorrentes, zero exceções). `USE_DSPY=auto` restaurado no `.env`.
- [x] ~~**`AFLOW_TOPOLOGY=baseline` quebra com `RuntimeError: asyncio.run() cannot be called from a running event loop`**~~ — corrigido 2026-04-24: novo helper `_run_async_safe(coro)` em `graph/nodes.py` detecta loop rodando via `asyncio.get_running_loop()` e, quando presente, despacha o coroutine em `ThreadPoolExecutor(max_workers=1)` (thread sem loop → `asyncio.run` funciona). Aplicado em **7 sync nodes** que invocavam `asyncio.run` direto: `perceber_owa`, `prewarm_sessions`, `classificar`, `consultar_sei`, `consultar_siga` (baseline path), `_consult_sei_for_email` + `_consult_siga_for_email` (Fleet single-email), e `agir_estagios._run_sei_chain`. 3 testes em `test_graph_nodes.py::TestRunAsyncSafe` cobrindo (a) sem loop rodando, (b) com loop rodando (simula LangGraph), (c) propagação de exceção da worker thread.

### Bugs descobertos no run 2026-04-24 (Alanis / forward da Stephania)
- [x] ~~**`nome_aluno` extraído do forwarder em vez do aluno em emails encaminhados**~~ — corrigido: novo `_extract_forwarded_original_sender(body)` em `procedures/playbook.py` detecta marcador de forward (`Forwarded message`/`Mensagem encaminhada`/`Mensagem Original`) e extrai a linha `De:`/`From:` interna. `extract_variables` agora prefere esse nome sobre o outer `From:` quando há marcador; fallback para sender original quando não há. Regressão real: email "Fwd: Assinatura do termo de estágio" da Stephania (professora) encaminhando TCE da Alanis (aluna) — template Tier 0 dizia "estudante Stephania Padovani" em vez de "estudante Alanis". 4 testes novos em `test_playbook.py::TestExtractVariables` (pt/en/outlook/no-forward-baseline).

### Bugs descobertos no run 2026-04-23 (Paloma / aditivo end-to-end)
- [x] ~~**LLM alucinando setor/assinatura** — "Núcleo de Estágios / UFPR" apareceu no rascunho salvo para a Paloma no 1º run (pré-fixes). Esse setor NÃO EXISTE: não está em `SOUL.md`, `SOUL_ESSENTIALS.md`, `AGENTS.md`, `PROCEDURES.md` nem `.env`. MiniMax-M2 inventou do zero. Rascunhos de outros runs mostraram variações: "Secretaria do Curso de Design Gráfico", "Secretaria da Coordenação do Curso de Design Gráfico (SACOD)", etc. — drift total da persona oficial.~~ — corrigido: (a) instrução explícita anti-alucinação no `user_prompt` de `LLMClient._build_messages` listando o setor real e proibindo variações; (b) `normalize_signature_block()` em `gmail/client.py` chamado dentro de `save_draft` corta qualquer sign-off ("Atenciosamente,"/"Att,"/"Cordialmente,"/"Saudações,"/"Respeitosamente,") do LLM, remove linhas com setores-fantasma conhecidos (whitelist extensível) e reappenda `settings.ASSINATURA_EMAIL` canônica. 9 testes em `test_signature_normalization.py` cobrindo o bug real da Paloma + aliases + idempotência + mid-text "atenciosamente" não ser cortado.
- [x] ~~**Drafts stale acumulam em re-runs**~~ — corrigido: `save_draft` agora chama `_delete_existing_drafts()` antes do APPEND. Dedup por `In-Reply-To` (via `X-GM-RAW rfc822msgid:`) com fallback para `TO` — remove qualquer draft pra o mesmo destinatário na mesma thread antes de salvar o novo. Log explicita "substituiu N antigo(s)" quando dedupe acontece.
- [x] ~~**Tier 0 HIT não consulta SEI antes de `agir_estagios`**~~ — corrigido: novo node `consultar_tier0_sei_siga` em `graph/nodes.py` entre `prewarm_sessions` e o conditional `dispatch_tier1`. Para cada Tier 0 HIT cuja intent declara `sei_action != "none"` (aditivo/conclusão/rescisão/novo TCE), roda `_consult_sei_for_email` + `_consult_siga_for_email` (os mesmos helpers que o Fleet sub-agent usa) e popula `sei_contexts` / `siga_contexts` antes do `agir_estagios`. Emails não-eligíveis (Outros, sei_action=none) são no-op. Falhas per-email são isoladas (SEI exception não quebra SIGA do mesmo email, tampouco de outros emails). 7 testes em `test_consultar_tier0_sei_siga.py` cobrindo no-op vazio, caminho completo (SEI+SIGA populam), skip de sei_action="none", skip de não-Estágios, isolamento de falha, None não polui dict, integração com o graph compilado.
- [ ] **Tesseract não empacotado** — OCR de PDFs escaneados exige binário Tesseract (UB-Mannheim 5.4.0) instalado manualmente pelo user em `C:\Program Files\Tesseract-OCR\` + `pytesseract`+`Pillow` no venv. Download do mirror oficial (`digi.bib.uni-mannheim.de`) está bloqueado na rede UFPR — GitHub release mirror (`github.com/UB-Mannheim/tesseract/releases`) funciona. Instalação silenciosa no user-profile falhou por UAC; precisa admin interativo. Validado ao vivo 2026-04-23: sem OCR a Paloma caía em Tier 1 com required_fields ausentes; com Tesseract+`por.traineddata` ela bateu Tier 0 HIT (keyword 1.00, `estagio_nao_obrig_aditivo`). Sem pendência de código — nota apenas para reprodução do ambiente.

### Bugs descobertos no smoke 2026-04-30 (Letícia / GRR20244602)

Smoke `scripts/smoke_agir_estagios.py --message-id CAA_UPeAvQMfoX4ssSbAqu9H-VqYY8D3FeUrYNyMBTLGr1NF_cQ@mail.gmail.com` rodado pra validar agir_estagios fim-a-fim. Resultado: `HARD BLOCK — 4 hard + 6 soft → draft unificado`. Inspeção da saída revelou 2 bugs.

- [ ] **🔴 SIGA `_navigate_to_student` retornando aluno errado** — `siga/client.py:68` consultou `GRR20244602` (Letícia Fonceca, confirmado pelo user) e retornou `nome="LOUIE PEDROSA DE SOUZA"` cujo GRR real é `GRR20231692`. Bug de **integridade de identidade**: todos os checkers que dependem de `siga_data["nome"]` viram lixo (`siga_concedente_duplicada`, `supervisor_formacao_compativel`, etc.) e SEI ops live (`add_to_acompanhamento_especial`) podem ser disparadas contra a pessoa errada. Hipóteses (em ordem de probabilidade):
  1. Filtro client-side `input[placeholder*='Nome ou Documento']` não escopa por GRR-only — `select_option(300)` foi bem-sucedido mas o filter não aplicou; `table tbody tr a:first` cai na 1ª linha da tabela inteira.
  2. `await asyncio.sleep(2)` insuficiente — Vue.js SPA, filter assíncrono; precisa esperar até DOM da tabela mudar (esperar `tbody tr` count <= 1 ou que o GRR procurado apareça em alguma row).
  3. 2+ `<a>` em `table tbody tr a`; `.first` clica no errado (botão de ação vs link de perfil).
  4. Placeholder do campo de busca mudou no SIGA, locator falha silencioso.
  
  **Fix mínimo (defensivo, baixo custo)**: depois de `_navigate_to_student`, `_extract_info_gerais` já extrai `info["grr"]` do header (`re.search(r"GRR\d+", txt)`); adicionar **assert** entre GRR consultado e GRR retornado em `check_student_status`/`get_historico`/`get_integralizacao`/`validate_internship_eligibility` — se diferente, retornar `None` e logar `ERROR` com ambos os GRRs. Isso para o sangramento.
  
  **Fix de raiz**: substituir `table tbody tr a:first` por seletor que escolhe a row cujo cell de GRR bate com `grr_clean`. Considerar `await self._page.wait_for_function(...)` esperando até a tabela estar filtrada (count de tbody rows estável).

- [x] ~~**🟡 Anexos PDF retornando `extracted_text=0 chars`**~~ — investigação 2026-04-30 fechou: era gap do **smoke**, não bug de produção. `GmailClient.list_unread` só baixa anexos; quem chama `extract_text_from_attachment` é o node `perceber_gmail` em [graph/nodes.py:60-61](ufpr_automation/graph/nodes.py:60). O smoke chamava só `list_unread`, então `att.extracted_text` ficava vazio → checkers viam falsos hard_blocks. Verificado: pytesseract 0.3.13, PIL 12.2.0, Tesseract 5.5.0 no PATH, `_is_tesseract_available() → True`. Fix: smoke agora chama o extractor após o fetch ([scripts/smoke_agir_estagios.py:fetch_email_by_msgid](scripts/smoke_agir_estagios.py)).

- [x] ~~**🔴 SIGA `_navigate_to_student` retornando aluno errado**~~ — fix 2026-04-30 em 2 camadas:
  1. **Raiz**: `table tbody tr a:first` (1ª row de toda a tabela) substituído por `table tbody tr:has-text('GRR…')` + fallback `:has-text('<digits>')`, com `wait_for(state="visible", timeout=8000)` em vez de `asyncio.sleep(2)` fixo. Click agora vai pro link **dentro da row específica do GRR**, não pra `.first` global.
  2. **Defensivo (rede de segurança)**: novo helper `_extract_grr_from_header()` extrai `GRR\d+` do header `<h2>Discente</h2>` da página de detalhes. Após o click, `_navigate_to_student` confere `actual_grr == expected_grr` — se diferente (cache/race/filtro furado/SIGA bug), loga `ERROR` e retorna `False`. Cobre todos os 4 call sites (`check_student_status`, `get_historico`, `get_integralizacao`, `validate_internship_eligibility` indireto).
  
  Validado ao vivo no smoke da Letícia (2026-04-30 16:24): `_navigate_to_student("GRR20244602")` agora retorna corretamente `LETICIA FONCECA RAMALHO` (era `LOUIE PEDROSA DE SOUZA`/`GRR20231692` antes).

### Bugs descobertos no smoke 2026-04-30 (parte 2 — pós-fix-SIGA)

Com o smoke agora extraindo texto do PDF e o SIGA retornando o aluno certo, o output do smoke da Letícia revelou um **gap de cobertura adicional** no `_consult_siga_async`:

- [x] ~~**🟡 SIGA context não popula chaves que os checkers esperam**~~ — fix 2026-04-30:
  - `EligibilityResult` em [siga/models.py](ufpr_automation/siga/models.py) estendido com `historico_data: dict` e `integralizacao_data: dict`.
  - `validate_internship_eligibility` em [siga/client.py](ufpr_automation/siga/client.py) agora captura os dicts retornados por `get_historico()` e `get_integralizacao()` em vez de descartá-los após calcular as regras.
  - Nova função pura `_eligibility_to_siga_context(grr, eligibility)` em [graph/nodes.py](ufpr_automation/graph/nodes.py) extraída de `_consult_siga_async` mapeia pras chaves dos checkers:
    - `matricula_status` ← `_normalize_matricula_status(student.situacao)` (whitelist "ativ" → "ATIVA"; outros valores em uppercase)
    - `curriculo_integralizado` ← `integ["integralizado"]` (bool)
    - `nao_vencidas` ← `integ["nao_vencidas"]` (lista de siglas)
    - `reprovacoes_total` ← `historico["reprovacoes_total"]`
  - Fail-safe: `situacao=""` (extrator não achou Status na página) → `matricula_status` **não populada** → checker cai em soft_block "SIGA não consultado" em vez de hard-block falso "Matrícula  — estágio não permitido".
  - Validado live no smoke da Letícia (2026-04-30 17:07): falsos hard_blocks de matricula_ativa + curriculo_integralizado eliminados; 11 disciplinas em `nao_vencidas` populadas corretamente; checker `tce_jornada_antes_meio_dia` agora pode aplicar a exceção quando o conjunto bater.
  - **Restante**: `reprovacoes_ultimo_semestre` e `reprovacao_por_falta_ultimo_semestre` ainda exigem breakdown semestre-a-semestre que `get_historico` não fornece (`semesters=[]`). Esses 2 checkers continuam soft_block "SIGA não consultado" (fail-safe correto). Adicionar parsing semestral no `get_historico` é trabalho separado.
  - Tests: 20 novos em [test_graph_nodes.py](ufpr_automation/tests/test_graph_nodes.py) (`TestNormalizeMatriculaStatus` × 11 + `TestEligibilityToSigaContext` × 10, incluindo regressão pra `situacao=""` fail-safe).

- [x] ~~**Refatoração: estagio ativo / concedente duplicada saem do SIGA**~~ — 2026-04-30: removidos checkers `siga_ch_simultaneos_30h` e `siga_concedente_duplicada` (dependiam de `estagios_ativos` que nunca foi fetched do SIGA). Verificação de estágio ativo agora é responsabilidade exclusiva do SEI cascade — `_consult_sei_for_email` busca processos vigentes via Acompanhamento Especial e `sei_processo_vigente_duplicado` faz o block. Regra dos 30h/semana removida; substituída pela regra de **período**: `tce_jornada_antes_meio_dia` agora aceita exceção quando `nao_vencidas ⊆ {OD501, ODDA6, ODDA7}` (aluno só com TCC1/TCC2/Estágio Supervisionado pendentes pode estagiar de manhã, já que essas 3 não exigem aula matinal). Limpeza completa: `procedures/checkers.py`, `siga/client.py` (MAX_WEEKLY_HOURS), `tests/test_checkers.py`, `workspace/PROCEDURES.md`, `ARCHITECTURE.md`, `config/settings.py`.

### Validação manual em produção
- [ ] Validar login automático no SEI com sessão ativa e credenciais reais
- [ ] Validar login automático no SIGA com sessão ativa e credenciais reais
- [ ] Refinar seletores Playwright SEI/SIGA após inspeção do DOM real
- [ ] Rodar scheduler 1 dia completo em produção
- [ ] Coletar feedback via Streamlit e verificar ReflexionMemory
- [x] ~~Re-seed Neo4j para refletir Coordenadora correta (Stephania) + templates~~ — confirmado pelo user 2026-04-24 (já havia sido executado em sessão anterior).
- [x] Smoke do Fleet em batch real: `AFLOW_TOPOLOGY=fleet python -m ufpr_automation --channel gmail --langgraph --limit 10` — 4 smokes rodados em 2026-04-18; primeiro Tier 0 hit + agir_estagios fire confirmados (soft-block path).
- [ ] Smoke real exercitando SEIWriter `create_process` live end-to-end (precisa email de aluno que passe todos os checkers — sem reprovações, com TCE digital válido, vigência ok, jornada ok).
- [x] ~~Adicionar regex `_ADITIVO_RE`~~ e data em extenso em `procedures/playbook.py` — feito em 2026-04-19 (commit `a86a596`). Extrai `numero_aditivo` + `data_termino_novo` com helper `_parse_br_date`.

### Marco III — refinamentos pendentes
- [~] **`BrowserPagePool` wire-up** — **reavaliado, parked**. O pool em `graph/browser_pool.py` foi desenhado para um mundo async (compartilha `BrowserContext` entre sub-agentes via `asyncio.Semaphore`), mas `process_one_email` do Fleet é sync — LangGraph dispara os sub-agentes em thread pool, cada um com seu próprio event loop, e `BrowserContext` do Playwright é bound ao loop que o criou. Auditoria revelou que o custo real é menor do que parecia: `sei/browser.py` e `siga/browser.py` já reusam `storage_state` via `create_browser_context`/`save_session_state`, então em steady-state (sessão válida no disco) o Fleet com N Estágios faz 2N spawns de Chromium mas **0 logins**. Dor restante: (a) race no primeiro login do dia (N sub-agentes tentando `auto_login` em paralelo quando a session file está ausente/expirada), (b) overhead de spawn de Chromium. Refactor correto pra usar o pool exige tornar todo o Fleet async (cascata em `_classify_*`, retriever, graph context, reflexion) — custo alto, benefício marginal. Melhor alternativa: pre-warm node sync antes do dispatch que faz 1 login quando session está stale. Item abaixo cobre isso.
- [x] **Pre-warm SEI/SIGA sessions antes do Fleet dispatch** — node `prewarm_sessions` implementado entre `tier0_lookup` e `dispatch_tier1`. Gate via `PREWARM_SESSIONS_ENABLED=true` (default OFF). Scaneia emails por padrão SEI/GRR; para cada sistema (SEI, SIGA) cuja session file está ausente ou com idade ≥ `PREWARM_SESSIONS_MAX_AGE_H` (default 6h), faz 1 login async. SEI e SIGA rodam em paralelo via `asyncio.gather`. Falhas são não-fatais — sub-agentes fazem seu próprio `auto_login` se necessário. 8 testes em `test_graph_nodes.py::TestPrewarmSessions`. **Ativar via env var só se medição em produção mostrar race de login é dor real.**
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
- [x] **Fase 8 — SIGA Grounder (Grounded SIGA selectors)** — `siga/selectors.py` (loader YAML + `SIGASelectorsError` + `_FORBIDDEN_SELECTORS` read-only guard mirroring SEI pattern), `agent_sdk/siga_grounder.py` (discover BLOCO 3 markdown → compute hash → build prompt → invoke Claude CLI → extract YAML → validate schema + forbidden guard → atomic write to `procedures_data/siga_capture/<ts>/siga_selectors.yaml` + refresh `latest/`; idempotent via content hash; rejected candidates parked for human review), `agent_sdk/skills/siga_grounder.md` briefing, `siga/SELECTORS_SCHEMA.md` + `tests/fixtures/siga_selectors.example.yaml`. 61 testes em `test_siga_selectors.py` (31) + `test_siga_grounder.py` (30). **Grounder rodou com sucesso em 2026-04-14 contra `base_conhecimento/ufpr_aberta/bloco_siga_secretarias.md`** — manifest com 18 screens em `procedures_data/siga_capture/latest/siga_selectors.yaml` (gitignored; cópia da pasta timestamped também existe). Schema + forbidden-selector guards passaram. Próximo passo (pendente autorização humana): refatorar `siga/client.py` para consumir o manifest via `get_screen`/`get_field` no lugar dos guess-based locators atuais.
- [x] **Refactor `siga/client.py` com seletores grounded + navegação real** — `scripts/siga_capture_estagios.py` capturou DOM ao vivo via Portal de Sistemas SSO (Keycloak) → SIGA. `browser.py` reescrito para login SSO (`sistemas.ufpr.br` → `input#username/password` → `input#kc-login` → card "Coordenação / Secretaria - Graduação"). `client.py` reescrito com: `get_historico()` (IRA, reprovações por tipo/semestre), `get_integralizacao()` (CH summary, disciplinas Vencida/Não Vencida, OD501/ODDA6 tracking), `validate_internship_eligibility(grr, vigencia_meses)` (matrícula ativa, >2 reprovações → soft block, currículo integralizado → hard block, OD501/ODDA6 → tempo restante). Manifest `siga_selectors.yaml` atualizado com 19 tab pane_ids, spinner Vue.js, colunas de tabela. 24 testes (+ 31 selector tests). **Guia unificado de navegação SEI+SIGA** em `docs/NAVIGATION_GUIDE.md` — referência completa para tarefas que envolvam navegação nos sistemas.

### Marco V futuro — Mineração do corpus de aprendizado humano

▶ **Input**: label Gmail `aprendizado/interacoes-secretaria-humano` (populado por `capturar_corpus_humano`) + `feedback_data/learning_corpus.jsonl` (metadata por `thread_id`).

- [ ] **Harvester `agent_sdk/human_corpus_harvester.py`** — lê o label via IMAP, extrai `{email_original, resposta_humana}` por thread, agrupa por `intent_name` (quando o Tier 0 resolveu) ou por `categoria`+`clustered_subject` (quando não resolveu).
- [ ] **Extensão do `intent_drafter.py`** — usar as respostas humanas como few-shot real no prompt que geram `PROCEDURES_CANDIDATES.md`. Hoje o drafter só usa `procedures.jsonl`/`feedback.jsonl`; adicionar um modo `--source human-corpus` que puxa do label.
- [ ] **Detector de template estável** — heurística: quando ≥3 threads do mesmo intent têm resposta humana semanticamente próxima (cosseno e5-large), promover a resposta como candidato a `template` na intent do `PROCEDURES.md`.
- [ ] **Auditoria de qualidade** — diff de `sugestao_resposta` gerada pelo LLM vs. `resposta_humana` real da mesma thread — métrica de drift do tom institucional.

**Contexto**: a intuição é que a resposta humana em produção é o "ground truth" mais valioso pra refinar tanto o tom (SOUL_ESSENTIALS.md) quanto os templates (PROCEDURES.md). O label Gmail é fonte de verdade durável — sobrevive a refactors no código e permite auditoria manual direto pelo Gmail.

### Out of scope (decisão alinhada com a coordenação)
- ❌ **SIGA write ops** — permanece read-only por design.
- ❌ **SEI sign/send/protocol** — proibido arquiteturalmente. `SEIWriter` não expõe esses métodos; 6 testes regressivos garantem que nenhum `sign()`/`enviar()`/`protocolar()` apareça na classe.
