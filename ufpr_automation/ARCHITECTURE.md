# Sistema de Automação Burocrática da UFPR — Diagrama de Arquitetura

## Visão Geral das 3 Fases de Maturidade

```mermaid
graph TB
    subgraph LEGEND["🔑 Legenda"]
        direction LR
        L1["🟢 Marco I — Protótipo"]
        L2["🟡 Marco II — Intermediário"]
        L3["🔴 Marco III — Avançado"]
    end

    subgraph PHASE1["🟢 MARCO I — Ingestão Assistida (Protótipo)"]
        direction TB

        subgraph P1_ORQUESTRADOR["Orquestrador"]
            NANOBOT["🐈 Nanobot Framework<br/>Loop: Perceber → Pensar → Agir"]
        end

        subgraph P1_PERCEPCAO["Perceber (Playwright RPA)"]
            BROWSER1["🌐 Playwright (Headless)<br/>Browser Context + Session State"]
            AUTOLOGIN["🤖 Auto-Login<br/>Credenciais .env + MFA via Telegram"]
            OWA1["📧 Outlook Web Access (OWA)<br/>UFPR Microsoft 365"]
            AUTOLOGIN -->|"E-mail + Senha + MFA"| OWA1
            BROWSER1 -->|"Web Scraping DOM"| OWA1
            OWA1 -->|"E-mails não lidos:<br/>remetente, assunto, corpo, anexos"| EXTRACT1["📋 Extração de Dados<br/>+ Download de Anexos"]
        end

        subgraph P1_COGNICAO["Pensar (LiteLLM + MiniMax)"]
            LLM1["🧠 LiteLLM → MiniMax API"]
            ICL["📝 In-Context Learning<br/>Normas UFPR no System Prompt"]
            EXTRACT1 -->|"Conteúdo do e-mail<br/>+ texto dos anexos"| LLM1
            ICL -->|"Contexto institucional"| LLM1
            LLM1 -->|"Classificação + Resposta"| DRAFT1["✍️ Ofício / Resposta Gerada"]
        end

        subgraph P1_ACAO["Agir (Human-in-the-Loop)"]
            DRAFT1 -->|"Texto formatado"| REPLY1["🖱️ Playwright: Responder"]
            REPLY1 -->|"Salvar como Rascunho"| DRAFTS1["📂 Pasta Rascunhos"]
            DRAFTS1 -->|"Aguarda validação"| HUMAN1["👤 Revisão Humana"]
            HUMAN1 -->|"Aprovado → Enviar"| SEND1["📤 Envio Manual"]
        end

        NANOBOT --> P1_PERCEPCAO
        NANOBOT --> P1_COGNICAO
        NANOBOT --> P1_ACAO
    end

    subgraph PHASE2["🟡 MARCO II — Roteamento Agêntico (Intermediário)"]
        direction TB

        subgraph P2_ORQUESTRADOR["Orquestrador"]
            LANGGRAPH2["🔀 LangGraph<br/>Workflows Multi-Agentes<br/>Grafos de Estado"]
        end

        subgraph P2_MEMORIA["Memória (Vector RAG)"]
            VECTORDB["🗄️ LanceDB / Chroma<br/>Banco Vetorial Local"]
            PORTARIAS["📜 Portarias e Memorandos<br/>Indexados por Embedding"]
            VECTORDB --- PORTARIAS
        end

        subgraph P2_ROTEAMENTO["Roteamento Condicional"]
            CLASSIFIER2["🏷️ Classificador de Risco"]
            CLASSIFIER2 -->|"Risco Baixo"| AUTO2["🤖 Resposta Automática<br/>(Envio direto)"]
            CLASSIFIER2 -->|"Risco Alto"| RAG2["🔍 Retrieval Node<br/>Busca na base vetorial"]
            RAG2 --> HUMAN2["👤 Revisão Humana"]
        end

        subgraph P2_EXCECAO["Tratamento de Exceções"]
            LAYOUT_CHANGE["⚠️ Mudança de Layout OWA"]
            SCRAPER_FAIL["❌ Falha no Scraper"]
            LAYOUT_CHANGE --> SCRAPER_FAIL
            SCRAPER_FAIL -->|"Nó de recuperação"| RECOVERY2["🔄 Recovery Node"]
        end

        LANGGRAPH2 --> P2_ROTEAMENTO
        LANGGRAPH2 --> P2_MEMORIA
        LANGGRAPH2 --> P2_EXCECAO
    end

    subgraph PHASE3["🔴 MARCO III — Automação Governamental Total (Avançado)"]
        direction TB

        subgraph P3_ORQUESTRADOR["Orquestrador"]
            LANGGRAPH3["🔀 LangGraph Fleet<br/>Frota de Sub-Agentes"]
        end

        subgraph P3_MEMORIA["Memória (GraphRAG)"]
            NEO4J["🕸️ Neo4j<br/>Grafo de Conhecimento"]
            HIERARQUIA["🏛️ Hierarquia Departamental<br/>Relações Normativas"]
            NEO4J --- HIERARQUIA
        end

        subgraph P3_SISTEMAS["Sistemas Legados (Expansão)"]
            AGENT_SIGA["🤖 Agente SIGA-UFPR<br/>Gestão Acadêmica"]
            AGENT_SEI["🤖 Agente SEI<br/>Sistema Eletrônico de Informações"]
            AGENT_EMAIL["🤖 Agente Outlook<br/>Webmail"]

            AGENT_SIGA -->|"Playwright"| SIGA["🖥️ Portal SIGA Web"]
            AGENT_SEI -->|"Playwright"| SEI["🖥️ Portal SEI Web"]
            AGENT_EMAIL -->|"Playwright"| OWA3["📧 Outlook Web"]

            SIGA -->|"Protocolar processos<br/>Preencher formulários"| TRAMITE["📋 Números de Trâmite"]
            SEI -->|"Extração em lote"| TRAMITE
            TRAMITE -->|"Resposta ao requerente"| OWA3
        end

        LANGGRAPH3 --> P3_SISTEMAS
        LANGGRAPH3 --> P3_MEMORIA
    end

    PHASE1 ==>|"Evolução"| PHASE2
    PHASE2 ==>|"Evolução"| PHASE3

    style PHASE1 fill:#e8f5e9,stroke:#4caf50,stroke-width:3px
    style PHASE2 fill:#fff9c4,stroke:#ffc107,stroke-width:3px
    style PHASE3 fill:#ffebee,stroke:#f44336,stroke-width:3px
    style LEGEND fill:#f5f5f5,stroke:#9e9e9e,stroke-width:1px
```

## Módulo RAG — Vector Store (Marco II, Fase Inicial)

```mermaid
graph LR
    subgraph INGEST["📥 Pipeline de Ingestão"]
        PDF["📄 PDFs<br/>(3.316 documentos)"]
        EXTRACT["📝 PyMuPDF<br/>Extração de Texto"]
        CHUNK["✂️ LangChain Splitter<br/>Chunking Semântico"]
        EMBED["🧮 multilingual-e5-large<br/>Embeddings (1024 dim)"]
        STORE["🗄️ LanceDB<br/>Vector Store Local"]

        PDF --> EXTRACT --> CHUNK --> EMBED --> STORE
    end

    subgraph RETRIEVE["🔍 Pipeline de Busca"]
        QUERY["❓ Query (PT-BR)"]
        QEMBED["🧮 query: prefix<br/>Embedding"]
        SEARCH["🔎 Busca Vetorial<br/>+ Filtros Metadata"]
        RESULTS["📋 Top-K Resultados<br/>com Score + Fonte"]

        QUERY --> QEMBED --> SEARCH --> RESULTS
    end

    STORE -.->|"cosine similarity"| SEARCH

    style INGEST fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style RETRIEVE fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

### Estrutura do Corpus

| Conselho | Atas | Resoluções | Instruções Normativas |
|----------|------|------------|----------------------|
| CEPE     | 731  | 648        | 8                    |
| COPLAD   | 630  | 474        | 1                    |
| COUN     | 217  | 435        | 1                    |
| CONCUR   | 143  | 10         | —                    |
| Estágio  | —    | —          | 18 (manuais, leis)   |

### Estatísticas da Ingestão (2026-04-07, com OCR)

| Métrica              | Valor   |
|----------------------|---------|
| PDFs processados     | 3.316   |
| PDFs indexados       | 3.288   |
| — via PyMuPDF        | 3.218   |
| — via OCR (Tesseract)| 70      |
| Chunks gerados       | 34.285  |
| PDFs irrecuperáveis  | 10      |
| Cobertura            | 99,2%   |

Relatório completo: [`RAG_INGESTION_REPORT.md`](RAG_INGESTION_REPORT.md)

### Pacote `ufpr_automation/rag/`

- **`ingest.py`** — Pipeline de ingestão: PDF → texto (PyMuPDF) → chunks (LangChain RecursiveCharacterTextSplitter com separadores para documentos legais PT-BR) → embeddings (E5 multilingual) → LanceDB. Suporta `--subset`, `--dry-run`, skip de arquivos já indexados (idempotente).
- **`retriever.py`** — Busca vetorial semântica com filtros por `conselho` e `tipo`. Retorna `SearchResult` com texto, score, metadados. Método `search_formatted()` gera contexto pronto para injeção no system prompt do LLM.
- **`raptor.py`** — Indexação hierárquica RAPTOR (GMM clustering + sumarização recursiva). Collapsed tree retrieval busca em todos os níveis.
- **`store/`** — Diretório do LanceDB. Compartilhado via Google Drive (`RAG_STORE_DIR` em `.env`). Não versionado no git.

## Stack Tecnológica por Fase

| Componente        | Marco I (Protótipo)         | Marco II (Intermediário)     | Marco III (Avançado)          |
|-------------------|-----------------------------|------------------------------|-------------------------------|
| **Linguagem**     | Python                      | Python                       | Python                        |
| **Orquestrador**  | Nanobot (loop nativo)       | LangGraph                    | LangGraph (Fleet)             |
| **Motor Cognitivo** | LiteLLM → MiniMax (RAG + Self-Refine) | LiteLLM → MiniMax (DSPy) | LiteLLM → MiniMax (GraphRAG)  |
| **Memória**       | LanceDB (Vetorial) + SOUL.md | LanceDB + RAPTOR (Hierárquico) | Neo4j (Grafo de Conhecimento) |
| **Interface I/O** | Gmail API (IMAP) / Playwright OWA | Gmail API / Playwright OWA | Gmail + SIGA + SEI |
| **Autonomia**     | Rascunho + Revisão Humana   | Auto (baixo risco) + Humano  | Totalmente autônomo           |
| **Autenticação**  | Auto-login + MFA Telegram   | Auto-login + MFA Telegram    | Auto-login + MFA Telegram     |
| **Tratamento Erro** | Logs no terminal          | Recovery nodes (LangGraph)   | Auto-healing + alertas        |

## Fluxo de Dados — Marco I (Detalhado)

```mermaid
sequenceDiagram
    participant C as ⏰ Cron / Manual
    participant N as 🐈 Nanobot Loop
    participant P as 🌐 Playwright
    participant O as 📧 OWA (UFPR)
    participant M as 🔐 Microsoft Login
    participant T as 📲 Telegram Bot
    participant G as 🧠 LiteLLM (MiniMax)
    participant H as 👤 Humano

    C->>N: Trigger ciclo
    N->>P: Abrir browser (headless)
    P->>O: Navegar → Caixa de Entrada

    alt Sessão expirada ou primeiro uso
        P->>M: Preencher e-mail + senha (.env)
        M-->>P: Desafio MFA (number matching)
        P->>P: Extrair número de 2 dígitos
        P->>T: Enviar número MFA
        T->>H: 📲 "Número MFA: 42"
        H->>M: Aprovar no Authenticator (celular)
        M-->>P: Login concluído
        P->>P: Salvar sessão (cookies + storage)
    end

    O-->>P: DOM carregado
    P->>P: Extrair e-mails não lidos<br/>(remetente, assunto, corpo)
    P-->>N: Lista de e-mails

    loop Para cada e-mail
        N->>G: Enviar conteúdo + System Prompt (normas UFPR)
        G-->>N: Classificação + Resposta redigida
        N->>P: Clicar "Responder" no e-mail
        P->>O: Digitar resposta gerada
        P->>O: Salvar como Rascunho (NÃO enviar)
        O-->>P: Rascunho salvo ✅
    end

    P-->>N: Ciclo concluído
    N->>H: 🔔 Alerta: ações aguardam revisão
    H->>O: Revisar rascunhos → Enviar manualmente
```
