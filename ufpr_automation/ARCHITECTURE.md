# Arquitetura — Sistema de Automação Burocrática UFPR

> **Status atual:** Marcos I, II e II.5 ✅ completos. Marco III parcial (GraphRAG ✅, demais pendentes).
> Veja `TASKS.md` para o roadmap restante.

## Visão geral das 3 fases

```mermaid
graph TB
    subgraph LEGEND["🔑 Legenda"]
        direction LR
        L1["🟢 Marco I — Protótipo"]
        L2["🟡 Marco II — Intermediário"]
        L3["🔴 Marco III — Avançado"]
    end

    subgraph PHASE1["🟢 MARCO I — Ingestão Assistida ✅"]
        direction TB
        NANOBOT["🐈 Nanobot Loop<br/>Perceber → Pensar → Agir"]
        BROWSER1["🌐 Playwright (headless)<br/>+ Auto-Login + MFA Telegram"]
        OWA1["📧 OWA / Gmail IMAP<br/>(canais primário e fallback)"]
        EXTRACT1["📋 Extração + Anexos<br/>(PDF/DOCX/XLSX/OCR)"]
        LLM1["🧠 LiteLLM → MiniMax<br/>+ ICL via SOUL.md"]
        DRAFT1["✍️ Rascunho salvo<br/>(human-in-the-loop)"]

        NANOBOT --> BROWSER1 --> OWA1 --> EXTRACT1 --> LLM1 --> DRAFT1
    end

    subgraph PHASE2["🟡 MARCO II — Roteamento Agêntico ✅"]
        direction TB
        LANGGRAPH2["🔀 LangGraph StateGraph<br/>+ SQLite Checkpointing"]
        VECTORDB["🗄️ LanceDB (34K chunks)<br/>+ RAPTOR hierárquico"]
        DSPY["📐 DSPy + Self-Refine<br/>+ Reflexion (memória de erros)"]
        ROUTER["🏷️ Roteamento por Confiança<br/>auto / review / escalação"]
        CASCADE["⚙️ Model Cascading<br/>local + API + fallback"]

        LANGGRAPH2 --> ROUTER --> VECTORDB
        LANGGRAPH2 --> DSPY --> CASCADE
    end

    subgraph PHASE3["🔴 MARCO III — Cognição Relacional ⚙️"]
        direction TB
        NEO4J["🕸️ Neo4j (1.757 nós, 2.296 rels) ✅<br/>Hierarquia + Normas + Fluxos"]
        SEI_M["📁 SEI Client (read-only) ✅<br/>Playwright + templates SOUL"]
        SIGA_M["🎓 SIGA Client (read-only) ✅<br/>Playwright + elegibilidade"]
        FLEET["🚀 LangGraph Fleet<br/>(sub-agentes paralelos)<br/>⏳ pendente"]

        NEO4J --> SEI_M
        NEO4J --> SIGA_M
        NEO4J --> FLEET
    end

    PHASE1 ==>|"Evolução"| PHASE2
    PHASE2 ==>|"Evolução"| PHASE3

    style PHASE1 fill:#e8f5e9,stroke:#4caf50,stroke-width:3px
    style PHASE2 fill:#fff9c4,stroke:#ffc107,stroke-width:3px
    style PHASE3 fill:#ffebee,stroke:#f44336,stroke-width:3px
    style LEGEND fill:#f5f5f5,stroke:#9e9e9e,stroke-width:1px
```

## Stack por componente

| Componente | Tecnologia | Notas |
|---|---|---|
| **Linguagem** | Python ≥ 3.12 | |
| **Orquestrador** | LangGraph (Marco II+) / Nanobot loop (Marco I) | StateGraph + SQLite checkpointing |
| **LLM** | LiteLLM → MiniMax-M2 | Provider-agnostic. Cascading: local/Ollama → API → fallback |
| **Memória vetorial** | LanceDB + RAPTOR | 34.285 chunks, multilingual-e5-large (1024 dim), Google Drive |
| **Memória relacional** | Neo4j | 1.757 nós, 2.296 relações (órgãos, normas, fluxos, templates) |
| **Otimização de prompts** | DSPy (GEPA / MIPROv2) | Signatures + métricas customizadas |
| **Episódica** | ReflexionMemory | Análise + recall de erros passados |
| **Canal e-mail** | Gmail IMAP (primário) / Playwright OWA (fallback) | Auto-login + MFA via Telegram (OWA) |
| **Sistemas legados** | Playwright (SEI, SIGA) | Read-only por enquanto |
| **Anexos** | PyMuPDF, python-docx, openpyxl, Tesseract | OCR fallback para PDFs escaneados/imagens |
| **Scheduler** | APScheduler (3x/dia configurável) | `--schedule [--once]` |
| **Feedback UI** | Streamlit | Dashboard, revisão, estatísticas |

## Pipeline LangGraph (Marco II+)

```mermaid
graph LR
    PERCEBER[perceber<br/>Gmail/OWA + anexos] --> RAG[rag_retrieve<br/>RAPTOR + GraphRAG + Reflexion]
    RAG --> CLASSIFY[classificar<br/>DSPy SelfRefine]
    CLASSIFY --> ROUTE{rotear<br/>por confiança}
    ROUTE -->|≥ 0.95| AGIR_AUTO[agir auto]
    ROUTE -->|≥ 0.70| AGIR_REVIEW[agir review]
    ROUTE -->|< 0.70| ESCALAR[escalar]
    ROUTE -->|categoria=Estágios| SEI[consultar_sei]
    SEI --> SIGA[consultar_siga]
    SIGA --> AGIR_REVIEW
    AGIR_AUTO --> REGISTRAR[registrar_procedimento]
    AGIR_REVIEW --> REGISTRAR
    ESCALAR --> REGISTRAR
    REGISTRAR --> FEEDBACK[registrar_feedback]
```

## RAG — Pipeline de ingestão e busca

```mermaid
graph LR
    subgraph INGEST["📥 Ingestão"]
        PDF["📄 3.316 PDFs"]
        EXTRACT["📝 PyMuPDF + Tesseract OCR"]
        CHUNK["✂️ LangChain Splitter<br/>(separadores legais PT-BR)"]
        EMBED["🧮 multilingual-e5-large<br/>1024 dim"]
        STORE["🗄️ LanceDB<br/>(ufpr_docs + ufpr_raptor)"]
        PDF --> EXTRACT --> CHUNK --> EMBED --> STORE
    end

    subgraph RETRIEVE["🔍 Busca"]
        QUERY["❓ Query PT-BR"]
        QEMBED["🧮 query: prefix"]
        SEARCH["🔎 cosine sim<br/>+ filtros (conselho, tipo)"]
        RESULTS["📋 Top-K + Score"]
        QUERY --> QEMBED --> SEARCH --> RESULTS
    end

    STORE -.-> SEARCH

    style INGEST fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style RETRIEVE fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

**Cobertura:** 99,2% (3.288/3.316 PDFs, 70 recuperados via OCR). Detalhes em `RAG_INGESTION_REPORT.md`.

## GraphRAG (Marco III)

Grafo Neo4j construído via `seed.py` (conhecimento estruturado: hierarquia, fluxos, templates) e `enrich.py` (extração de normas do RAG vetorial via regex):

| Tipo de nó | Quantidade | Origem |
|---|---|---|
| Órgãos | 21 | seed (SOUL.md) |
| Pessoas | 12 | seed |
| Normas | ~1.600 | enrich (extraídas dos PDFs) |
| Fluxos | 6 (47 etapas) | seed |
| Templates | 15 | seed (ClaudeCowork) |
| Tipos de processo SEI | 20 | seed |
| Abas SIGA | 8 | seed |

**Vigência:** cada norma tem `status` (`vigente` 1.281 / `alterada` 174 / `revogada` 148). Relações `ALTERA`, `REVOGA`, `CONSOLIDADA_EM` formam a cadeia de linhagem. `fonte_rag` aponta para o PDF original no LanceDB.

**Retrieval:** o nó `rag_retrieve` do LangGraph combina:
1. `RaptorRetriever.search()` — collapsed-tree vetorial
2. `GraphRetriever` — workflow + normas + templates + hints SIGA + contatos
3. `ReflexionMemory.retrieve()` — erros passados como contexto negativo

Ver `graphrag/README.md` para detalhes.
