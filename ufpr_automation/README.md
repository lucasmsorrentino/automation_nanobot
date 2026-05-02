# 🤖 UFPR Automation

> Sistema de automação burocrática da Universidade Federal do Paraná. Lê e-mails institucionais, classifica via LLM, recupera contexto de normas (RAG vetorial + grafo Neo4j) e gera respostas como rascunho para revisão humana.

![Python](https://img.shields.io/badge/python-≥3.12-blue)
![Stack](https://img.shields.io/badge/stack-LangGraph%20Fleet%20%2B%20DSPy%20%2B%20RAPTOR%20%2B%20Neo4j%20%2B%20AFlow-violet)
![Status](https://img.shields.io/badge/Marcos%20I%2BII%2BII.5%2BIII%2BV-✅-green)
![Marco IV](https://img.shields.io/badge/Marco%20IV-🟡%20em%20andamento-yellow)

## Sobre

Pipeline `Perceber → Pensar → Agir` orquestrado por **LangGraph**, alimentado por uma base vetorial de **34.285 chunks** de resoluções, atas e instruções normativas da UFPR (LanceDB + RAPTOR), enriquecida por um **grafo de conhecimento Neo4j** com 1.757 nós (hierarquia departamental, normas, fluxos, templates).

O sistema **nunca envia e-mails automaticamente** — sempre salva como rascunho para revisão humana.

> **Por que RPA via Playwright para OWA?** A governança de TI da UFPR bloqueia o registro de aplicativos para a Microsoft Graph API. O canal **Gmail IMAP** é o primário (forwarding do OWA). O canal OWA via Playwright existe como fallback.

## Arquitetura

| Camada | Componentes |
|---|---|
| **Canais** | `gmail/` (IMAP, primário) · `outlook/` (Playwright + auto-login + MFA Telegram, fallback) |
| **Anexos** | `attachments/` — PDF (PyMuPDF), DOCX, XLSX, OCR Tesseract para escaneados |
| **Memória vetorial** | `rag/` — LanceDB + RAPTOR hierárquico, multilingual-e5-large, 34K chunks |
| **Memória relacional** | `graphrag/` — Neo4j, 1.757 nós, normas com vigência (vigente/alterada/revogada). `templates.py` (TemplateRegistry) serve despachos a partir do grafo. |
| **Memória episódica** | `feedback/reflexion.py` — análise + recall de erros passados |
| **Memória híbrida (Tier 0)** | `procedures/playbook.py` + `workspace/PROCEDURES.md` — playbook YAML curto-circuita RAG/LLM em emails reconhecidos |
| **LLM** | `llm/` — LiteLLM → MiniMax-M2, Self-Refine, model cascading (local/API/fallback). DSPy via `USE_DSPY=auto` (ativa quando há prompt compilado) |
| **Otimização** | `dspy_modules/` — DSPy Signatures, GEPA / MIPROv2; gate `_should_use_dspy()` em `graph/nodes.py` |
| **Orquestrador** | `graph/` — LangGraph StateGraph + SQLite checkpointing. **`fleet.py`** paraleliza Tier 1 via `Send` API + reducers `Annotated[..., _merge_dict]`. **`browser_pool.py`** compartilha pages Playwright. |
| **Topology evaluator** | `aflow/` — 5 topologias hand-authored (baseline, fleet, ablations) + evaluator + CLI. Selecionável via `AFLOW_TOPOLOGY`. |
| **Sistemas legados (read)** | `sei/client.py`, `siga/client.py` — Playwright, read-only |
| **SEI write ops** | `sei/writer.py` — `SEIWriter` com APENAS `attach_document` + `save_despacho_draft`. **Sem** `sign()`/`send()`/`protocol()` (safety arquitetural + 6 testes regressivos + `_FORBIDDEN_SELECTORS` runtime guard). |
| **Procedimentos** | `procedures/store.py` — log JSONL para aprendizado contínuo |
| **Scheduler** | `scheduler.py` — APScheduler 3x/dia (configurável) |
| **Feedback UI** | `feedback/web.py` — Streamlit dashboard |
| **Persona/ICL** | `workspace/SOUL.md` (full) + `workspace/SOUL_ESSENTIALS.md` (slim system prompt) + `workspace/PROCEDURES.md` (Tier 0 intents) |

Diagramas Mermaid completos em [`ARCHITECTURE.md`](ARCHITECTURE.md). Roadmap em [`TASKS.md`](TASKS.md).

## Quickstart

```bash
# 1. Instalar (na raiz do nanobot)
pip install -e ".[rag,marco2,marco3]"

# 2. Configurar credenciais
cp ufpr_automation/.env.example ufpr_automation/.env
# editar .env: GMAIL_*, MINIMAX_API_KEY, NEO4J_*, RAG_STORE_DIR, ...

# 3. Rodar pipeline (Gmail IMAP + LangGraph)
python -m ufpr_automation --channel gmail --langgraph

# 4. Ou rodar via scheduler (3x/dia)
python -m ufpr_automation --schedule
```

## CLI

| Comando | Descrição |
|---|---|
| `python -m ufpr_automation` | Pipeline (canal definido por `EMAIL_CHANNEL` no `.env`) |
| `python -m ufpr_automation --channel gmail --langgraph` | Pipeline LangGraph com Gmail IMAP |
| `python -m ufpr_automation --channel owa --headed --debug` | OWA Playwright visível com captura de DOM |
| `python -m ufpr_automation --perceber-only` | Apenas scraping, sem LLM (OWA only) |
| `python -m ufpr_automation --schedule [--once]` | Scheduler daemon (`--once` para rodar 1 vez) |

### RAG

```bash
# Ingerir documentos (PDF → chunks → embeddings → LanceDB)
python -m ufpr_automation.rag.ingest [--subset estagio | --dry-run | --ocr-only]

# Construir RAPTOR hierárquico
python -m ufpr_automation.rag.raptor [--max-levels 3]

# Buscar via CLI
python -m ufpr_automation.rag.retriever "prazo de estágio obrigatório" --conselho cepe --top-k 5

# REPL interativo
python -m ufpr_automation.rag.chat [--conselho cepe]

# Web UI (Streamlit, porta 8501)
streamlit run ufpr_automation/rag/web.py
```

### GraphRAG (Neo4j)

```bash
# Pré-requisito: Neo4j rodando em bolt://localhost:7687
docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/ufpr2026 neo4j:5

python -m ufpr_automation.graphrag.seed              # popular base
```

### Feedback / DSPy

```bash
# Stats e revisão
python -m ufpr_automation.feedback stats
python -m ufpr_automation.feedback review

# Web UI (porta 8502)
streamlit run ufpr_automation/feedback/web.py

# Otimizar prompts
python -m ufpr_automation.dspy_modules.optimize --strategy gepa  # bootstrap (synthetic ok)
python -m ufpr_automation.dspy_modules.optimize --strategy mipro # 20+ feedback exemplos
python -m ufpr_automation.dspy_modules.optimize --evaluate-only

# Após gerar gepa_optimized.json, USE_DSPY=auto ativa o classifier DSPy automaticamente
USE_DSPY=auto python -m ufpr_automation --channel gmail --limit 5
USE_DSPY=off  python -m ufpr_automation --channel gmail   # força LiteLLM
USE_DSPY=on   python -m ufpr_automation --channel gmail   # exige prompt compilado
```

### LangGraph Fleet (Marco III)

```bash
# Default já é Fleet — paraleliza rag_retrieve + classificar + consultar_sei/siga
python -m ufpr_automation --channel gmail --limit 10

# Pool de Playwright pages compartilhado entre sub-agents
FLEET_BROWSER_POOL_SIZE=5 python -m ufpr_automation --channel gmail

# Pre-warm de sessões SEI/SIGA antes do fan-out
#   Roda uma vez, sequencial, entre tier0_lookup e dispatch_tier1. Se o
#   storage_state.json de SEI ou SIGA estiver mais velho que MAX_AGE_H,
#   faz auto_login agora — assim os N sub-agentes paralelos que rodam
#   depois encontram sessão fresca e ninguém precisa logar. Evita race
#   de N logins simultâneos sobrescrevendo o mesmo storage_state.
#   Default OFF: ligar só quando batch grande em prod mostrar a race.
#   Skip automático se nenhum email menciona SEI/GRR/23075.
PREWARM_SESSIONS_ENABLED=true python -m ufpr_automation --channel gmail
PREWARM_SESSIONS_MAX_AGE_H=4 python -m ufpr_automation --channel gmail
```

### AFlow — topology evaluator (Marco III)

```bash
# Avaliar todas as 5 topologias contra o feedback set (ou synthetic se vazio)
python -m ufpr_automation.aflow.cli --topologies all --limit 20

# Avaliar apenas baseline vs fleet
python -m ufpr_automation.aflow.cli --topologies baseline,fleet --limit 10

# Forçar topologia específica em runtime
AFLOW_TOPOLOGY=baseline python -m ufpr_automation --channel gmail
AFLOW_TOPOLOGY=fleet    python -m ufpr_automation --channel gmail   # default
```

### SEI write ops (Marco III + Marco IV)

```python
# Marco IV expandiu a API pública para 3 métodos:
#   - create_process       (iniciar processo SEI novo)
#   - attach_document      (anexar documento Externo com classificação)
#   - save_despacho_draft  (lavrar Despacho no editor rich-text)
# NUNCA existem métodos sign/send/protocol/finalize.
from ufpr_automation.sei.writer import SEIWriter
from ufpr_automation.sei.writer_models import SEIDocClassification

# Verificar API pública
python -c "from ufpr_automation.sei.writer import SEIWriter; print([m for m in dir(SEIWriter) if not m.startswith('_')])"
```

**Modo dry-run (Marco IV, default)**: as três operações capturam screenshots + audit mas **não clicam em nada no SEI**. Setado via `SEI_WRITE_MODE=dry_run` no `.env` (ou omitido). Use dry-run para validar a lógica de `agir_estagios` contra emails reais sem risco. Para habilitar `SEI_WRITE_MODE=live`, os seletores Playwright precisam ser capturados primeiro contra uma sessão SEI real (ver `TASKS.md` §"Prioridade — Marco IV").

Variáveis:
- `SEI_WRITE_ARTIFACTS_DIR` — onde ficam screenshots, DOM dumps e audit JSONL (default: `procedures_data/sei_writes/`).
- `SEI_WRITE_MODE` — `dry_run` (default, safe) ou `live` (requer seletores).

### Marco IV — Estágios end-to-end (em andamento)

Workflow objetivo: receber TCE por email → extrair dados do PDF anexado → criar processo SEI → anexar TCE (tipo Externo/Termo/Inicial, sigiloso) → lavrar Despacho → rascunhar email de acuse. O pipeline lógico está pronto (Intent estendido, checker registry, doc catalog, SEIWriter dry-run); falta wire-up no graph + captura de seletores Playwright.

```bash
# Ver o catálogo de classificações SEI
cat ufpr_automation/workspace/SEI_DOC_CATALOG.yaml

# Ver o intent expandido
sed -n '/estagio_nao_obrig_acuse_inicial/,/^```$/p' ufpr_automation/workspace/PROCEDURES.md

# Listar checkers registrados
python -c "from ufpr_automation.procedures.checkers import registered_checkers; print('\n'.join(registered_checkers()))"
```

### Marco V — Automações via Claude Code CLI (plano Max, sem API)

Conjunto de ferramentas offline que rodam o binário `claude` como subprocess (`agent_sdk/runner.py`) sob plano Max — custo zero adicional. **Estritamente separadas do path crítico** (LangGraph + LiteLLM continuam intactos). Todas têm fallback gracioso quando o CLI não está disponível.

| Fase | Módulo | O que faz |
|---|---|---|
| 1 | `agent_sdk/runner.py` | Infra compartilhada: `run_claude_oneshot`, `is_claude_available`, audit JSONL |
| 2 | `agent_sdk/intent_drafter.py` | Clusteriza emails Tier 1, delega para Claude CLI gerar intents YAML, valida via `Intent.model_validate`, append em `PROCEDURES_CANDIDATES.md` (idempotente por hash) |
| 3 | `agent_sdk/feedback_chat.py` | Prepara sessão de revisão de feedback (bootstrap + summary + meta), lança Claude CLI; Streamlit continua standalone |
| 4 | `agent_sdk/debug_classification.py` | Replay Tier 0 + trace de procedure log + feedback lookup + propostas de fix. CLI `--stable-id <prefix>` ou `--last N` |
| 5 | `agent_sdk/rag_auditor.py` | Eval set YAML → recall/latência por query + subset, diff contra baseline, update atômico só em sucesso |
| 6 | `agent_sdk/procedures_staleness.py` | Valida `blocking_checks` vs checker registry, refs de SOUL.md §X, idade de `last_update`, consistência `sei_action` vs catalog |
| 7 | `.claude/commands/`, `.claude/settings.json`, `agent_sdk/skills/maintainer.md` | 5 slash commands (`/run-pipeline-once`, `/feedback-stats`, `/check-tier0`, `/test-suite`, `/rag-query`) + allow/deny pré-aprovado + briefing do maintainer |

```bash
# Exemplos
python -m ufpr_automation.agent_sdk.intent_drafter            # propõe novas intents
python -m ufpr_automation.agent_sdk.debug_classification --last 10
python -m ufpr_automation.agent_sdk.rag_auditor               # audita RAG vs ground truth
python -m ufpr_automation.agent_sdk.procedures_staleness      # checa decadência do playbook
```

Spec completa em [`SDD_CLAUDE_CODE_AUTOMATIONS.md`](SDD_CLAUDE_CODE_AUTOMATIONS.md).

## Configuração (`.env`)

Principais variáveis (ver `.env.example` para a lista completa):

```env
# Canal de e-mail
EMAIL_CHANNEL=gmail
GMAIL_EMAIL=...
GMAIL_APP_PASSWORD=...

# LLM
MINIMAX_API_KEY=...
LLM_MODEL=minimax/MiniMax-M2

# Assinatura e Cc default (Marco IV)
# Single-line com "\n" literais; settings.py decodifica para line breaks reais
ASSINATURA_EMAIL=Att,\nNome\n...\nE-mail\nURL\nTelefone
# Cc automático em todo rascunho gerado (deixe vazio para desativar)
EMAIL_CC_DEFAULT=design.grafico@ufpr.br

# RAG (Google Drive compartilhado)
RAG_STORE_DIR=G:/Meu Drive/ufpr_rag/store
RAG_DOCS_DIR=G:/Meu Drive/ufpr_rag/docs

# Feedback/procedures compartilhados entre máquinas (trabalho ↔ casa)
FEEDBACK_DATA_DIR=G:/Meu Drive/ufpr_rag/feedback_data
PROCEDURES_DATA_DIR=G:/Meu Drive/ufpr_rag/procedures_data

# GraphRAG
NEO4J_URI=bolt://localhost:7687
NEO4J_PASSWORD=...

# Scheduler
SCHEDULE_HOURS=8,13,17
SCHEDULE_TZ=America/Sao_Paulo

# DSPy gate (Marco III)
USE_DSPY=auto                    # auto | on | off

# Fleet pool de browsers (Marco III)
FLEET_BROWSER_POOL_SIZE=3

# Pre-warm SEI/SIGA sessions antes do Fleet fan-out (Marco III refinamento)
# Evita race quando N sub-agentes paralelos tentam auto_login simultaneamente.
# Default OFF. Ativar quando race de login for dor real em produção.
PREWARM_SESSIONS_ENABLED=false   # true|1|yes|on para habilitar
PREWARM_SESSIONS_MAX_AGE_H=6     # idade máxima (horas) da session file antes de re-login

# AFlow topology dispatcher (Marco III)
AFLOW_TOPOLOGY=fleet             # fleet | baseline | skip_rag_high_tier0 | no_self_refine | fleet_no_siga
AFLOW_METRIC=composite
AFLOW_EVAL_LIMIT=20

# SEI write artifacts (Marco III)
SEI_WRITE_ARTIFACTS_DIR=         # opcional, default: procedures_data/sei_writes

# SEI write mode (Marco IV) — dry_run (safe default) | live
# dry_run: loga intenção + screenshot, não clica em nada no SEI
# live:    fluxo Playwright completo (requer seletores capturados)
SEI_WRITE_MODE=dry_run

# OWA fallback (apenas se EMAIL_CHANNEL=owa)
OWA_EMAIL=...
OWA_PASSWORD=...
TELEGRAM_BOT_TOKEN=...    # MFA number-match
TELEGRAM_CHAT_ID=...
```

## Notas

- **Human-in-the-loop:** o sistema **nunca** envia e-mails. Sempre salva como rascunho.
- **Sessão Playwright (OWA):** persistida em `session_data/state.json`. Re-login automático quando expira.
- **Store RAG:** compartilhado via Google Drive (`G:/Meu Drive/ufpr_rag/store`). 167 MB, contém `ufpr_docs` (flat) + `ufpr_raptor` (hierárquico).
- **Feedback compartilhado:** apontando `FEEDBACK_DATA_DIR`/`PROCEDURES_DATA_DIR` para o Drive, o painel Streamlit e o ReflexionMemory passam a ser sincronizados entre múltiplas máquinas (trabalho ↔ casa). Default continua local. Append-only JSONL — evitar execuções simultâneas do scheduler nas duas máquinas.
- **Thread context:** `gmail/thread.py` separa corpo do e-mail em "nova mensagem do remetente" vs "histórico citado" antes de mandar ao LLM, detectando `Em … escreveu:`, `On … wrote:`, `-----Mensagem Original-----` e prefixos `>`. Resolve a confusão do modelo em respostas `Re:`.
- **Categorias:** taxonomia hierárquica com separador ` / ` — 13 valores (ver `core/models.py` `Categoria` ou `workspace/AGENTS.md`).
- **Cache de embeddings:** `multilingual-e5-large` em `~/.cache/huggingface/hub/`. Em uso intenso, set `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` para evitar 429.
- **Windows + UTF-8:** `utils/logging.py` reconfigura `sys.stdout`/`stderr` para UTF-8 no bootstrap do logger — todos os CLIs herdam.
- **Segurança:** o `.env` está no `.gitignore` — nunca comite credenciais.
- **Testes:** `pytest ufpr_automation/tests/ -v` (685 testes).
- **SEI safety arquitetural:** `SEIWriter` não expõe `sign()`, `send()`, `protocol()` ou `finalize()`. Adicionar qualquer um quebra o teste regressivo `test_writer_public_api_is_only_attach_and_draft`. O `_FORBIDDEN_SELECTORS` runtime guard ainda impede clicks em "Assinar/Enviar Processo/Protocolar/btnAssinar" mesmo se um selector escapar. Belt + suspenders.
- **Fleet reducers:** os campos paralelos em `graph/state.py` (`rag_contexts`, `classifications`, `sei_contexts`, `siga_contexts`, `errors`) usam `Annotated[..., reducer]` para que sub-agents do Fleet façam merge de dicts ao invés de last-write-wins. Sem isso, dispatches paralelos via `Send` API perderiam dados.
