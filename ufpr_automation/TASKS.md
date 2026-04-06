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

## Marco II — Roteamento Agêntico (Futuro)

- [ ] **OCR para anexos** — PDFs escaneados e imagens (Tesseract/EasyOCR)
  - [ ] Detecção automática de PDF escaneado (pouco texto por página)
  - [ ] `ocr_image()` e `ocr_pdf_scanned()` em `attachments/extractor.py`
- [ ] Migrar orquestrador para LangGraph
- [ ] Implementar Vector RAG (LanceDB/Chroma) para portarias e memorandos
- [ ] Roteamento condicional: auto-envio para risco baixo
- [ ] Tratamento de exceções (mudança de layout OWA)

## Marco III — Automação Governamental Total (Futuro)

- [ ] LangGraph Fleet com sub-agentes
- [ ] GraphRAG (Neo4j) para hierarquia departamental
- [ ] Integração com SIGA-UFPR via Playwright
- [ ] Integração com SEI via Playwright
- [ ] Protocolar processos e extrair trâmites em lote