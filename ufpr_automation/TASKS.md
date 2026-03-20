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
  - [x] `config.json` — Provider Gemini

- [x] **Integração com Gemini (Pensar)**
  - [x] Criar módulo `llm/` com cliente Gemini (via nanobot provider)
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
  - [x] `agents/pensar.py` — PensarAgent com chamadas Gemini **concorrentes**
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
  - [x] Evitar exaustão de quota Gemini com muitos e-mails não lidos

- [x] **4. Substituir hard-coded `wait_for_timeout()` por waits adaptativos**
  - [x] Usar `wait_for_selector()` / `expect()` do Playwright onde possível
  - [x] Manter timeouts apenas como fallback com valores configuráveis

- [x] **5. Validação de `categoria` com Literal enum**
  - [x] Trocar `str` por `Literal[...]` em `EmailClassification.categoria`
  - [x] Garantir que LLM só retorna categorias válidas via schema

- [x] **6. Testes unitários mínimos**
  - [x] Testes para `core/models.py` (EmailData, EmailClassification)
  - [x] Testes para `llm/client.py` (mock Gemini, validar schema)
  - [x] Teste end-to-end do pipeline com dados mock

- [x] **7. Logging persistente (structured)**
  - [x] Adicionar logging estruturado (JSON) para arquivo em `logs/`
  - [x] Substituir `print()` por `logger.info()` nos módulos principais

### 🔜 Pendente — Validação Manual (requer sessão OWA)

- [ ] **Validação de seletores Playwright**
  - [ ] Testar `body_extractor.py` com sessão OWA real (`--perceber-only`)
  - [ ] Testar `responder.py` com sessão OWA real (rascunho manual)
  - [ ] Pipeline completo end-to-end com e-mails reais
- [ ] **Validação do login automático**
  - [ ] Testar auto-login com credenciais reais (preenchimento e-mail + senha)
  - [ ] Testar extração do número MFA da página Microsoft
  - [ ] Testar notificação Telegram com número MFA
  - [ ] Testar re-login automático após expiração de sessão

---

## Marco II — Roteamento Agêntico (Futuro)

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