# SDD — Automações via Claude Code CLI (Plano Max)

> **Status:** especificação para roadmap de adoção  
> **Audiência:** mantenedores do `ufpr_automation` e o próprio Claude Code rodando em sessões futuras  
> **Custo:** zero (todas as automações usam quota do plano Max via `claude` CLI autenticado, sem chave de API)  
> **Documento irmão:** [`SDD_SEI_SELECTOR_CAPTURE.md`](SDD_SEI_SELECTOR_CAPTURE.md) — primeira automação concreta, já especificada em detalhes

---

## 1. Visão geral e filosofia

O `claude` CLI (Claude Code) **é** um harness de Claude Agent SDK pré-configurado: tem Bash, Read, Write, Edit, Glob, Grep, Task (subagents), MCP, hooks, slash commands. Quando autenticado com a conta Max via `claude /login`, todas as invocações usam quota da assinatura — não há cobrança por token. Isso permite um padrão arquitetural híbrido para o `ufpr_automation`:

```
┌──────────────────────────────────────────────────────┐
│ Path crítico online (por email, 50/dia × 3 horários) │
│   LangGraph + DSPy + LiteLLM + MiniMax-M2            │  ← determinístico, cheap, auditável
│   - Marcos I-III + IV (não muda)                     │  ← MANTÉM como está
└──────────────────────────────────────────────────────┘
                       ↕  fronteira intransponível
┌──────────────────────────────────────────────────────┐
│ Tooling offline (sessões manuais ou agendadas raras) │
│   claude CLI subprocess (`claude -p ...`)            │  ← exploratório, plano Max
│   - SEI selector capture (já especificado)           │
│   - Intent drafter (Marco IV.2)                      │
│   - Feedback review chat                             │
│   - Classification debugger                          │
│   - RAG quality auditor                              │
│   - PROCEDURES staleness checker                     │
│   - Maintainer chat                                  │
└──────────────────────────────────────────────────────┘
```

**Princípio cardinal:** o lado offline JAMAIS é invocado dentro do loop online de classificação de email. A separação é tanto operacional (latência: claude leva ~30s-2min; LangGraph leva ~10-30s) quanto semântica (claude é "criativo/exploratório", LangGraph é "determinístico/auditável"). Misturar quebra a previsibilidade que justifica `SEIWriter._FORBIDDEN_SELECTORS`.

### 1.1 Restrições compartilhadas por todas as automações

| Restrição | Razão |
|---|---|
| **Sem chave de API Anthropic** — nada de `claude-agent-sdk` Python package nem `ANTHROPIC_API_KEY` | Custo zero, evita lock-in. Todas as invocações via `subprocess.run(["claude", "-p", ...])` ou `claude` interativo |
| **Sem `claude` no path crítico** | Determinismo + custo (quota Max é finita) + latência |
| **Sempre human-in-the-loop para mudanças com efeito persistente** | Claude Code propõe, humano commita. Vale para PROCEDURES.md, código, prompts DSPy, etc. |
| **Audit trail obrigatório** | Toda invocação programática loga em `procedures_data/agent_sdk/<task>/<ts>.jsonl` com prompt + output + cost estimate |
| **Idempotência sempre que possível** | Re-rodar não deve gerar drift. Outputs determinísticos via `--output-format json` quando viável |
| **Falha-safe** | Se `claude` não estiver autenticado / quota esgotada / network down, a automação loga e desiste — nunca quebra o pipeline online |

### 1.2 O que muda (e o que não muda) no projeto

**Adições propostas:**
- `ufpr_automation/agent_sdk/` — módulo novo com runner + helpers compartilhados
- `ufpr_automation/agent_sdk/skills/` — briefings markdown por tarefa (lidos pelo `claude -p` via Read)
- `scripts/` (raiz do repo) — entry-point scripts CLI por automação
- `procedures_data/agent_sdk/` — audit trails (gitignored, criado em runtime)
- 6 entradas novas em `pyproject.toml` opcionais (`[claude-code]` extra) — só se quisermos validar a presença do binário

**Não muda:**
- `nanobot/` — framework continua provider-agnostic
- `graph/`, `dspy_modules/`, `llm/`, `rag/`, `sei/`, `siga/` — pipeline online intacto
- `pyproject.toml` deps obrigatórias — Claude Code é externo (binário), não dependência Python

---

## 2. Padrão arquitetural reutilizável

Antes de cada spec individual, define-se uma camada compartilhada para que as 6 automações não dupliquem código.

### 2.1 `agent_sdk/runner.py` — wrapper de subprocess

```python
# ufpr_automation/agent_sdk/runner.py
"""Thin wrapper around `claude -p ...` for one-shot agent invocations.

All automations defined under ufpr_automation/agent_sdk/ go through this
runner so audit, retries, and output parsing are uniform.
"""
from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ufpr_automation.config import settings
from ufpr_automation.utils.logging import logger


AGENT_SDK_DIR = settings.PACKAGE_ROOT / "procedures_data" / "agent_sdk"


@dataclass
class ClaudeRunResult:
    """Outcome of a one-shot `claude -p` invocation."""
    success: bool
    task: str
    run_id: str
    started_at: str
    duration_s: float
    prompt_chars: int
    output_text: str = ""
    output_json: dict | None = None
    stderr: str = ""
    exit_code: int = 0
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None


def run_claude_oneshot(
    task: str,
    prompt: str,
    *,
    output_format: str = "text",          # "text" | "json" | "stream-json"
    cwd: Path | None = None,
    timeout_s: int = 600,
    extra_args: list[str] | None = None,
    dry_run: bool = False,
) -> ClaudeRunResult:
    """Run `claude -p PROMPT` and capture stdout/stderr.

    Args:
        task: short task identifier (used for audit dir + logs)
        prompt: full prompt text — will be passed via stdin to avoid argv limits
        output_format: passed as --output-format
        cwd: working directory (default: project root)
        timeout_s: kill after N seconds
        extra_args: appended to the claude argv
        dry_run: if True, log the intended invocation but do NOT call claude

    Returns:
        ClaudeRunResult with parsed output (json if applicable) + audit refs.
    """
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc)
    audit_dir = AGENT_SDK_DIR / task / run_id
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Audit: prompt
    (audit_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    if dry_run:
        logger.info("agent_sdk[%s] DRY_RUN — would invoke claude -p (prompt: %d chars)",
                    task, len(prompt))
        return ClaudeRunResult(
            success=True, task=task, run_id=run_id,
            started_at=started.isoformat(), duration_s=0.0,
            prompt_chars=len(prompt), output_text="[DRY_RUN]",
            artifacts=[audit_dir / "prompt.md"],
        )

    argv = ["claude", "-p", "-", "--output-format", output_format]
    if extra_args:
        argv.extend(extra_args)

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=str(cwd or settings.PROJECT_ROOT),
            timeout=timeout_s,
            check=False,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        return ClaudeRunResult(
            success=False, task=task, run_id=run_id,
            started_at=started.isoformat(),
            duration_s=time.monotonic() - t0,
            prompt_chars=len(prompt),
            error=f"timeout after {timeout_s}s",
        )
    except FileNotFoundError:
        return ClaudeRunResult(
            success=False, task=task, run_id=run_id,
            started_at=started.isoformat(),
            duration_s=0.0, prompt_chars=len(prompt),
            error="claude binary not found in PATH — run `claude /login` first",
        )

    duration = time.monotonic() - t0

    # Audit: stdout + stderr
    (audit_dir / "stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (audit_dir / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")

    # Parse JSON if requested
    output_json: dict | None = None
    if output_format == "json" and proc.returncode == 0:
        try:
            output_json = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            logger.warning("agent_sdk[%s] failed to parse JSON output: %s", task, e)

    # Audit JSONL row
    audit_row = {
        "ts": started.isoformat(),
        "task": task,
        "run_id": run_id,
        "duration_s": round(duration, 2),
        "prompt_chars": len(prompt),
        "output_format": output_format,
        "exit_code": proc.returncode,
        "success": proc.returncode == 0,
        "stdout_chars": len(proc.stdout or ""),
    }
    audit_log = AGENT_SDK_DIR / "audit.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(audit_row, ensure_ascii=False) + "\n")

    return ClaudeRunResult(
        success=proc.returncode == 0,
        task=task, run_id=run_id,
        started_at=started.isoformat(),
        duration_s=duration,
        prompt_chars=len(prompt),
        output_text=proc.stdout or "",
        output_json=output_json,
        stderr=proc.stderr or "",
        exit_code=proc.returncode,
        artifacts=[
            audit_dir / "prompt.md",
            audit_dir / "stdout.txt",
            audit_dir / "stderr.txt",
        ],
    )
```

### 2.2 `agent_sdk/skills/<task>.md` — briefings reutilizáveis

Cada automação tem um arquivo markdown em `ufpr_automation/agent_sdk/skills/` que descreve a tarefa em detalhe. O prompt programático que vai para `claude -p` referencia esse arquivo via instrução `Leia ufpr_automation/agent_sdk/skills/<task>.md`. Isso permite:

- Manter prompts sob versionamento sem inflar o código Python
- Iterar a redação do briefing sem mexer no runner
- Testar manualmente: `claude` interativo + `Leia .../skills/intent_drafter.md`

### 2.3 Output schemas via Pydantic

Quando uma automação espera output estruturado (JSON), define-se um modelo Pydantic em `agent_sdk/schemas.py` e o briefing instrui o Claude Code a emitir exatamente esse formato. O runner valida com `Model.model_validate(result.output_json)` — falhas viram retry com prompt de correção.

### 2.4 Hooks de scheduler

Automações periódicas (ex.: intent drafter semanal, RAG auditor mensal) plugam no `apscheduler` existente em `scheduler.py` como jobs separados, **distintos** do job principal de processamento de email. Configurável via `.env`:

```env
# Agendamento das automações claude code (CRON-like)
AGENT_SDK_INTENT_DRAFTER_CRON="0 18 * * SUN"     # domingo 18h
AGENT_SDK_RAG_AUDITOR_CRON="0 9 1 * *"           # 1º dia do mês
AGENT_SDK_PROCEDURES_STALENESS_CRON="0 12 * * MON"  # segunda 12h
```

Vazio = job desabilitado.

### 2.5 Falhas e fallback

Toda automação implementa:
1. **Pre-flight check** — `claude --version` retorna 0? Se não, log + skip.
2. **Quota check** — se `claude -p "echo OK"` retorna erro de rate limit, marcar last_failed e re-tentar daqui a 1h.
3. **Idempotência** — re-rodar não causa duplicação. Para drafters: gravar em `*_CANDIDATES.md` com hash do conteúdo; se hash já existe, skip.
4. **Audit obrigatório** — antes de qualquer ação persistente, gravar JSONL.

---

## 3. Spec — Intent Drafter (Marco IV.2)

> **Prioridade:** ALTA — desbloqueia o ciclo de auto-aprendizado do Tier 0 playbook  
> **Frequência:** semanal (job APScheduler) ou manual (`python -m ufpr_automation.agent_sdk.intent_drafter`)  
> **Custo estimado por execução:** ~$5-15 equivalente, dentro do plano Max sem cobrança

### 3.1 Goal

Analisar `procedures_data/procedures.jsonl` + `feedback_data/feedback.jsonl` periodicamente, identificar **categorias de email que recorrentemente caem em Tier 1** (não foram resolvidas pelo playbook) e **propor intents YAML candidatos** para `workspace/PROCEDURES_CANDIDATES.md`. Humano revisa, e se aprovar, promove manualmente para `PROCEDURES.md` via comando dedicado (futuro: `python -m ufpr_automation.procedures.promote <intent_name>`).

### 3.2 Trigger

- **Manual:** `python -m ufpr_automation.agent_sdk.intent_drafter [--last-days 14] [--min-frequency 5]`
- **Agendado:** se `AGENT_SDK_INTENT_DRAFTER_CRON` estiver setado, scheduler dispara

### 3.3 Inputs

- `procedures_data/procedures.jsonl` (últimos N dias, default 14)
- `feedback_data/feedback.jsonl` (correções humanas — ground truth)
- `workspace/PROCEDURES.md` (intents existentes — para evitar duplicação)
- `workspace/SEI_DOC_CATALOG.yaml` (catálogo de classificações)
- RAG store (consultado pelo Claude Code via Bash → `python -m ufpr_automation.rag.retriever "..."`)
- `workspace/SOUL.md` (regras normativas)

### 3.4 Output

- **Primário:** `workspace/PROCEDURES_CANDIDATES.md` — append de bloco(s) ` ```intent ` candidato(s), cada um precedido por header de proveniência:
  ```markdown
  <!-- Candidato gerado por agent_sdk/intent_drafter em 2026-04-19T18:00:00
       Baseado em 23 emails Tier 1 entre 2026-04-05 e 2026-04-19
       Cluster: "consulta sobre AFC + pedido de declaração" (Categoria: Formativas)
       RAG queries: "AFC validação", "declaração horas formativas"
       Fontes: ['SOUL.md §13', 'Resolução 70/04-CEPE', 'manual_sei.txt §AFC']
       Hash: a1b2c3...
       Para promover: revise abaixo e mova o bloco para PROCEDURES.md -->
  
  ```intent
  intent_name: formativas_solicitar_declaracao_afc
  ...
  ```
  ```
- **Secundário:** `procedures_data/agent_sdk/intent_drafter/<run_id>/` com prompt + stdout + stderr + relatório de cluster
- **Audit:** `procedures_data/agent_sdk/audit.jsonl` row

### 3.5 Procedure (o que o Claude Code faz)

1. Lê o briefing `agent_sdk/skills/intent_drafter.md`
2. Lê os 3 inputs primários (jsonl + PROCEDURES.md atual)
3. Roda análise: agrupa emails Tier 1 por categoria + ngrams do subject + sender domain. Para cada cluster ≥ N (default 5):
   - Lê 3-5 emails amostrais do cluster
   - Identifica o tema comum
   - Verifica se já existe intent que cobre — se sim, propõe **expansão** (novos keywords) ao invés de novo intent
   - Senão, faz queries RAG para encontrar fontes normativas (`python -m ufpr_automation.rag.retriever "tema do cluster" --top-k 5`)
   - Compõe um intent YAML completo seguindo o schema do `Intent` (incluindo os campos Marco IV: `sei_action`, `required_attachments`, `blocking_checks`, `despacho_template`)
4. Append no `PROCEDURES_CANDIDATES.md` com header de proveniência + hash de conteúdo
5. Se hash já existe no arquivo, skip (idempotência)
6. Escreve relatório de execução em `<run_id>/REPORT.md` com:
   - Quantos clusters analisados
   - Quantos viraram candidato vs skip vs duplicado
   - Quantos viraram expansão de intent existente
   - Recomendações para revisão humana

### 3.6 Briefing template (a ser salvo em `agent_sdk/skills/intent_drafter.md`)

Resumo do conteúdo (a fazer na sprint de implementação):
- Contexto: o que é Tier 0 vs Tier 1, por que matters
- Schema completo do `Intent` (referenciar `procedures/playbook.py:Intent`)
- Como ler `procedures.jsonl` (`ProcedureStore.list_recent`)
- Como rodar o RAG (`python -m ufpr_automation.rag.retriever`)
- Critérios de qualidade para um intent: keywords não-ambíguos, required_fields realistas, sources ancorados em normas reais (não inventar)
- **Anti-padrão crítico:** NÃO inventar fontes (Lei XXX/YYYY) — só citar o que aparecer no RAG. Se não achar fonte, marcar `confidence: 0.5` e `sources: ["pendente_revisao_humana"]`
- Exemplos reais de bons intents (referenciar `estagio_nao_obrig_acuse_inicial`)
- Output: append em `PROCEDURES_CANDIDATES.md` com header de proveniência

### 3.7 Test plan

- **Unit:** mock `ProcedureStore` com clusters sintéticos, rodar `intent_drafter --dry-run`, verificar que o YAML proposto valida via `Intent.model_validate`
- **Smoke:** rodar contra `procedures_data/` real (após acumular ~50+ runs), verificar que ao menos 1 candidato sai e o `PROCEDURES_CANDIDATES.md` é escrito sem corromper YAML
- **Idempotência:** rodar 2× com mesmo input — segunda execução não duplica candidatos

### 3.8 Critérios de sucesso

- [ ] `agent_sdk/intent_drafter.py` existe e implementa o procedure
- [ ] `agent_sdk/skills/intent_drafter.md` documenta o briefing completo
- [ ] CLI `python -m ufpr_automation.agent_sdk.intent_drafter` funciona
- [ ] `PROCEDURES_CANDIDATES.md` é criado se não existir, append-only depois
- [ ] Audit JSONL recebe row por execução
- [ ] Idempotência via hash funcionando
- [ ] Job APScheduler opcional via `AGENT_SDK_INTENT_DRAFTER_CRON`

---

## 4. Spec — Feedback Review Chat (complementa Streamlit, não substitui)

> **Prioridade:** ALTA — adiciona uma interface conversacional poderosa **ao lado** do Streamlit feedback UI existente  
> **Frequência:** ad-hoc (você escolhe qual usar conforme o caso)  
> **Custo:** muito baixo (sessões de ~5-15 min, dentro da quota Max)  
> **Streamlit continua disponível como fallback obrigatório** (ver §4.7 abaixo)

### 4.1 Goal

Adicionar uma **segunda via** de revisão de feedback ao lado do `feedback/web.py` (Streamlit), para casos onde o chat conversacional é mais produtivo: investigação profunda, consultas live a SEI/SIGA durante a revisão, captura de "por quê" para o Reflexion. O Streamlit continua sendo a via primária para batch triage visual e o **fallback obrigatório** para qualquer situação onde o Claude Code não esteja disponível (quota Max esgotada, sem rede, sem `claude` autenticado, Anthropic com outage, operador prefere clicar a digitar).

O agent do Feedback Chat tem tools para:

- Ler `feedback_data/last_run.jsonl` (resultado da última execução do pipeline)
- Consultar SIGA (read-only) para validar dados de aluno
- Consultar SEI (read-only) para validar processos
- Consultar RAG para buscar normativas
- Aplicar correções no `feedback.jsonl` via `FeedbackStore.add_correction()` (com confirmação humana)
- Explicar por que o pipeline classificou de uma forma específica
- Capturar entries de Reflexion quando o operador explica o erro

### 4.2 Trigger

- **Manual:** `python -m ufpr_automation.agent_sdk.feedback_chat` — abre uma sessão `claude` interativa pré-briefada
- **Atalho:** alias no shell, ex.: `alias review='cd ~/nanobot && claude < ufpr_automation/agent_sdk/skills/feedback_chat_bootstrap.md'`

### 4.3 Inputs

- `feedback_data/last_run.jsonl` (última execução do pipeline)
- `feedback_data/feedback.jsonl` (histórico de correções)
- Acesso live a SIGA/SEI via tools Playwright
- RAG via `python -m ufpr_automation.rag.retriever`
- `workspace/SOUL.md`, `workspace/PROCEDURES.md`, `workspace/SEI_DOC_CATALOG.yaml`

### 4.4 Output

- Atualizações em `feedback_data/feedback.jsonl` (append-only)
- Atualizações em `feedback_data/reflexion_memory.jsonl` quando o user explica POR QUÊ a classificação tava errada
- Audit: `procedures_data/agent_sdk/feedback_chat/<run_id>/transcript.md`

### 4.5 Procedure

A sessão é interativa, então o "procedure" é o briefing inicial que define o setup:

1. Bootstrap: Claude Code lê `feedback_data/last_run.jsonl` e mostra um resumo: N emails processados, X auto-draft, Y human review, Z escalação
2. Para cada email da última run, oferece um sumário curto (subject, sender, categoria proposta, confidence)
3. Você diz: "vamos para o email 3" / "todos os Estágios primeiro" / "me explica por que o email 5 foi classificado como Outros"
4. Para cada email selecionado, o agent:
   - Mostra rascunho proposto
   - Mostra contexto RAG usado
   - Mostra resultado de SEI/SIGA consultas (se houve)
   - Pergunta: aprovar / corrigir / explicar
5. Se você corrigir, ele formata como entrada `feedback.jsonl` e pede confirmação antes de salvar
6. Se você explicar (ex.: "isso não é Estágios, é Acadêmico — TCC não é estágio"), ele salva como Reflexion entry para o pipeline aprender

### 4.6 Briefing template (a ser salvo em `agent_sdk/skills/feedback_chat_bootstrap.md`)

- Contexto do projeto (referenciar CLAUDE.md)
- Schema de `feedback.jsonl` e `last_run.jsonl`
- Como aplicar correções via Edit no JSONL (não via Append direto — usar `feedback/store.py` API se disponível)
- Tone: cordial, técnico, cita fontes
- **Permissão:** pode rodar Bash, Read, Edit em `feedback_data/`. NÃO pode tocar `PROCEDURES.md` (esse caminho passa pelo intent_drafter + revisão humana separada)

### 4.7 Quando usar cada via — Feedback Chat (default) vs Streamlit (fallback)

**Os dois caminhos coexistem permanentemente.** O Feedback Chat é o caminho padrão; o Streamlit é a rede de segurança obrigatória — usado quando o chat não está disponível ou quando algum cenário específico favorece a tabela visual.

**Default:** Feedback Chat. A tabela abaixo marca **exceções** onde Streamlit vence ou é o único caminho viável.

| Cenário | Default (Chat) | Fallback (Streamlit) |
|---|---|---|
| Investigação profunda de 1-2 emails ("por que classificou X?") | ✅ default | — |
| Precisa consultar SEI/SIGA durante a revisão | ✅ default | — |
| Capturar motivo do erro pra Reflexion | ✅ default | — |
| Modificar prompts DSPy a partir de feedback acumulado | ✅ default (chat pode rodar `optimize`) | ✅ alternativa (export → optimize) |
| Triagem rápida de muitos emails (visual scan, "esses 5 ok, esses 2 errados") | — | ✅ exceção (tabela compacta é mais rápida) |
| Operador não-técnico, prefere clicar a digitar | — | ✅ exceção (form-based) |
| Acesso simultâneo de múltiplas máquinas / múltiplos operadores | — | ✅ exceção (web UI multi-tab) |
| Onboarding de novo operador (curva de aprendizado menor) | — | ✅ exceção |
| **Sem `claude` autenticado / quota Max esgotada / Anthropic offline** | ❌ indisponível | ✅ **OBRIGATÓRIO — único caminho** |

**Regra prática para o operador:** abra o Feedback Chat por padrão. Se o chat estiver indisponível (sem `claude` autenticado, quota Max esgotada, Anthropic com outage), ou se a tarefa do dia for batch triage visual de muitos emails, abra o Streamlit.

**Regra prática para o sistema:** o `FeedbackStore` é a fonte única da verdade. Os dois caminhos escrevem nele via `add_correction()` — nenhum dos dois bypassa o outro nem causa conflito.

### 4.8 Garantia de fallback (CRÍTICO)

O Streamlit `feedback/web.py` **deve continuar funcionando sem dependência alguma do Claude Code**:

- [ ] Nenhum import novo em `feedback/web.py` referenciando `agent_sdk/`
- [ ] Nenhum dado em `feedback_data/` em formato exclusivo de uma das vias
- [ ] `streamlit run ufpr_automation/feedback/web.py` continua iniciando a UI sem warnings
- [ ] Documentação no README lista o Feedback Chat como **opção default** e o Streamlit como **fallback explícito** (com a tabela §4.7 ou link pra ela)
- [ ] Test de regressão: `test_feedback_streamlit_independent` garante que `feedback.web` importa sem `claude` no PATH

### 4.9 Critérios de sucesso

- [ ] `agent_sdk/feedback_chat.py` cria o bootstrap e exec `claude`
- [ ] `agent_sdk/skills/feedback_chat_bootstrap.md` está completo
- [ ] Sessão consegue ler `last_run.jsonl` e listar emails
- [ ] Correções são gravadas via `FeedbackStore.add_correction()` (não escrita direta)
- [ ] Transcript salvo em `procedures_data/agent_sdk/feedback_chat/<run_id>/`
- [ ] Reflexion entries criadas quando o user explica o erro
- [ ] **Streamlit `feedback/web.py` continua funcionando sem mudança** — `streamlit run` segue funcional
- [ ] README documenta as duas vias com a tabela §4.7

---

## 5. Spec — Classification Debugger

> **Prioridade:** ALTA — diagnóstico imediato quando a classificação está errada  
> **Frequência:** ad-hoc, ~1× por semana  
> **Custo:** muito baixo (~5 min de chat)

### 5.1 Goal

Quando você nota que um email foi mal-classificado, em vez de ler logs e adivinhar, você abre um "debugger conversacional" passando o `stable_id` do email. O agent reconstrói o caminho que aquele email tomou através do pipeline e explica:

- Tier 0 hit/miss e por quê
- Se teve match, qual intent + score
- Se foi para Tier 1: qual contexto RAG retornado, qual prompt do classifier, qual output do LLM, qual resultado do Self-Refine, qual decisão do router
- Se passou por SEI/SIGA consult: o que foi retornado
- Onde, especificamente, o pipeline tomou a decisão errada

E **propõe** correção (mas não aplica): adicionar keyword ao Tier 0 intent X / criar feedback entry / ajustar o threshold do router / ingerir doc novo no RAG.

### 5.2 Trigger

```bash
python -m ufpr_automation.agent_sdk.debug_classification --stable-id b02f093d
# ou
python -m ufpr_automation.agent_sdk.debug_classification --last 5  # últimos 5 da última run
```

### 5.3 Inputs

- `feedback_data/last_run.jsonl`
- `procedures_data/procedures.jsonl` (steps do pipeline)
- LangGraph checkpoint do email (se SQLite checkpointing salvou)
- RAG store (re-rodar a query usada)
- `workspace/PROCEDURES.md`, `workspace/SOUL.md`

### 5.4 Output

- Markdown report em `procedures_data/agent_sdk/debug_classification/<run_id>/<stable_id>.md` com:
  - Trace completo do email
  - Diagnóstico do erro (se houver)
  - 1-3 propostas de correção, cada uma com:
    - Tipo (intent expansion / threshold tweak / new feedback entry / RAG ingestion)
    - Diff sugerido
    - Risco (alto/médio/baixo)
    - Esforço (em LoC)
- Audit JSONL row

### 5.5 Procedure

1. Lê o briefing
2. Carrega o email + classification do last_run
3. Replay determinístico do Tier 0: roda o playbook contra o subject+body, mostra score/method
4. Se Tier 0 errou: identifica qual keyword falhou ou qual semantic match passou abaixo do threshold
5. Se Tier 1: lê o trace de procedures.jsonl, mostra cada step
6. Compara com PROCEDURES.md vigente — propõe edits cirúrgicos
7. Escreve o report

### 5.6 Critérios de sucesso

- [ ] CLI `--stable-id` e `--last N` funcionam
- [ ] Report markdown gerado é claro e cita evidências (não "achismo")
- [ ] Pelo menos 1 proposta de correção concreta por debug
- [ ] Não aplica nada (só propõe — humano decide)

---

## 6. Spec — RAG Quality Auditor

> **Prioridade:** MÉDIA — pega drift do RAG ao longo do tempo  
> **Frequência:** mensal (job APScheduler)  
> **Custo:** moderado (~$5-10 equivalente por execução)

### 6.1 Goal

Manter um conjunto de **20-30 queries de teste com resposta esperada** (ground truth) e rodar mensalmente contra o RAG. Detectar:

- **Recall drop** — query "regulamento de estágio Design Gráfico" não retorna mais o doc certo no top-3
- **Score drift** — score médio das queries de teste caiu > 10%
- **Coverage** — algum subset (cepe, prograd, manual_sei, etc.) está retornando resultados ruins?
- **Latência** — p95 do tempo de query degradou?

Quando algo cai abaixo do threshold, escreve relatório + propõe ações (re-ingerir subset X, ajustar separadores do chunker, etc.).

### 6.2 Trigger

- **Agendado:** `AGENT_SDK_RAG_AUDITOR_CRON` (default: 1º dia do mês 9h)
- **Manual:** `python -m ufpr_automation.agent_sdk.rag_auditor [--quick]`

### 6.3 Inputs

- `agent_sdk/eval_sets/rag_ground_truth.yaml` — arquivo curado a mão (item §6.5)
- RAG store via `RAGRetriever`
- `procedures_data/agent_sdk/rag_auditor/baseline.json` — última execução de referência (para comparar)

### 6.4 Output

- `procedures_data/agent_sdk/rag_auditor/<run_id>/report.md` com:
  - Métricas por query (rank do doc esperado, score, latência)
  - Métricas agregadas por subset
  - Comparação com baseline anterior
  - **Alertas** quando recall@3 < 90% ou score médio cai > 10%
  - Propostas de ação se algo crítico
- `procedures_data/agent_sdk/rag_auditor/baseline.json` atualizado se a run passou

### 6.5 `rag_ground_truth.yaml` (formato)

```yaml
queries:
  - id: "estagio_regulamento_dg"
    query: "regulamento de estágio do curso de Design Gráfico"
    expected_doc_substring: "Regulamento de Estágio Design"
    expected_in_top_k: 3
    subset: estagio
    notes: "Doc canônico, deveria sempre ser top-1"

  - id: "afc_resolucao_70_04"
    query: "Resolução 70/04 atividades formativas complementares"
    expected_doc_substring: "70-04"
    expected_in_top_k: 3
    subset: cepe
```

Item de implementação separada: o usuário (ou Claude Code via maintainer mode) cura essa lista com 20-30 queries cobrindo cada subset.

### 6.6 Procedure

1. Lê ground truth
2. Para cada query, roda `RAGRetriever.search()`, mede latência, encontra rank do `expected_doc_substring` nos top-K
3. Agrega por subset, compara com baseline
4. Se alguma métrica caiu > threshold, marca como alerta
5. Escreve report markdown
6. Atualiza baseline.json (atomic — só se a run passou todas as métricas hard)

### 6.7 Critérios de sucesso

- [ ] CLI funciona em modo manual e agendado
- [ ] `rag_ground_truth.yaml` curado com 20+ queries
- [ ] Report markdown legível
- [ ] Alertas dispararam por degradação simulada (teste com query que sabidamente não retorna)
- [ ] Job APScheduler opcional

---

## 7. Spec — PROCEDURES.md Staleness Checker

> **Prioridade:** MÉDIA — mantém o playbook Tier 0 alinhado com SOUL.md / RAG  
> **Frequência:** semanal ou disparado por mudança em SOUL.md  
> **Custo:** baixo (~2-5 min)

### 7.1 Goal

Para cada intent em `PROCEDURES.md`, verificar se o `template`, `despacho_template`, `sources` e `blocking_checks` ainda batem com:
- O conteúdo atual de `workspace/SOUL.md`
- As normas vigentes no Neo4j (`status: vigente`)
- O `SEI_DOC_CATALOG.yaml`

Sinalizar inconsistências para revisão humana (não aplica correções automáticas — esse caminho passa pelo intent_drafter).

### 7.2 Trigger

- **Agendado:** `AGENT_SDK_PROCEDURES_STALENESS_CRON` (default: segunda 12h)
- **Manual:** `python -m ufpr_automation.agent_sdk.procedures_staleness`
- **Hook:** se `SOUL.md` for editado (git hook), dispara automaticamente

### 7.3 Output

- `procedures_data/agent_sdk/procedures_staleness/<run_id>/report.md` com:
  - Por intent: ✅ ok / ⚠️ atenção / 🔴 stale
  - Detalhe das inconsistências encontradas (citação do SOUL.md vs intent)
  - Sugestões de fix (mas NÃO aplicadas — humano que decide)

### 7.4 Procedure

1. Lê todos os intents de PROCEDURES.md
2. Para cada um:
   - Lê as fontes citadas em `sources` e verifica se ainda existem no SOUL.md / Neo4j
   - Lê `template` e `despacho_template`, identifica placeholders, verifica se as regras subjacentes ainda valem
   - Para `blocking_checks`, verifica que cada ID ainda está registrado em `procedures/checkers.py`
3. Marca resultado por intent
4. Escreve report

### 7.5 Critérios de sucesso

- [ ] CLI funciona
- [ ] Report mostra ao menos 1 ⚠️ ou 🔴 quando rodado contra um intent intencionalmente desatualizado
- [ ] Não modifica PROCEDURES.md (só lê)

---

## 8. Spec — Maintainer Tool ("Claude Code para o ufpr_automation")

> **Prioridade:** MÉDIA — acelera dev work, especialmente onboarding de novos contribuidores  
> **Frequência:** sempre que precisar mexer no código  
> **Custo:** depende do uso, mas dentro da quota Max

### 8.1 Goal

Não é uma automação batch — é o **modo interativo do Claude Code** rodando dentro do diretório do projeto, com CLAUDE.md já configurado, fazendo as tarefas que normalmente passariam por uma IDE. Casos de uso:

- "Adiciona um intent novo pra Aproveitamento de Disciplinas baseado nesses 3 emails"
- "Por que esse teste tá flaky?"
- "Ingere esse PDF novo no RAG e me confirma que tá indexado"
- "Tem alguma intent duplicada no PROCEDURES?"
- "Compila o DSPy com o feedback atual"

### 8.2 Trigger

```bash
cd ufpr_automation
claude
```

Sem mais nada. CLAUDE.md já briefa.

### 8.3 Melhorias propostas (este SDD entrega):

- [ ] **Skill curation** — `agent_sdk/skills/maintainer.md` com lista de comandos comuns + dicas (ex.: "para re-ingerir só estágio: `python -m ufpr_automation.rag.ingest --subset estagio`")
- [ ] **Slash commands custom** — registrar slash commands específicos do projeto:
  - `/run-pipeline-once` → executa `python -m ufpr_automation --schedule --once`
  - `/feedback-stats` → executa `python -m ufpr_automation.feedback stats`
  - `/check-tier0` → executa um check rápido do playbook
- [ ] **Settings.json local** — `.claude/settings.json` no projeto com permissões pré-aprovadas para os comandos comuns (read-only)

### 8.4 Critérios de sucesso

- [ ] `agent_sdk/skills/maintainer.md` está completo
- [ ] Slash commands registrados (se a feature for usada — opcional)
- [ ] `.claude/settings.json` documentado (sem credenciais)

---

## 9. Roadmap de adoção

Ordem recomendada (cada etapa pressupõe a anterior estável):

### Fase 1 — Infra compartilhada (1 sessão de implementação)

1. Criar `ufpr_automation/agent_sdk/` (módulo vazio com `__init__.py`)
2. Implementar `agent_sdk/runner.py` (§2.1 acima)
3. Implementar `agent_sdk/schemas.py` (vazio inicialmente, modelos vão entrando conforme as automações são implementadas)
4. Criar `ufpr_automation/agent_sdk/skills/` com README
5. Adicionar `procedures_data/agent_sdk/` ao `.gitignore`
6. Smoke test: invocar `run_claude_oneshot("smoke", "Diga olá em uma linha")` e validar audit trail

**Bloqueia:** todas as automações abaixo

### Fase 2 — Primeira automação real: Intent Drafter (§3)

Maior valor estratégico (auto-aprendizado do Tier 0). Implementar primeiro porque:
- Valida o padrão arquitetural completo
- Produz output verificável e idempotente
- Não tem dependência runtime (não precisa de Playwright nem SIGA/SEI live)

**Pré-requisito:** acumular ~50+ runs em `procedures.jsonl` para ter dados pra agrupar

### Fase 3 — Feedback Review Chat (§4)

Substitui o Streamlit. Maior impacto na produtividade do operador (você).

**Pré-requisito:** Fase 1 concluída

### Fase 4 — Classification Debugger (§5)

Pequeno, focado, alto valor. Recomendo fazer junto com Fase 3.

### Fase 5 — RAG Quality Auditor (§6)

Curar o `rag_ground_truth.yaml` é o passo mais demorado (humano decide as queries). Implementar quando o RAG estiver estável e quiser monitorar drift.

### Fase 6 — PROCEDURES Staleness Checker (§7)

Útil quando o playbook crescer (>30 intents). Hoje com 24, dá pra revisar manualmente.

### Fase 7 — Maintainer Tool polish (§8)

Slash commands + skills curados — incremental, conforme o uso real revelar atritos.

### Marco visual no TASKS.md

```
Marco IV (em andamento):
  ├─ SEI Selector Capture  ← BLOQUEANTE atual (SDD_SEI_SELECTOR_CAPTURE.md)
  ├─ Wire-up SEIWriter
  └─ Validação live

Marco V — Claude Code Automations (este SDD):
  ├─ Fase 1: Infra (agent_sdk/runner.py)
  ├─ Fase 2: Intent Drafter (a maior alavanca)
  ├─ Fase 3+4: Feedback Chat + Debugger (UX)
  ├─ Fase 5: RAG Auditor (qualidade)
  ├─ Fase 6: PROCEDURES Staleness (manutenção)
  └─ Fase 7: Maintainer polish (DX)
```

---

## 10. Anti-patterns — o que NÃO fazer

| Anti-pattern | Por quê |
|---|---|
| **Chamar `claude -p` dentro do nó LangGraph durante processamento de email** | Latência (~30s-2min), custo de quota Max, perda de determinismo, não-auditável. Nunca. |
| **Usar `claude-agent-sdk` Python package** | Vai pela API Anthropic, cobra por token, perde o ponto inteiro de usar o plano Max. |
| **Permitir que o agente edite `PROCEDURES.md` direto** | Bypassa revisão humana — risco de hallucination injetar regras erradas que vão para os emails dos alunos sem filtro. SEMPRE escrever em `PROCEDURES_CANDIDATES.md` e exigir promoção manual. |
| **Permitir que o agente toque `sei/writer.py` em runtime** | Mesma razão do path crítico — esse arquivo é a fronteira de safety, qualquer mudança passa por humano + testes regressivos. Em maintainer mode, OK editar (PR-style); em runtime de produção, NUNCA. |
| **Hardcodar prompts dentro dos `.py`** | Inflate o código + dificulta iteração. Briefings vão em `agent_sdk/skills/*.md`. |
| **Fazer cada automação reinventar audit/log** | Centralizar em `agent_sdk/runner.py` (§2.1). |
| **Confiar em output não-validado** | Sempre validar JSON output via Pydantic; texto livre deve ser tratado como sugestão, nunca como autoridade. |
| **Misturar credenciais de teste e produção no `.env`** | Para o SEI capture e similar, usar `.env.test` separado e carregar explicitamente via `load_dotenv(".env.test", override=True)`. |
| **Rodar automações sem audit trail** | Toda invocação de `claude -p` deve gerar pelo menos um JSONL row. |
| **Loop infinito de drafting** | Se o intent drafter ficar produzindo o mesmo candidato de novo (via hash), o sistema deve detectar e parar — não floodar `PROCEDURES_CANDIDATES.md`. |
| **Deprecar o Streamlit feedback UI** | O Feedback Chat (§4) é uma via *adicional*, não substituta. Streamlit continua sendo fallback obrigatório quando: quota Max esgotada, `claude` não autenticado, Anthropic offline, operador prefere clicar a digitar, batch triage visual. Os dois escrevem no mesmo `FeedbackStore`. |

---

## 11. Resumo executivo

**O que este SDD entrega:**
1. Um padrão arquitetural reutilizável para chamar `claude` CLI programaticamente sob plano Max (`agent_sdk/runner.py` + skills + audit)
2. 6 specs concretas de automação (intent drafter, feedback chat, classification debugger, RAG auditor, PROCEDURES staleness, maintainer polish)
3. Roadmap de adoção em 7 fases priorizadas
4. Lista de 10 anti-patterns a evitar

**O que fazer primeiro (próxima sessão dev, depois da SEI capture):**
1. Implementar a Fase 1 (infra) — ~1 sessão
2. Implementar a Fase 2 (Intent Drafter) — ~2 sessões com revisão dos primeiros candidatos

**Custo total estimado de operação (ano completo, todas as automações ativas):**
- Quota Max: dentro do plano (zero adicional)
- Tempo de revisão humana: ~15min/semana revisando candidatos do intent_drafter + ~30min/mês olhando reports do RAG auditor

**Valor esperado:**
- Tier 0 hit rate sobe ao longo do tempo (auto-aprendizado) → menos chamadas LiteLLM → menos custo MiniMax
- Qualidade de classificação melhora (feedback chat captura mais correções de qualidade)
- Menos bugs em produção (debugger + RAG auditor pegam regressões cedo)
- Onboarding de contribuidores acelerado (maintainer mode)

---

## Apêndice A — Comando rápido pra começar a Fase 1

```powershell
cd C:\Users\trabalho\Documents\automation\nanobotWork\nanobot
git pull origin dev
.\.venv\Scripts\Activate.ps1
claude
```

Dentro do Claude Code:
> Leia ufpr_automation/SDD_CLAUDE_CODE_AUTOMATIONS.md §2 e §9.Fase1.
> Implemente a Fase 1: criar ufpr_automation/agent_sdk/ com runner.py
> conforme o esqueleto da §2.1, schemas.py vazio, skills/README.md,
> testes em ufpr_automation/tests/test_agent_sdk_runner.py mockando
> subprocess.run, e atualizar .gitignore para procedures_data/agent_sdk/.
> Smoke test final: run_claude_oneshot em modo dry_run.

## Apêndice B — Mapa de dependências entre as automações

```
agent_sdk/runner.py (§2.1) ──┬─→ Intent Drafter (§3)
                              ├─→ Feedback Chat (§4)
                              ├─→ Classification Debugger (§5)
                              ├─→ RAG Auditor (§6)
                              ├─→ PROCEDURES Staleness (§7)
                              └─→ Maintainer polish (§8)

ProcedureStore ──→ Intent Drafter, Classification Debugger
FeedbackStore ───→ Feedback Chat, Classification Debugger
RAGRetriever ────→ Intent Drafter, RAG Auditor, Classification Debugger
PROCEDURES.md ───→ Intent Drafter (read), Staleness Checker (read)
                   (NUNCA write — sempre via PROCEDURES_CANDIDATES.md)
SEI_DOC_CATALOG ─→ Intent Drafter (read)
SOUL.md ─────────→ Staleness Checker, Intent Drafter (read)
Neo4j ───────────→ Staleness Checker (vigência de normas)
```
