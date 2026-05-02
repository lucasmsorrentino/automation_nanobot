# Maintainer Skill — ufpr_automation

Skill curada para o modo interativo do Claude Code operando dentro deste
repositório. Este arquivo NÃO é carregado automaticamente pelo CLI — é uma
referência para o operador (e para o Claude quando perguntado sobre fluxos
comuns) sobre comandos, convenções e atalhos do projeto.

## Contexto rápido

- Projeto duplo: `nanobot/` (framework) + `ufpr_automation/` (deployment UFPR)
- UFPR atualmente em Marco V (Claude Code Automations) — detalhes em
  `ufpr_automation/TASKS.md` e `CLAUDE.md`
- Branch default: `dev`. PRs viram `main`.

## Fluxos frequentes

### 1. Rodar o pipeline

```bash
python -m ufpr_automation --channel gmail --langgraph        # Gmail IMAP
python -m ufpr_automation --channel owa --langgraph          # OWA Playwright
python -m ufpr_automation --schedule --once                  # Agendado 1x
```

### 2. Testes

```bash
python -m pytest ufpr_automation/tests/ -v                    # todos
python -m pytest ufpr_automation/tests/test_agir_estagios.py  # um arquivo
python -m pytest -k "intent_drafter" -v                       # por palavra
```

### 3. RAG

```bash
# Ingerir subset específico
python -m ufpr_automation.rag.ingest --subset estagio
python -m ufpr_automation.rag.ingest --subset cepe/resolucoes

# Re-ingestar só PDFs que falharam antes (OCR fallback)
python -m ufpr_automation.rag.ingest --ocr-only

# Query ad-hoc
python -m ufpr_automation.rag.retriever "prazo de colação de grau" --top-k 5

# Auditar qualidade do RAG contra ground truth curado (Fase 5)
python -m ufpr_automation.agent_sdk.rag_auditor
python -m ufpr_automation.agent_sdk.rag_auditor --quick  # primeiras 5 queries
```

### 4. Tier 0 Playbook

```bash
# Detectar intents desatualizados (Fase 6)
python -m ufpr_automation.agent_sdk.procedures_staleness
python -m ufpr_automation.agent_sdk.procedures_staleness --max-age-days 60

# Gerar candidatos de intent a partir de clusters Tier 1 (Fase 2)
python -m ufpr_automation.agent_sdk.intent_drafter --dry-run
python -m ufpr_automation.agent_sdk.intent_drafter --last-days 14 --min-frequency 5

# Ver checkers registrados
python -c "from ufpr_automation.procedures.checkers import registered_checkers; print('\n'.join(registered_checkers()))"
```

### 5. Feedback / debug

```bash
# Stats de feedback
python -m ufpr_automation.feedback stats

# Review interativo (Streamlit — fallback obrigatório)
streamlit run ufpr_automation/feedback/web.py

# Review via chat (Claude CLI — preferido quando disponível) (Fase 3)
python -m ufpr_automation.agent_sdk.feedback_chat

# Diagnosticar classificação específica (Fase 4)
python -m ufpr_automation.agent_sdk.debug_classification --stable-id <prefix>
python -m ufpr_automation.agent_sdk.debug_classification --last 5
```

### 6. GraphRAG / Neo4j

```bash
# Seed / re-seed do grafo
python -m ufpr_automation.graphrag.seed
python -m ufpr_automation.graphrag.seed --clear
```

## Convenções do repositório

- **Testes:** suite deve ficar verde. Mocks em nível de uso (cascaded_completion
  no namespace do cliente, não litellm direto — ver `test_llm_client.py`)
- **Playwright:** imports tipados via `TYPE_CHECKING` pra não quebrar
  coleta de testes em máquinas sem Playwright
- **SEI:** `SEIWriter` expõe APENAS `create_process`, `attach_document`,
  `save_despacho_draft`. Nunca `sign()`/`enviar()`/`protocolar()`. 6 testes
  regressivos garantem isso.
- **SIGA:** read-only por design
- **Commits:** mensagem descritiva em pt-br ou en-us, suffix `Co-Authored-By: Claude`
- **Branches:** `dev` default, `main` é release. Feature branches `feat/<nome>`

## Anti-padrões conhecidos (não repetir)

1. **Não mockar `ufpr_automation.llm.client.litellm`** — o router faz
   `import litellm` localmente; o mock não pega. Mockar
   `cascaded_completion_sync` / `cascaded_completion` em vez.
2. **Não escrever direto em PROCEDURES.md** — sempre via
   PROCEDURES_CANDIDATES.md + revisão humana.
3. **Não usar `datetime.utcnow()`** — Python 3.12+ deprecou. Usar
   `datetime.now(timezone.utc)`.
4. **Não importar Playwright no topo do módulo** — usar `TYPE_CHECKING`.
5. **Não importar `agent_sdk/` de `feedback/web.py`** — Streamlit é
   fallback obrigatório e deve rodar sem `claude` instalado.

## Onde buscar mais contexto

- `CLAUDE.md` — arquitetura e comandos de alto nível
- `ufpr_automation/TASKS.md` — roadmap + status atual
- `ufpr_automation/ARCHITECTURE.md` — trajetória de maturação
- `ufpr_automation/SDD_CLAUDE_CODE_AUTOMATIONS.md` — specs das automações Marco V
- `ufpr_automation/SDD_SEI_SELECTOR_CAPTURE.md` — sprint de captura SEI ao vivo
