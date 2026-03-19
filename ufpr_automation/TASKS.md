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
  - [x] Aguardar login manual (5 min timeout)
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

### 🔜 Pendente

- [ ] **Validação de seletores Playwright**
  - [ ] Testar `body_extractor.py` com sessão OWA real (`--perceber-only`)
  - [ ] Testar `responder.py` com sessão OWA real (rascunho manual)

- [ ] **Testes**
  - [ ] Testes unitários para `core/models.py`
  - [ ] Testes de integração para `outlook/scraper.py` (mock)
  - [ ] Teste end-to-end do fluxo completo

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