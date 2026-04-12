# Intent Drafter — Briefing

> Contexto para o Claude Code CLI quando invocado por `agent_sdk/intent_drafter.py`.

## O que é Tier 0 vs Tier 1

- **Tier 0 (Playbook)**: intents YAML em `workspace/PROCEDURES.md`. Resolvem emails instantaneamente por keyword/semantic match — zero custo LLM.
- **Tier 1 (RAG + LLM)**: retrieval do LanceDB + classificação via LiteLLM. Funciona, mas custa tokens e leva ~5s por email.
- **Objetivo**: mover emails recorrentes de Tier 1 → Tier 0, criando intents de alta qualidade.

## Schema do Intent

Referência: `ufpr_automation/procedures/playbook.py:Intent` (Pydantic BaseModel)

Campos obrigatórios:
- `intent_name` (str, snake_case, único)
- `keywords` (list[str] — frases literais que aparecem nos emails)
- `categoria` (str — deve ser uma das categorias válidas: Estágios, Acadêmico / Matrícula, Acadêmico / Equivalência de Disciplinas, Acadêmico / Aproveitamento de Disciplinas, Acadêmico / Ajuste de Disciplinas, Diplomação / Diploma, Diplomação / Colação de Grau, Extensão, Formativas, Requerimentos, Urgente, Correio Lixo, Outros)
- `action` (str — "Redigir Resposta", "Abrir Processo SEI", "Encaminhar", etc.)

Campos opcionais com defaults:
- `required_fields` (list[str]) — campos que DEVEM estar presentes no email (ex: nome_aluno, grr)
- `sources` (list[str]) — normas que fundamentam a resposta
- `last_update` (str, YYYY-MM-DD)
- `confidence` (float, 0.0–1.0) — usar 0.5 se sem fonte confirmada
- `template` (str) — texto da resposta com placeholders [NOME_ALUNO], [GRR], [NUMERO_PROCESSO_SEI]
- `sei_action` ("none" | "create_process" | "append_to_existing")
- `sei_process_type` (str)
- `required_attachments` (list[str])
- `blocking_checks` (list[str] — nomes de checkers registrados em `procedures/checkers.py`)
- `despacho_template` (str)

## Como consultar o RAG

```bash
python -m ufpr_automation.rag.retriever "tema do cluster" --top-k 5
```

## Critérios de qualidade

1. Keywords devem ser **frases literais** que aparecem nos subjects/bodies — não genéricas
2. `confidence >= 0.85` apenas se há fonte normativa confirmada no RAG
3. `confidence = 0.5` + `sources: ["pendente_revisao_humana"]` se sem fonte
4. Template deve cobrir o caso mais comum do cluster
5. NÃO inventar leis/resoluções — só citar o que aparece no RAG ou SOUL.md
6. Se intent similar já existe, propor EXPANSÃO (novos keywords) ao invés de novo intent

## Anti-padrão crítico

**NÃO inventar fontes normativas.** Se o RAG não retorna uma resolução/lei relevante, marque:
```yaml
confidence: 0.5
sources:
  - "pendente_revisao_humana"
```

## Exemplo de bom intent

```intent
intent_name: estagio_nao_obrig_acuse_inicial
keywords:
  - "TCE inicial"
  - "termo de compromisso"
  - "estágio não obrigatório"
categoria: "Estágios"
action: "Abrir Processo SEI"
required_fields:
  - nome_aluno
sources:
  - "SOUL.md §8"
  - "Lei 11.788/2008"
last_update: "2026-04-10"
confidence: 0.92
template: "Prezado(a) [NOME_ALUNO], acusamos o recebimento do TCE e informamos que o processo SEI [NUMERO_PROCESSO_SEI] foi aberto para análise."
sei_action: create_process
sei_process_type: "Graduação/Ensino Técnico: Estágios não Obrigatórios"
required_attachments:
  - TCE_assinado
blocking_checks:
  - siga_matricula_ativa
  - data_inicio_retroativa
despacho_template: |
  Ao Setor,
  Encaminha-se o TCE de [NOME_ALUNO] (GRR[GRR]) para análise.
```

## Output esperado

Append em `workspace/PROCEDURES_CANDIDATES.md` com header de proveniência + hash.
Humano revisa e promove manualmente para `workspace/PROCEDURES.md`.
