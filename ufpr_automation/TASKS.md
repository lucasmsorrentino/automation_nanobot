# 📋 TASKS — Roadmap do Sistema de Automação Burocrática UFPR

## Marco I — Protótipo de Ingestão Assistida

### ✅ Concluído

- [x] **Ambiente de desenvolvimento**
  - [x] Virtual environment (`.venv/`) com Python 3.12
  - [x] Instalação do nanobot (editable), Playwright, Chromium
  - [x] Arquivo `.env.example` para variáveis sensíveis

- [x] **Arquitetura e documentação**
  - [x] Diagrama Mermaid.js com 3 fases de maturidade (`ARCHITECTURE.md`)
  - [x] README.md do projeto com quickstart e estrutura
  - [x] Especificação original mantida (`INICIO.md`)

- [x] **Estrutura modular do projeto**
  - [x] `config/` — Configurações via `.env` (python-dotenv)
  - [x] `core/` — Modelos de domínio (`EmailData`)
  - [x] `outlook/` — Integração OWA (browser lifecycle + scraper)
  - [x] `cli/` — Interface de linha de comando (argparse)
  - [x] `utils/` — Utilitários (debug capture)
  - [x] `workspace/` — Integração nanobot (AGENTS.md, SOUL.md, SKILL.md)

- [x] **Playwright OWA — Perceber**
  - [x] Abrir navegador (headed/headless automático)
  - [x] Persistência de sessão (cookies + storage state)
  - [x] Detecção de login via URL + DOM
  - [x] Aguardar login manual (5 min timeout) — fallback
  - [x] **Login automático** (credenciais via `.env` + MFA number-match via Telegram Bot)
  - [x] **Re-login automático** quando sessão expira (sem intervenção manual)
  - [x] Varrer inbox e imprimir títulos dos e-mails
  - [x] 3 estratégias de fallback para extração (React selectors → aria → JS)
  - [x] Modo debug (`--debug`) com captura de DOM + screenshot

- [x] **Nanobot workspace**
  - [x] `AGENTS.md` — Personalidade do agente UFPR
  - [x] `SOUL.md` — Template de normas institucionais (ICL)
  - [x] `SKILL.md` — Skill do Outlook
  - [x] `config.json` — Provider LLM (LiteLLM)

- [x] **Integração com LLM (Pensar)**
  - [x] Criar módulo `llm/` com cliente LiteLLM (provider-agnostic)
  - [x] System prompt com normas da UFPR (ICL do `SOUL.md`)
  - [x] Classificação de e-mails: departamento, urgência, tipo
  - [x] Geração de resposta/ofício conforme normas

- [x] **Ação no OWA (Agir)**
  - [x] Criar módulo `outlook/responder.py`
  - [x] Clicar em "Responder" no e-mail via Playwright
  - [x] Digitar resposta gerada pelo LLM
  - [x] Salvar como rascunho (NUNCA enviar automaticamente)

- [x] **Arquitetura Multi-Agente**
  - [x] `agents/perceber.py` — PerceberAgent (scraping + corpo completo)
  - [x] `agents/pensar.py` — PensarAgent com chamadas LLM **concorrentes** (via LiteLLM)
  - [x] `agents/agir.py` — AgirAgent (salvar rascunhos)
  - [x] `orchestrator.py` — coordenador do pipeline Perceber → Pensar → Agir
  - [x] `outlook/body_extractor.py` — extração do corpo completo (não apenas preview)
  - [x] `llm/client.py` — adicionado `classify_email_async` para suporte a asyncio.gather

- [x] **Notificação (Notificar)**
  - [x] Relatório de ações pendentes no terminal (print_summary no orchestrator)

- [x] **Preencher SOUL.md — ICL completo**
  - [x] Normas do regulamento de estágio do Curso de Design Gráfico
  - [x] Manual de Estágios UFPR (COAFE/PROGRAD)
  - [x] Resoluções CEPE (46/10, 70/04, IN 01/12, IN 02/12, IN 01/13)
  - [x] Modelos de despacho SEI (TCE, Aditivo+Relatório, Rescisão)
  - [x] Templates de e-mail para situações comuns (6 modelos)
  - [x] Perguntas frequentes com respostas padrão (13 Q&As)
  - [x] Estrutura do Relatório de Estágio e dados de contato institucionais

### 🔜 Pendente — Robustez (Ordered by Impact)

- [x] **1. Identificação estável de e-mails (substituir email_index)**
  - [x] Gerar hash estável `sender + subject + timestamp` como ID único
  - [x] Agir valida que o e-mail aberto corresponde ao esperado antes de digitar
  - [x] Eliminar dependência de índice posicional que quebra se inbox muda

- [x] **2. Tratamento de falhas parciais no Pensar**
  - [x] Usar `asyncio.gather(*tasks, return_exceptions=True)` para não perder resultados bons
  - [x] Filtrar exceções e continuar pipeline com classificações bem-sucedidas
  - [x] Reportar falhas individuais no summary

- [x] **3. Rate limiting nas chamadas LLM paralelas**
  - [x] Adicionar `asyncio.Semaphore(max_concurrent=5)` no Pensar
  - [x] Evitar exaustão de quota LLM com muitos e-mails não lidos

- [x] **4. Substituir hard-coded `wait_for_timeout()` por waits adaptativos**
  - [x] Usar `wait_for_selector()` / `expect()` do Playwright onde possível
  - [x] Manter timeouts apenas como fallback com valores configuráveis

- [x] **5. Validação de `categoria` com Literal enum**
  - [x] Trocar `str` por `Literal[...]` em `EmailClassification.categoria`
  - [x] Garantir que LLM só retorna categorias válidas via schema

- [x] **6. Testes unitários mínimos**
  - [x] Testes para `core/models.py` (EmailData, EmailClassification)
  - [x] Testes para `llm/client.py` (mock LiteLLM, validar schema)
  - [x] Teste end-to-end do pipeline com dados mock

- [x] **7. Logging persistente (structured)**
  - [x] Adicionar logging estruturado (JSON) para arquivo em `logs/`
  - [x] Substituir `print()` por `logger.info()` nos módulos principais

- [x] **8. Suporte a anexos de e-mail**
  - [x] Modelo `AttachmentData` (filename, mime_type, size, local_path, extracted_text, needs_ocr)
  - [x] Campos `attachments` e `has_attachments` em `EmailData`
  - [x] Download de anexos via Gmail IMAP (`_extract_attachments` em `gmail/client.py`)
  - [x] Extração de texto: PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl), texto plano
  - [x] Injeção do texto dos anexos no prompt do LLM (`llm/client.py`)
  - [x] Integração no pipeline Gmail (`orchestrator.py`)
  - [x] Configuração via `ATTACHMENTS_DIR` e `ATTACHMENT_MAX_SIZE_MB`
  - [x] Imagens e PDFs escaneados marcados com `needs_ocr=True` (OCR na Fase 2)
  - [x] 11 testes unitários passando (`tests/test_attachments.py`)
  - [x] **Teste end-to-end validado (2026-04-06):**
    - 20 emails lidos, 7 com anexos (20 arquivos: PDFs, PNGs, JPGs)
    - PDFs com texto: extração OK (ex: despachos SEI, formulário horas formativas)
    - PDFs escaneados e imagens: marcados `needs_ocr=True` (10+ arquivos, aguardando Fase 2 OCR)
    - Texto dos anexos injetado no LLM — classificação correta (ex: "Problemas com Estágio" com despachos SEI → Estágios)
    - 20/20 classificações, 8 rascunhos salvos
    - 53 testes passando (0 falhas)

- [x] **9. Correção de testes existentes**
  - [x] `test_partial_failure` — mock baseado em conteúdo ao invés de call_count (compatível com Self-Refine)
  - [x] `test_all_pdfs` — skip quando pasta docs está vazia

### 🔜 Pendente — Validação Manual (requer sessão OWA)

> **Próxima tarefa.** Executar na ordem abaixo. Cada etapa depende da anterior.
> Usar `--headed --debug` nas primeiras tentativas para ver o que acontece no browser.

#### Etapa 1 — Validar login automático + MFA via Telegram

**Pré-requisitos:**
1. Preencher `ufpr_automation/.env` com valores reais:
   - `OWA_EMAIL` — e-mail institucional UFPR
   - `OWA_PASSWORD` — senha do e-mail
   - `TELEGRAM_BOT_TOKEN` — token do bot criado via @BotFather
   - `TELEGRAM_CHAT_ID` — seu chat ID (obter via @userinfobot no Telegram)
   - `GEMINI_API_KEY` — chave da API Gemini
2. Deletar `session_data/state.json` se existir (forçar login do zero)

**Comandos de teste:**
```bash
# Teste 1: Login automático com janela visível (observar o fluxo)
python -m ufpr_automation --headed --debug

# O que observar:
#   ✅ E-mail é preenchido automaticamente na página Microsoft
#   ✅ Senha é preenchida após o redirect
#   ✅ Número MFA de 2 dígitos aparece no console E no Telegram
#   ✅ Após aprovar no Authenticator, inbox é detectada
#   ✅ session_data/state.json é criado
```

**Se falhar:** Provavelmente os seletores da página de login da Microsoft mudaram.
Capturar o DOM com `--debug` e ajustar os seletores em `browser.py:auto_login()`.
Seletores-chave a verificar:
- Input de e-mail: `input[type="email"]` ou `input[name="loginfmt"]`
- Input de senha: `input[type="password"]` ou `input[name="passwd"]`
- Botão Next/Submit: `input[type="submit"]` ou `#idSIButton9`
- Número MFA: `#displaySign`

- [x] Auto-login preenche e-mail e senha corretamente
- [x] Número MFA é extraído e exibido no console
- [x] Notificação Telegram chega com o número MFA
- [x] Login conclui após aprovação no Authenticator
- [x] `session_data/state.json` é criado com sucesso

#### Etapa 2 — Validar scraping (Perceber)

**Pré-requisito:** Etapa 1 concluída (sessão salva).

```bash
# Teste 2: Scraping headless com sessão salva
python -m ufpr_automation --perceber-only

# O que observar:
#   ✅ Sessão é carregada sem precisar de login
#   ✅ E-mails não lidos são listados com remetente + assunto
#   ✅ Corpo completo é extraído (não apenas preview)
```

**Se falhar:** Seletores do OWA mudaram. Usar `--headed --debug` para capturar DOM.
Verificar as 3 estratégias de fallback em `scraper.py` e os seletores em `body_extractor.py`.

- [x] Sessão salva funciona em modo headless
- [x] `scraper.py` extrai lista de e-mails não lidos
- [x] `body_extractor.py` extrai corpo completo de cada e-mail

#### Etapa 2.5 — Migrar LLM de Gemini direto para LiteLLM + MiniMax ✅

> **Concluído em 2026-03-20.** Gemini free tier esgotado → migrado para LiteLLM + MiniMax-M2.

**Mudanças realizadas:**
1. `llm/client.py` reescrito: `GeminiClient` → `LLMClient` usando `litellm.completion()`/`acompletion()`
2. `config/settings.py` atualizado: `MINIMAX_API_KEY`, modelo padrão `minimax/MiniMax-M2`
3. `.env.example` atualizado com novas variáveis
4. JSON output via prompt instruction + `_extract_json()` (MiniMax não suporta `response_format`)
5. `classify_email_async` funciona com `asyncio.gather()` via `litellm.acompletion()`
6. Testes atualizados para mockar `litellm` — 17/17 passam

- [x] `llm/client.py` usa `litellm.acompletion()` em vez de `google.genai`
- [x] `config/settings.py` com `MINIMAX_API_KEY` e modelo padrão MiniMax
- [x] `.env.example` atualizado
- [x] Testes unitários passam com mock LiteLLM
- [x] Classificação funciona end-to-end com MiniMax API

#### Etapa 3 — Validar classificação LLM (Pensar) ✅

> **Concluído em 2026-03-20.** MiniMax-M2 via LiteLLM classifica corretamente.

**Resultado:** 3/3 e-mails classificados com sucesso (Estágios, Informes, Estágios).
- JSON válido retornado após stripping de markdown code fences
- Categorias corretas para e-mails institucionais
- Respostas sugeridas seguem normas UFPR do SOUL.md

- [x] LLM classifica e-mails corretamente (JSON válido)
- [x] Categorias fazem sentido para e-mails institucionais
- [x] Respostas sugeridas seguem normas UFPR do SOUL.md

#### Etapa 4 — Validar rascunhos (Agir) ✅

> **Concluído em 2026-03-20.** Pipeline end-to-end funcional: 3/3 rascunhos salvos.

**Resultado:** Pipeline completo executado com sucesso.
- Bug fix: adicionado `dismiss_owa_dialog()` para fechar modal "Descartar mensagem" que bloqueava entre rascunhos.

- [x] Playwright abre o e-mail correto (validação por hash sender+subject)
- [x] Resposta é digitada no campo de Reply
- [x] Rascunho é salvo na pasta Rascunhos
- [x] Pipeline end-to-end completo sem erros

#### Etapa 5 — Validar re-login automático ✅

> **Concluído em 2026-03-20.** Re-login headless funciona com auto-login + MFA via Telegram.

**Mudanças realizadas (bugs encontrados durante validação):**
1. `browser.py:is_logged_in()` — corrigido falso positivo: trocado `domcontentloaded` por `networkidle`, adicionado check negativo para `login.microsoftonline.com`, removido seletor genérico `[role="main"]`
2. `responder.py:_close_and_save_draft()` — salva rascunho com `Ctrl+S` antes de fechar, evitando diálogo "Descartar mensagem"
3. `responder.py:dismiss_owa_dialog()` + `_handle_save_dialog()` — seletores agora escopados a `div[role="dialog"]` para não clicar em botões do toolbar OWA (causava hang de 120s)

```bash
# Teste 5: Deletar sessão e rodar headless (simula expiração)
rm -f ufpr_automation/session_data/state.json
python -m ufpr_automation

# O que observar:
#   ✅ Detecta que não há sessão
#   ✅ Executa auto-login em headless
#   ✅ Envia número MFA via Telegram
#   ✅ Após aprovação, continua pipeline normalmente
```

- [x] Re-login funciona sem janela visível
- [x] MFA notification chega via Telegram mesmo em headless

---

## Marco II — Roteamento Agêntico

### ✅ Concluído

- [x] **Canal Gmail IMAP** (canal primário, substitui OWA para leitura)
  - [x] `gmail/client.py` — GmailClient com App Password (sem MFA, sem Playwright)
  - [x] `list_unread()`, `save_draft()`, `send_reply()`, `mark_read()`
  - [x] Download de anexos via IMAP (`_extract_attachments`)
  - [x] Seleção de canal via `--channel gmail|owa` e `EMAIL_CHANNEL` no `.env`

- [x] **RAG — Base vetorial de documentos institucionais**
  - [x] `rag/ingest.py` — Pipeline: PDF → PyMuPDF → chunks (LangChain) → embeddings (multilingual-e5-large) → LanceDB
  - [x] `rag/retriever.py` — Busca semântica com filtros por conselho/tipo
  - [x] Subset estágio (18 PDFs, 338 chunks) indexado e validado
  - [x] Caminhos configuráveis via `RAG_STORE_DIR` / `RAG_DOCS_DIR` (compartilhado via Google Drive)
  - [x] Integração no pipeline: contexto RAG injetado no prompt do LLM antes da classificação

- [x] **RAPTOR — RAG hierárquico** (Sarthi et al., ICLR 2024)
  - [x] `rag/raptor.py` — Clusterização GMM + sumarização LLM recursiva
  - [x] Collapsed tree retrieval (busca em todos os níveis)
  - [x] Auto-fallback para busca flat se RAPTOR não disponível

- [x] **Self-Refine** (Madaan et al., NeurIPS 2023)
  - [x] `llm/client.py:self_refine_async()` — gerar → criticar → refinar
  - [x] Critérios UFPR-específicos (resolução correta, tom oficial, completude)
  - [x] Max 1 ciclo de refinamento por e-mail

- [x] **Score de confiança + roteamento**
  - [x] Campo `confianca: float` (0.0–1.0) em `EmailClassification`
  - [x] Roteamento por confiança em `graph/nodes.py:rotear()`:
    - ≥ 0.95 → auto-draft (sem revisão humana)
    - ≥ 0.70 → human review (rascunho salvo para aprovação)
    - < 0.70 → escalação manual

- [x] **LangGraph — orquestrador StateGraph**
  - [x] `graph/builder.py` — StateGraph com nós e arestas condicionais
  - [x] `graph/nodes.py` — Nós: perceber → rag_retrieve → classificar → rotear → agir
  - [x] `graph/state.py` — EmailState TypedDict
  - [x] Checkpointing SQLite para tolerância a falhas
  - [x] CLI: `python -m ufpr_automation --channel gmail --langgraph`

- [x] **DSPy — otimização programática de prompts**
  - [x] `dspy_modules/signatures.py` — EmailClassifier, DraftCritic, DraftRefiner
  - [x] `dspy_modules/modules.py` — SelfRefineModule composto
  - [x] `dspy_modules/metrics.py` — Métricas de qualidade (formato, citação, tom)
  - [x] `dspy_modules/optimize.py` — GEPA bootstrap e MIPROv2

- [x] **Reflexion — memória episódica de erros** (Shinn et al., NeurIPS 2023)
  - [x] `feedback/reflexion.py` — ReflexionMemory (gerar análise + armazenar + recuperar)
  - [x] Contexto de erros anteriores injetado como "=== ERROS ANTERIORES ==="
  - [x] Integrado no nó `rag_retrieve` do LangGraph

- [x] **Feedback store — infraestrutura de correções humanas**
  - [x] `feedback/store.py` — FeedbackStore (JSONL append-only)
  - [x] `feedback/cli.py` — CLI para stats e export (`python -m ufpr_automation.feedback stats|export`)

- [x] **Locator fallback chain — resiliência do Playwright**
  - [x] `outlook/locators.py` — Cadeia de fallback: semantic → text → ID → CSS
  - [x] 10 elementos OWA com múltiplas estratégias cada
  - [x] API pública: `find_element()`, `click_element()`, `get_text()`, `wait_for_any()`

- [x] **Model cascading — roteamento de modelos LLM**
  - [x] `llm/router.py` — Router com TaskType (CLASSIFY, DRAFT, CRITIQUE, REFINE)
  - [x] Classificação → modelo local/barato; Drafting → modelo API capaz
  - [x] Fallback automático com retry configurável
  - [x] Configuração via `LLM_CLASSIFY_MODEL`, `LLM_DRAFT_MODEL`, `LLM_FALLBACK_MODEL`

### 🔜 Pendente — Completar Marco II

- [x] **RAPTOR tree** — árvore hierárquica construída (2 níveis, 12 sumários, 34.231 nós totais)
- [x] **OCR para anexos** — PDFs escaneados e imagens (2026-04-07)
  - [x] Detecção automática de PDF escaneado (pouco texto por página) em `attachments/extractor.py`
  - [x] Marcação com `needs_ocr=True` (10+ arquivos no teste e2e)
  - [x] `_ocr_pdf_scanned()` e `_ocr_image()` com Tesseract (por+eng, 300 DPI) em `attachments/extractor.py`
  - [x] OCR integrado ao pipeline de ingestão RAG (`rag/ingest.py --ocr-only`)
  - [x] 70 PDFs escaneados recuperados (404 chunks), 10 irrecuperáveis (7 vazios, 2 corrompidos, 1 ilegível)
  - [x] Cobertura RAG: 3.288/3.316 = 99,2%
- [x] **Feedback loop completo** — conectar store ao pipeline
  - [x] FeedbackStore com `add()`, `list_all()`, `count()` implementados
  - [x] Comando `review` interativo no CLI de feedback (`--approve-all` para batch)
  - [x] Integração: nó `registrar_feedback` no LangGraph grava no FeedbackStore após classificação; `review` CLI gera ReflexionMemory em correções
- [x] **perceber_owa no LangGraph** — implementação completa em `graph/nodes.py`
- [x] **Testes para módulos novos** — 79 testes (graph 19, router 12, reflexion 14, dspy 34)
- [x] **Ingestão completa do RAG** — 3.316 PDFs → 34.285 chunks indexados no LanceDB (2026-04-07)
  - [x] 3.288 documentos indexados com sucesso (99,2%) — 3.218 PyMuPDF + 70 OCR
  - [x] 10 PDFs irrecuperáveis (7 vazios 0 bytes, 2 corrompidos, 1 ilegível)
  - [x] Relatório completo em `RAG_INGESTION_REPORT.md`
  - [x] Store compartilhado via Google Drive (`G:/Meu Drive/ufpr_rag/`)

---

## Marco II.5 — Integração SEI/SIGA + Agendamento + Feedback Web

### ✅ Concluído (2026-04-08)

- [x] **Módulo SEI (Sistema Eletrônico de Informações)**
  - [x] `sei/models.py` — ProcessoSEI, DocumentoSEI, DespachoDraft
  - [x] `sei/browser.py` — Login automático via Playwright (credenciais `.env`)
  - [x] `sei/client.py` — SEIClient: search_process, get_process_status, list_documents
  - [x] Preparação de rascunhos de despacho usando templates SOUL.md seção 14 (TCE, Aditivo, Rescisão)
  - [x] Extração de número de processo SEI e GRR de texto (regex)
  - [x] **Somente leitura** — nenhuma ação submetida automaticamente

- [x] **Módulo SIGA (Sistema Integrado de Gestão Acadêmica)**
  - [x] `siga/models.py` — StudentStatus, EnrollmentInfo, EligibilityResult
  - [x] `siga/browser.py` — Login automático via Playwright (credenciais `.env`)
  - [x] `siga/client.py` — SIGAClient: check_student_status, check_enrollment, validate_internship_eligibility
  - [x] Validação de elegibilidade para estágio conforme SOUL.md seção 11
  - [x] **Somente leitura** — nenhuma ação submetida automaticamente

- [x] **Pipeline LangGraph expandido**
  - [x] Novos nós: `consultar_sei`, `consultar_siga`, `registrar_procedimento`
  - [x] Roteamento condicional: emails de "Estágios" passam por SEI/SIGA antes de agir
  - [x] `graph/state.py` — campos `sei_contexts`, `siga_contexts`, `procedures_logged`
  - [x] `graph/builder.py` — grafo expandido com nós condicionais

- [x] **Registro de procedimentos (aprendizado)**
  - [x] `procedures/store.py` — ProcedureStore (JSONL append-only)
  - [x] ProcedureRecord com steps, duração, outcome, consultas SEI/SIGA
  - [x] Estatísticas: tempo médio, taxa de sucesso, procedimentos por categoria

- [x] **Agendamento automático (3x/dia)**
  - [x] `scheduler.py` — APScheduler com CronTrigger
  - [x] Configurável via `SCHEDULE_HOURS` e `SCHEDULE_TZ` no `.env`
  - [x] CLI: `--schedule` (daemon) e `--schedule --once` (execução única)

- [x] **Interface web de feedback (Streamlit)**
  - [x] `feedback/web.py` — Dashboard, Revisar Classificações, Estatísticas, Procedimentos
  - [x] Aceitar/Corrigir classificações via botões (integrado com FeedbackStore + ReflexionMemory)
  - [x] Visualização de consultas SEI/SIGA e log de procedimentos
  - [x] Gráficos de evolução de acurácia

- [x] **Testes**
  - [x] `test_sei.py` — 16 testes (modelos, extração regex, templates de despacho)
  - [x] `test_siga.py` — 8 testes (modelos, elegibilidade)
  - [x] `test_procedures.py` — 9 testes (store JSONL, estatísticas)
  - [x] `test_scheduler.py` — 6 testes (config, importação)
  - [x] `test_graph_expanded.py` — 8 testes (nós SEI/SIGA, roteamento, procedimentos)

### 🔜 Pendente — Validação Manual

- [ ] Validar login automático no SEI (requer sessão ativa e credenciais reais)
- [ ] Validar login automático no SIGA (requer sessão ativa e credenciais reais)
- [ ] Refinar seletores Playwright do SEI/SIGA após inspeção do DOM real
- [ ] Testar scheduler em produção (executar 1 dia completo)
- [ ] Coletar feedback via interface web e verificar ReflexionMemory

---

## Marco III — Automação Governamental Total

- [ ] LangGraph Fleet com sub-agentes
- [x] **GraphRAG (Neo4j) para hierarquia departamental** — implementado (2026-04-08)
  - [x] `graphrag/client.py` — Neo4j connection manager com health check
  - [x] `graphrag/schema.py` — Constraints, indexes, modelo do grafo (12 tipos de nó, 12 tipos de relação)
  - [x] `graphrag/seed.py` — Seed com conhecimento institucional completo (órgãos, normas, fluxos, templates, papéis, sistemas, SIGA abas, SEI tipos de processo)
  - [x] `graphrag/retriever.py` — Retriever com match de fluxo, normas, templates, hints SIGA, contexto organizacional
  - [x] Integração no LangGraph: `rag_retrieve` combina Vector RAG + GraphRAG + Reflexion
  - [x] 43 testes (schema 3, client 6, retriever 20, seed 12, integração 2)
  - [x] Dependência `neo4j>=5.20.0` em `[marco3]` extra, config `NEO4J_*` em settings.py
- [ ] AFlow — otimização automática de topologia do grafo
- [ ] Protocolar processos no SEI via Playwright (atualmente somente leitura)
- [ ] Preencher formulários no SIGA via Playwright (atualmente somente leitura)
- [ ] Extrair trâmites em lote
- [ ] Model cascading local (Ollama/Qwen3-8B) — infraestrutura pronta, aguardando setup