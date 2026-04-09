# TASKS — Roadmap

> Para o histórico completo de tarefas executadas (Marcos I/II/II.5/III), consulte `git log` ou versões anteriores deste arquivo.

## Status atual

| Marco | Status | Resumo |
|---|---|---|
| **Marco I** — Protótipo | ✅ | Pipeline Perceber→Pensar→Agir, OWA Playwright + Gmail IMAP, auto-login MFA, anexos (PDF/DOCX/XLSX), salva como rascunho |
| **Marco II** — Roteamento Agêntico | ✅ | LangGraph StateGraph, RAG (LanceDB + RAPTOR), Self-Refine, DSPy, Reflexion, Locator chain, Model cascading |
| **Marco II.5** — SEI/SIGA + Scheduler | ✅ | Módulos SEI/SIGA (read-only, Playwright), pipeline expandido, ProcedureStore, scheduler (3x/dia), Streamlit feedback UI |
| **Marco III** — Cognição Relacional | ⚙️ | GraphRAG/Neo4j ✅ implementado (1.757 nós, 2.296 rels). Demais itens pendentes (LangGraph Fleet, AFlow, write em SEI/SIGA) |

**Testes:** ~160 passando (`pytest ufpr_automation/tests/ -v`)
**RAG:** 34.285 chunks (3.288/3.316 PDFs, 99,2% via PyMuPDF + OCR Tesseract)

## Pendente

### Validação manual em produção (Marco II.5)
- [ ] Validar login automático no SEI com sessão ativa e credenciais reais
- [ ] Validar login automático no SIGA com sessão ativa e credenciais reais
- [ ] Refinar seletores Playwright SEI/SIGA após inspeção do DOM real
- [ ] Rodar scheduler 1 dia completo em produção
- [ ] Coletar feedback via Streamlit e verificar ReflexionMemory

### Marco III — itens restantes
- [ ] LangGraph Fleet com sub-agentes paralelos
- [ ] AFlow — otimização automática de topologia do grafo
- [ ] Protocolar processos no SEI via Playwright (atualmente read-only)
- [ ] Preencher formulários no SIGA via Playwright (atualmente read-only)
- [ ] Extrair trâmites em lote
- [ ] Habilitar model cascading local com Ollama/Qwen3-8B (infra pronta, falta setup)
