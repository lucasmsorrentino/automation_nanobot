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

### 🔜 Pendente

- [x] **Integração com Gemini (Pensar)**
  - [x] Criar módulo `llm/` com cliente Gemini (via nanobot provider)
  - [x] System prompt com normas da UFPR (ICL do `SOUL.md`)
  - [x] Classificação de e-mails: departamento, urgência, tipo
  - [x] Geração de resposta/ofício conforme normas

- [ ] **Ação no OWA (Agir)**
  - [ ] Criar módulo `outlook/responder.py`
  - [ ] Clicar em "Responder" no e-mail via Playwright
  - [ ] Digitar resposta gerada pelo LLM
  - [ ] Salvar como rascunho (NUNCA enviar automaticamente)

- [ ] **Notificação (Notificar)**
  - [ ] Expandir alertas além do terminal (e.g., log file, webhook)
  - [ ] Relatório de ações pendentes para revisão humana

- [ ] **Preencher SOUL.md**
  - [ ] Inserir normas reais da UFPR
  - [ ] Modelos de ofício do setor
  - [ ] Resoluções do CEPE relevantes
  - [ ] Regras específicas do departamento

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