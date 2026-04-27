# Plano: Expansão Tier 0, fix do role "procure a coordenação", e separação coordenação vs externo nas bases

> **Status (2026-04-27, fim do dia)**: Frentes 1, 2 e 3 **implementadas no código**, mais sessão de refinamento com o coordenador (intents adicionados/refatorados). Suite completa: **1013 passed**, suite Tier 0: **119 passed**.
>
> **34 intents novos em §12–§16** de `workspace/PROCEDURES.md` aguardando revisão final do coordenador (tags `[A REVISAR — 2026-04-27]` em cada seção). Checklist navegável: [`INTENTS_PARA_REVISAO.md`](INTENTS_PARA_REVISAO.md).
>
> **Pendências operacionais** (não-bloqueantes; rodar quando confirmado):
> - Backfill in-place LanceDB (`orgao_emissor` + `is_coordenacao` derivados do `caminho` já existente — minutos, não horas; não precisa re-extrair PDFs nem re-embedar).
> - Re-seed Neo4j (`seed --clear` + `enrich` — precisa do servidor `bolt://localhost:7687` ativo).
>
> **Tasks de engenharia futura** (3) registradas no fim do documento: `email_cc` no Intent, `siga_action: fetch_documento_por_grr`, ingestão do tutorial PROGRAP/UDIP no RAG.

## Context

O sistema `ufpr_automation` já roda Memória Híbrida (Tier 0 → Tier 1 RAG+LLM). Três sintomas/perguntas motivam este plano:

1. **Custo/eficiência**: o LLM está sendo chamado para perguntas que poderiam ser respondidas por scripts fechados (Tier 0). Vale empurrar a fronteira Tier 0 pra cima e deixar o RAG só para o que é genuinamente novo? **Sim** — cada hit Tier 0 vale ~ $0 vs $0,001–0,01 do Tier 1, elimina latência de embedding+LLM e (mais importante) elimina alucinação.
2. **Anti-padrão de role**: o LLM responde a alunos "procure/entre em contato com a Coordenação" — mas a Coordenação somos nós. Auditoria localizou os pontos exatos de vazamento.
3. **Separação coordenação vs externo nas bases**: hoje é parcial. Neo4j tem nó `:Orgao{sigla:'CCDG'}` mas sem aresta `EMITIDO_POR` nas normas/templates; LanceDB usa subpasta como proxy mas a pasta `estagio/` mistura Lei federal + Res CEPE + regulamento DG sem distinção. Não dá pra perguntar "documentos próprios da coordenação" via filtro hoje.

Outcome desejado:

- Tier 0 cobre ≥ 80% do volume mensal de emails (hoje cobre ~60%).
- Templates do agente nunca dizem "procure/contate a coordenação" — quando faltar info, pede diretamente ou encaminha pra **outro** setor.
- Toda peça (norma, doc, template) tem `orgao_emissor` e (no grafo) aresta `EMITIDO_POR`. Filtro `--orgao=CCDG` na CLI funciona.

---

## Diagnóstico — auditorias completas

### Auditoria 1 — Como o LLM entende o "role"

**System prompt assemblado em `ufpr_automation/llm/client.py:51-96` (`_build_system_instruction`)** — composição de 2 partes:

1. **`workspace/AGENTS.md:1-5`** — declaração de role:
   > "Você é um agente de automação burocrática especializado nos processos da Secretaria da Coordenação do Curso de Design Gráfico da Universidade Federal do Paraná (UFPR). Sua função principal é auxiliar na gestão de e-mails institucionais..."
   - Diz "agente" (autônomo), não "assistente" (helper). Bom.
2. **`workspace/SOUL_ESSENTIALS.md`** (versão slim, ~200 linhas) — identidade institucional, tom, categorias, contatos, regras críticas.
3. **Fallback**: se SOUL_ESSENTIALS.md não existir, injeta `SOUL.md` completo (718 linhas) + warning log.

**DSPy signatures** (`dspy_modules/signatures.py`):
- `EmailClassifier:12-22` — "Classifique um e-mail... redija uma resposta formal" (implícito: você é o respondente)
- `DraftCritic:51-57` — "Você é um revisor de correspondência institucional da UFPR." (autoridade sênior)

**Self-Refine critic** (`llm/client.py:297-320`) — 5 critérios atuais; nenhum verifica anti-padrão "procure a coordenação".

### Pontos de vazamento "procure a coordenação"

| # | Local | Severidade | Trigger |
|---|---|---|---|
| 1 | `workspace/PROCEDURES.md:378` (template `estagio_nao_obrig_pendencia`) | 🔴 Alta — template direto | Sempre que o intent dispara |
| 2 | `workspace/SOUL.md:576` ("Qualquer dúvida, entre em contato com a Coordenação...") | 🟡 Média — fallback | Se SOUL_ESSENTIALS.md sumir |
| 3 | `workspace/SOUL.md:618` ("contate a UE/COAPPE") | 🟢 OK — COAPPE é setor externo | — |
| 4 | `llm/client.py:_self_refine_async` | 🟡 Média — sem detecção | Drafts ruins passam Self-Refine |
| 5 | `dspy_modules/signatures.py:DraftCritic` | 🟡 Média — sem detecção | Idem para path DSPy |
| 6 | `workspace/SOUL_ESSENTIALS.md` (faltava regra) | 🟢 **Resolvido em 2026-04-27** | Guard explícito agora presente |

**Regra existente prévia** (referência): `SOUL_ESSENTIALS.md:165` já tinha "NUNCA diga ao aluno pra abrir processo SEI" — usa o mesmo formato `**NUNCA...**` que o novo guard.

### Auditoria 2 — Separação coordenação vs externo

| Local | Status |
|---|---|
| LanceDB metadata | ⚠️ Parcial — só pasta nível-1 (`design_grafico`/`cepe`/`estagio`/...). Sem campo `orgao_emissor`. |
| Pasta `estagio/` | 🔴 **Pior caso** — Lei 11.788 + Res 46/10-CEPE + regulamento DG misturados, todos com `conselho=estagio`. |
| Neo4j `:Orgao` | ✅ CCDG é nó próprio com sigla, email, endereço, subordinação clara |
| Neo4j `:Norma` | ⚠️ `Regulamento DG 2024` existe como nó mas sem aresta `EMITIDO_POR -> CCDG` |
| Neo4j `:Template` | ⚠️ Conteúdo cita Coordenação no texto mas sem aresta `EMITIDO_POR -> CCDG` |
| `base_conhecimento/` | ❌ Mix — `FichaDoCurso.txt`/`procedimentos.md` (DG) e `manual_sei.txt`/`manual_siga.txt` (UFPR-wide) sem distinção formal |

**Mapa autoritativo doc → órgão emissor** (para uso em Frente 3):

| Pasta / arquivo | `orgao_emissor` | Notas |
|---|---|---|
| `cepe/**` | `CEPE` | conselho |
| `coun/**` | `COUN` | conselho |
| `coplad/**` | `COPLAD` | conselho |
| `concur/**` | `CONCUR` | conselho |
| `design_grafico/**` | `CCDG` | coordenação local |
| `estagio/Lei*.pdf` | `MEC` | lei federal |
| `estagio/resolucaoCEPE_*.pdf` | `CEPE` | resolução |
| `estagio/regulamento_estagio-DesignGrafico.pdf` | `CCDG` | local |
| `estagio/manual-de-estagios-*.pdf` | `PROGRAP` | manual UFPR |
| `estagio/exemplo*.pdf` | `CCDG` | exemplo de despacho da coordenação |
| `estagio/Perguntas Frequentes - COAPPE*.pdf` | `COAPPE` | FAQ COAPPE |
| `sei_pop/**` | `UFPR` | POPs UFPR-wide |
| `ufpr_aberta/**` | `UFPR_ABERTA` | conteúdo Moodle |

### Auditoria 3 — Cobertura Tier 0 atual

Volume real (mar/2026, do `manual_sei.txt`):

| Categoria | Volume | Cobertura Tier 0 atual |
|---|---|---|
| Estágios não-obrig | 238 | ✅ 4 intents (acuse, aditivo, conclusão, pendência) |
| Informações e Documentos | 132 | ❌ 0 — cai sempre em Tier 1 |
| Registro de Diplomas | 62 | ✅ 1 intent (genérico) |
| Estágio Obrigatório | 60 | ⚠️ 1 intent (só matrícula) |
| Aproveitamento/Dispensa | 60 | ✅ 3 intents |
| Voluntariado | 42 | ✅ 1 intent |
| Matrículas | 30 | ⚠️ 1 intent (situação especial) |
| Expedição de Diploma | 23 | ✅ junto com diploma_registro |
| Trancamento/Destrancamento | 13 | ✅ 2 intents |
| Cancelamento Abandono | 12 | ✅ 1 |
| Cancelamento Prazo | 11 | ✅ 1 |
| Colação | 11+5+3 | ✅ 2 |
| FAQs estágio | (alta) | ✅ 6 intents |
| **Cobertura estimada hoje** | | **~ 60%** |

Buracos óbvios:
- 132 "Informações e Documentos" sem nenhum intent → maior dreno isolado de Tier 1.
- 60 Estágio Obrigatório com só 1 intent.
- 30 Matrículas com só 1 intent.
- Encaminhamentos triviais (PRAE, AUI, PRPPG, PROGEPE, SIBI) sem intent.

---

## Frente 1 — Expansão Tier 0 (custo/eficiência)

### Princípio

Tier 0 é o mecanismo correto para *qualquer* mensagem cuja resposta é determinística dado a categoria. Tier 1 (RAG+LLM) é a *exceção*, não a regra. O custo do RAG (embedding da query + retrieval + LLM call) só se justifica quando há ambiguidade real ou interpretação de norma.

Tier 0 já suporta tudo o que precisamos:
- `keywords` (regex score 1.0) + match semântico e5-large (cosine ≥ 0.90)
- `required_fields` + `extract_variables` (regex em `playbook.py`)
- `llm_extraction_fields` para texto livre (LLM bounded, sem RAG — ver `estagio_nao_obrig_pendencia`)
- `template` com placeholders `[CAMPO]` e `{{ jinja }}`
- `sei_action` opcional para fluxos com escrita SEI
- `blocking_checks` para validações
- `last_update` + staleness check vs RAG mtime

Não precisa mudar engine. Precisa **autorar mais intents**.

### Lista priorizada de novos intents (~25)

#### Bloco A — Informações e Documentos (132 emails/mês, ROI máximo)

| intent_name | gatilhos | template gera | encaminha pra |
|---|---|---|---|
| `info_declaracao_matricula` | "declaração de matrícula", "comprovante de matrícula" | passo a passo SIGA | — (auto-serviço SIGA) |
| `info_declaracao_vinculo` | "declaração de vínculo", "atestado de vínculo" | idem | — |
| `info_declaracao_provavel_formando` | "provável formando", "vou formar" | regras + canal | — |
| `info_atestado_frequencia` | "atestado de frequência", "abono de falta" | encaminhar professor | professor da disciplina |
| `info_historico_escolar` | "histórico escolar", "histórico parcial" | SIGA self-service | — |
| `info_2via_diploma` | "segunda via de diploma", "perdi o diploma" | encaminhar | PROGRAP |
| `info_horario_atendimento_secretaria` | "horário da secretaria", "quando atendem" | resposta direta | — |
| `info_endereco_coordenacao` | "onde fica a coordenação", "endereço" | resposta direta | — |
| `info_ementa_disciplina` | "ementa de", "programa da disciplina" | link sacod + PPC | — |
| `info_quem_e_coordenadora` | "quem é a coordenadora" | resposta direta (Stephania) | — |

#### Bloco B — Encaminhamentos puros (atalhos baratos)

| intent_name | gatilhos | encaminha pra |
|---|---|---|
| `enc_bolsas_assistencia_estudantil` | "bolsa permanência", "auxílio moradia", "bolsa PRAE" | PRAE |
| `enc_intercambio` | "intercâmbio", "mobilidade", "estudar fora" | AUI |
| `enc_iniciacao_cientifica` | "iniciação científica", "como ser bolsista IC", "quero pesquisar" | PRPPG + orientador |
| `enc_monitoria` | "monitoria", "ser monitor" | edital semestral |
| `enc_biblioteca_quitacao` | "quitação SIBI", "débito biblioteca" | SIBI |
| `enc_carteirinha_estudante` | "carteirinha", "RU", "restaurante universitário" | PRAE/RU |
| `enc_psicologico_naa` | "atendimento psicológico", "saúde mental" | NAA / PRAE |

#### Bloco C — Estágio Obrigatório (60, expandir)

| intent_name | gatilhos | template / fluxo |
|---|---|---|
| `estagio_obrig_tce_inicial` | "TCE estágio obrigatório", "começar estágio supervisionado" | parecido com não-obrig mas tipo SEI diferente |
| `estagio_obrig_relatorio_parcial` | "relatório parcial", "6 meses estágio" | acuse + anexa SEI |
| `estagio_obrig_defesa_avaliacao` | "banca de estágio", "defesa supervisionado" | regras de defesa |
| `estagio_obrig_lancamento_nota` | "nota do estágio supervisionado" | encaminha COE |
| `estagio_obrig_ic_substituicao_fluxo` | (já existe FAQ; criar fluxo SEI) | abre processo COE |

#### Bloco D — Matrículas (30, expandir)

| intent_name | gatilhos | template |
|---|---|---|
| `matricula_isolada` | "disciplina isolada", "aluno especial" | regras + edital |
| `matricula_ajuste_periodo` | "ajuste de matrícula", "trocar disciplina" | passo SIGA |
| `matricula_mobilidade_estrangeiro` | "matrícula mobilidade", "estudante estrangeiro" | encaminha AUI + colegiado |
| `matricula_provar` | "PROVAR" | regras |

#### Bloco E — Acadêmico geral

| intent_name | gatilhos | template |
|---|---|---|
| `tcc_regras_gerais` | "TCC", "trabalho de conclusão" | PPC + regulamento curso |
| `afc_atividades_validas` | "atividades formativas", "AFC", "horas complementares" | tabela AFC + link sacod |
| `mudanca_curriculo_2016_2020` | "mudar de currículo", "currículo 2020" | regras + colegiado |
| `calendario_academico` | "quando começa o semestre", "calendário acadêmico" | link PROGRAP |
| `enade` | "ENADE", "prova ENADE" | regras + link |

### Estimativa de cobertura após expansão

| Estado | Tier 0 hits | Tier 1 fallback |
|---|---|---|
| Hoje | ~60% | ~40% |
| Após Bloco A+B (10 intents simples) | ~75% | ~25% |
| Após Bloco A+B+C+D+E (~25 intents) | ~85% | ~15% |

Cada intent autorado é um **custo único** (autoria humana ~30 min usando manual_sei.txt + template) que retorna em **toda chamada futura daquela categoria** — savings cumulativos diários.

### Trabalho concreto Frente 1

1. **Autoria**: adicionar os blocos A→E em `ufpr_automation/workspace/PROCEDURES.md`. Cada bloco vira uma seção `## §N` com um ou mais ` ```intent ` blocks. Seguir o esqueleto dos intents existentes (`intent_name`, `keywords`, `categoria`, `action`, `required_fields`, `sources`, `last_update`, `confidence`, `template`).
2. **Embeddings**: nada a fazer. `playbook.py:get_playbook()` recomputa embeddings na 1ª chamada (lru_cache singleton).
3. **Validação por intent**: criar 1-2 emails de fixture para cada novo intent em `tests/fixtures/tier0_emails/` (texto cru) e adicionar em `tests/test_playbook.py` um caso `test_intent_<nome>_routes_correctly` que verifica `score >= 0.90` e `template != None`.
4. **Bench de cobertura**: rodar `python -m ufpr_automation --channel gmail --schedule --once` em batch de teste de 50 emails reais (após autorar Bloco A) e medir `tier0_hits / total`. Meta: ≥ 75% após Bloco A+B; ≥ 85% após todos os blocos.

---

## Frente 2 — Travar o anti-padrão "procure a coordenação"

### 2.1 — `workspace/SOUL_ESSENTIALS.md` ✅ FEITO em 2026-04-27

Bloco novo adicionado após `:165` ("NUNCA diga ao aluno pra abrir processo SEI..."):

```markdown
## Você É a Coordenação — anti-padrão de auto-referência (CRÍTICO)

**NUNCA diga ao remetente "entre em contato com a Coordenação", "procure
a Coordenação", "consulte a Coordenação", "consulte a Secretaria do Curso"
ou variações.** Você **É** a Coordenação do Curso de Design Gráfico. [...]

Frases proibidas: ❌ "Em caso de dúvidas, entre em contato com a Coordenação"
                   ❌ "Procure a Coordenação para mais detalhes"
                   ❌ "Consulte a Secretaria do Curso"
                   ❌ "Entre em contato com a Coordenação ou diretamente com a COAPPE"

Substituições corretas: ✅ "Em caso de dúvidas, responda este e-mail."
                         ✅ "...a COAPPE atende em estagio@ufpr.br ou (41) 3310-2706."
                         ✅ "...contate a PRAE em prae@ufpr.br."
                         ✅ "Para mobilidade internacional, contate a AUI em https://internacional.ufpr.br."
```

### 2.2 — `workspace/SOUL.md` (PENDENTE)

- Adicionar mesmo bloco no início (após identificação institucional, ~linha 50). Garante que mesmo no fallback completo a regra é injetada.
- Editar `:576` ("Qualquer dúvida, entre em contato com a Coordenação ou diretamente com a UE/COAPPE...") para tirar a Coordenação. Manter UE/COAPPE.
- `:618` ("contate a UE/COAPPE") está OK — COAPPE é setor externo.

### 2.3 — `workspace/PROCEDURES.md` (PENDENTE)

Varredura `grep -n "entre em contato com a Coordenação\|procure a Coordenação\|consulte a Coordenação"` confirmou apenas 1 hit a corrigir:

- **`:378-379`** em `estagio_nao_obrig_pendencia.template`:
  - **Atual**: "Em caso de dúvidas, entre em contato com a Coordenação ou diretamente com a COAPPE pelo e-mail estagio@ufpr.br ou telefone (41) 3310-2706."
  - **Substituir por**: "Em caso de dúvidas, responda este e-mail. Para falar diretamente com a COAPPE: estagio@ufpr.br · (41) 3310-2706."
  - Atualizar `last_update` do intent para `2026-04-27`.

### 2.4 — `ufpr_automation/llm/client.py:297-320` (PENDENTE)

Em `_self_refine_async`, adicionar critério #6 ao critique_prompt:

```python
"6. A resposta NÃO contém o anti-padrão \"procure/entre em contato com/consulte a Coordenação\"? "
"   (Você É a Coordenação; nunca delegar a si mesmo.) "
```

### 2.5 — `ufpr_automation/dspy_modules/signatures.py:51-57` (PENDENTE)

`DraftCritic` docstring — adicionar regra:

```python
"""Avalie criticamente um rascunho de resposta institucional da UFPR.

Verifique se a resposta cita a norma correta, se o tom é adequado para
correspondência oficial, se a classificação está correta, se a resposta
atende à demanda do remetente, se há erros factuais, e se a resposta
NÃO contém o anti-padrão "procure/entre em contato com/consulte a
Coordenação" (o agente É a Coordenação; nunca delegar a si mesmo).
"""
```

Recompilar prompt DSPy se necessário (`python -m ufpr_automation.dspy_modules.optimize --strategy gepa`).

### 2.6 — Teste de regressão (PENDENTE)

`tests/test_anti_self_referral.py`:

```python
@pytest.mark.parametrize("intent_name", get_playbook().list_intent_names())
def test_intent_template_does_not_self_refer(intent_name):
    intent = get_playbook().get(intent_name)
    forbidden = ["procure a Coordenação", "entre em contato com a Coordenação",
                 "consulte a Coordenação", "consulte a Secretaria"]
    for phrase in forbidden:
        assert phrase.lower() not in intent.template.lower(), \
            f"Intent {intent_name} contém anti-padrão de auto-referência: {phrase}"
```

---

## Frente 3 — Separação coordenação vs externo nas bases (PENDENTE)

### 3.1 — Adicionar campo `orgao_emissor` no metadata RAG

**`ufpr_automation/rag/ingest.py:114-143`** (`metadata_from_path`) — adicionar mapeamento:

```python
_ORGAO_EMISSOR_MAP = {
    "cepe": "CEPE",
    "coun": "COUN",
    "coplad": "COPLAD",
    "concur": "CONCUR",
    "design_grafico": "CCDG",
    "sei_pop": "UFPR",
    "ufpr_aberta": "UFPR_ABERTA",
}

_ESTAGIO_FILENAME_PATTERNS = [
    (re.compile(r"^Lei", re.I), "MEC"),
    (re.compile(r"resolucaoCEPE", re.I), "CEPE"),
    (re.compile(r"DesignGrafico|design.grafico", re.I), "CCDG"),
    (re.compile(r"manual-de-estagios", re.I), "PROGRAP"),
    (re.compile(r"^Perguntas Frequentes.*COAPPE", re.I), "COAPPE"),
    (re.compile(r"^exemplo", re.I), "CCDG"),
]

def _infer_orgao_emissor(rel_path: Path) -> str:
    parts = rel_path.parts
    if not parts:
        return "DESCONHECIDO"
    top = parts[0].lower()
    if top in _ORGAO_EMISSOR_MAP:
        return _ORGAO_EMISSOR_MAP[top]
    if top == "estagio":
        for pat, orgao in _ESTAGIO_FILENAME_PATTERNS:
            if pat.search(rel_path.name):
                return orgao
        return "DESCONHECIDO"
    return "DESCONHECIDO"
```

E no metadata do chunk:

```python
metadata["orgao_emissor"] = _infer_orgao_emissor(rel_path)
metadata["is_coordenacao"] = metadata["orgao_emissor"] == "CCDG"
```

### 3.2 — Filtros novos na CLI do retriever

**`ufpr_automation/rag/retriever.py:91-139`** — adicionar parâmetros `orgao` e `only_coordenacao`:

```python
def search(query, conselho=None, tipo=None, orgao=None, only_coordenacao=False, top_k=10):
    where_clauses = []
    if conselho: where_clauses.append(f"conselho = '{conselho}'")
    if tipo: where_clauses.append(f"tipo = '{tipo}'")
    if orgao: where_clauses.append(f"orgao_emissor = '{orgao}'")
    if only_coordenacao: where_clauses.append("is_coordenacao = true")
```

E na CLI: `--orgao CCDG`, `--only-coordenacao`.

### 3.3 — Re-ingestão LanceDB

```bash
# fluxo Windows correto (já documentado em CLAUDE.md):
cp -r "G:/Meu Drive/ufpr_rag/store/ufpr.lance" "C:/Users/trabalho/rag_store_local/"
RAG_STORE_DIR="C:/Users/trabalho/rag_store_local" python -m ufpr_automation.rag.ingest
MSYS_NO_PATHCONV=1 robocopy "C:\Users\trabalho\rag_store_local\ufpr.lance" "G:\Meu Drive\ufpr_rag\store\ufpr.lance" /E /COPY:DAT /R:3 /W:5
```

Re-ingest é necessário porque LanceDB schema é fixado por chunk → adicionar campo novo requer reescrever a tabela.

### 3.4 — Arestas no Neo4j

**`ufpr_automation/graphrag/seed.py`**:

- Em `_seed_orgaos:115-184`: adicionar nó `:Orgao{sigla:'MEC', nome:'Ministério da Educação'}` se ainda não existe.
- Em `_seed_normas:327-361`: criar arestas `(:Norma)-[:EMITIDO_POR]->(:Orgao)`:

```cypher
MATCH (n:Norma {codigo: 'Lei 11.788/2008'}), (o:Orgao {sigla: 'MEC'})
MERGE (n)-[:EMITIDO_POR]->(o);

MATCH (n:Norma {codigo: 'Resolução 46/10-CEPE'}), (o:Orgao {sigla: 'CEPE'})
MERGE (n)-[:EMITIDO_POR]->(o);

MATCH (n:Norma {codigo: 'Regulamento DG 2024'}), (o:Orgao {sigla: 'CCDG'})
MERGE (n)-[:EMITIDO_POR]->(o);
```

- Em `_seed_templates:645-773`: ligar templates a CCDG:

```cypher
MATCH (t:Template), (o:Orgao {sigla: 'CCDG'})
WHERE t.despacho_tipo IN ['tce_inicial', 'aditivo', 'rescisao']
MERGE (t)-[:EMITIDO_POR]->(o);
```

### 3.5 — Re-seed Neo4j

```bash
python -m ufpr_automation.graphrag.seed --clear
python -m ufpr_automation.graphrag.enrich
```

### 3.6 — `find_normas_by_orgao` no retriever GraphRAG

**`ufpr_automation/graphrag/retriever.py`** — adicionar método que retorna normas com `EMITIDO_POR -> {sigla}`. Usar para queries do tipo "documentos próprios da coordenação".

---

## Ordem de execução proposta (sprint quando retomar)

| Dia | Frente | Atividade | Risco |
|---|---|---|---|
| 1 | 2 | ✅ FEITO: SOUL_ESSENTIALS.md guard | — |
| 1 | 2 | SOUL.md + PROCEDURES.md (varredura "entre em contato com a Coordenação") | Baixo |
| 1 | 2 | client.py:_self_refine_async critério 6 + DraftCritic docstring | Baixo |
| 1 | 2 | `tests/test_anti_self_referral.py` | Baixo |
| 2 | 1 | Bloco A (info_*) — 10 intents — em PROCEDURES.md + fixtures | Baixo |
| 2 | 1 | Bench de cobertura batch 50 emails | Sem impacto produção |
| 3 | 1 | Bloco B (enc_*) — 7 intents | Baixo |
| 3 | 1 | Bloco C+D+E — 8 intents | Baixo |
| 4 | 3 | Editar `rag/ingest.py` + `retriever.py` (campos + filtros) | Médio |
| 4 | 3 | Cópia local store, re-ingest com novo schema | Médio (volume de dados) |
| 5 | 3 | Editar `graphrag/seed.py` + adicionar nó MEC + arestas EMITIDO_POR | Médio |
| 5 | 3 | `seed --clear` + `enrich` | Reversível |
| 5 | 3 | Verificação E2E (queries de filtro) | — |
| 6 | 1+2 | Bench final em batch 100 emails reais | — |

## Critical files (ponteiros)

- `ufpr_automation/workspace/PROCEDURES.md` — onde adicionar intents Tier 0
- `ufpr_automation/workspace/SOUL_ESSENTIALS.md:165-184` ✅ guard "NUNCA diga 'procure a coordenação'" já presente
- `ufpr_automation/workspace/SOUL.md:576` — frase a editar (e adicionar guard ~linha 50)
- `ufpr_automation/llm/client.py:297-320` — Self-Refine critic prompt (adicionar critério 6)
- `ufpr_automation/dspy_modules/signatures.py:51-57` — DraftCritic docstring
- `ufpr_automation/rag/ingest.py:114-143` — `metadata_from_path` (adicionar `orgao_emissor`)
- `ufpr_automation/rag/retriever.py:91-139` — `search()` (adicionar filtros)
- `ufpr_automation/graphrag/seed.py:115-184,327-361,645-773` — `_seed_orgaos`, `_seed_normas`, `_seed_templates` (adicionar arestas)
- `ufpr_automation/procedures/playbook.py` — engine Tier 0 (não muda)

## Verificação E2E quando retomar

1. **Frente 2 — anti-self-referral**:
   - `pytest tests/test_anti_self_referral.py -v` (passa para todos os intents)
   - Rodar pipeline em 5 emails reais que cairiam em Tier 1, ler drafts gerados, verificar zero ocorrências de "procure/contate/consulte a Coordenação".

2. **Frente 1 — cobertura Tier 0**:
   - `python -m ufpr_automation --channel gmail --limit 50` em ambiente de teste
   - Logs do `tier0_lookup`: `tier0_hits / total ≥ 0.85` após autoria completa.
   - Tempo médio por email cai (Tier 0 é ms; Tier 1 é segundos).

3. **Frente 3 — separação CCDG**:
   - `python -m ufpr_automation.rag.retriever "estágio" --orgao CCDG` retorna ≥ 3 chunks de regulamento DG / ficha do curso.
   - `python -m ufpr_automation.rag.retriever "estágio" --orgao CEPE` retorna ≥ 3 chunks de Res 46/10.
   - Cypher: `MATCH (n:Norma)-[:EMITIDO_POR]->(o {sigla:'CCDG'}) RETURN n` retorna `Regulamento DG 2024` no mínimo.
   - Cypher: `MATCH (t:Template)-[:EMITIDO_POR]->(o {sigla:'CCDG'}) RETURN t` retorna 3 templates de despacho.

4. **Bench global**:
   - `python -m ufpr_automation.aflow.cli --topologies fleet --limit 20` antes vs depois — accuracy não regride, latência média melhora.

---

## Histórico

- **2026-04-27 (manhã)** — Plano aprovado. Iniciada Frente 2: guard "procure a coordenação" adicionado em `SOUL_ESSENTIALS.md` (após `:165`).
- **2026-04-27 (tarde)** — Execução continuada e completada (código). Resumo:

### Frente 2 ✅ código completo
- [`SOUL_ESSENTIALS.md`](workspace/SOUL_ESSENTIALS.md) — guard "Você É a Coordenação — anti-padrão de auto-referência (CRÍTICO)" após bloco "NUNCA diga ao aluno pra abrir processo SEI". Lista frases proibidas + substituições corretas.
- [`SOUL.md`](workspace/SOUL.md) — mesmo guard adicionado após "Regras de Comunicação"; linha 576 ("entre em contato com a Coordenação ou diretamente com a UE/COAPPE") substituída por "responda este e-mail. Para falar diretamente com a UE/COAPPE...".
- [`PROCEDURES.md:378`](workspace/PROCEDURES.md) — template do `estagio_nao_obrig_pendencia` corrigido. `last_update` atualizado para `2026-04-27`.
- [`llm/client.py:_self_refine_async`](llm/client.py) — adicionado critério #6 ao critique_prompt: detecta anti-padrão "procure/contate a Coordenação" e força refinamento.
- [`dspy_modules/signatures.py`](dspy_modules/signatures.py) — atualizadas docstrings de `EmailClassifier` (preventivo na origem) e `DraftCritic` (detecção crítica).
- [`tests/test_anti_self_referral.py`](tests/test_anti_self_referral.py) — novo teste parametrizado por intent. **61 passed** (templates + despacho_template).

### Frente 1 ✅ código completo
- [`PROCEDURES.md`](workspace/PROCEDURES.md) §12–§16 — **25 intents novos** (29 templates contando 4 despachos SEI):
  - **§12 Informações e Documentos** (10): `info_declaracao_matricula`, `info_declaracao_vinculo`, `info_declaracao_provavel_formando`, `info_atestado_frequencia`, `info_historico_escolar`, `info_2via_diploma`, `info_horario_atendimento_secretaria`, `info_endereco_coordenacao`, `info_ementa_disciplina`, `info_quem_e_coordenadora`.
  - **§13 Encaminhamentos** (7): `enc_bolsas_assistencia_estudantil`, `enc_intercambio`, `enc_iniciacao_cientifica`, `enc_monitoria`, `enc_biblioteca_quitacao`, `enc_carteirinha_estudante_ru`, `enc_atendimento_psicologico_naa`.
  - **§14 Estágio Obrigatório** (5): `estagio_obrig_tce_inicial` (com despacho SEI), `estagio_obrig_relatorio_parcial` (com despacho), `estagio_obrig_defesa_avaliacao`, `estagio_obrig_lancamento_nota`, `estagio_obrig_ic_substituicao_fluxo` (com despacho).
  - **§15 Matrículas** (4): `matricula_disciplina_isolada`, `matricula_ajuste_periodo`, `matricula_mobilidade_estrangeiro`, `matricula_provar`.
  - **§16 Acadêmicos gerais** (5): `tcc_regras_gerais`, `afc_atividades_validas`, `mudanca_curriculo_2016_para_2020`, `calendario_academico`, `enade`.
- Validação: **66 passed** em `test_playbook.py + test_tier0_lookup.py`. Anti-self-referral nos novos templates: **61 passed** (todos limpos).
- Cobertura Tier 0 esperada: ~85% (vs ~60% antes).

### Frente 3 ✅ código completo (operações pendentes)
- [`rag/ingest.py`](rag/ingest.py) — novas funções `_ORGAO_EMISSOR_MAP`, `_ESTAGIO_FILENAME_PATTERNS`, `_infer_orgao_emissor`. Schema do chunk inclui `orgao_emissor` (string) + `is_coordenacao` (bool).
- [`rag/retriever.py`](rag/retriever.py) — parâmetros `orgao` e `only_coordenacao` em `search()`/`search_formatted()`; flags CLI `--orgao` e `--only-coordenacao`. `SearchResult` ganhou esses campos com defaults backward-compat.
- [`tests/test_rag_orgao_emissor.py`](tests/test_rag_orgao_emissor.py) — **17 mappings testados** (cepe/coun/coplad/concur/design_grafico/sei_pop/ufpr_aberta + 6 patterns de filename em estagio/ + 2 desconhecidos).
- [`graphrag/seed.py`](graphrag/seed.py) — adicionado nó `:Orgao{sigla:'MEC'}`. `_seed_normas` agora cria arestas `(:Norma)-[:EMITIDO_POR]->(:Orgao)` para 9 normas (Lei 11.788, CNE/CES, 6× CEPE, 1× PROGRAP, 1× CCDG). `_seed_templates` cria `(:Template)-[:EMITIDO_POR]->(:Orgao{sigla:'CCDG'})` em massa.
- [`graphrag/retriever.py`](graphrag/retriever.py) — métodos públicos `find_normas_by_orgao(sigla)`, `find_templates_by_orgao(sigla)`, `find_normas_da_coordenacao()`.

### Suite completa
**1013 passed, 49 skipped, 0 failed** em `pytest ufpr_automation/tests/` (≈66s).

### Pendências operacionais

1. **Re-ingest LanceDB** (custoso — ~3.3k PDFs, precisa do fluxo Windows correto):
   ```bash
   cp -r "G:/Meu Drive/ufpr_rag/store/ufpr.lance" "C:/Users/trabalho/rag_store_local/"
   RAG_STORE_DIR="C:/Users/trabalho/rag_store_local" \
     "/c/Users/trabalho/Documents/automation/nanobotWork/nanobot/.venv/Scripts/python.exe" \
     -m ufpr_automation.rag.ingest
   MSYS_NO_PATHCONV=1 robocopy "C:\Users\trabalho\rag_store_local\ufpr.lance" \
     "G:\Meu Drive\ufpr_rag\store\ufpr.lance" /E /COPY:DAT /R:3 /W:5
   ```
   Como `orgao_emissor` e `is_coordenacao` são colunas novas, o LanceDB precisa de re-ingest **completo**. O retriever já tem fallback (`has_orgao_col`/`has_is_coord_col`) que retorna defaults para chunks antigos durante a transição.

2. **Re-seed Neo4j** (precisa do servidor `bolt://localhost:7687` ativo):
   ```bash
   .venv/Scripts/python.exe -m ufpr_automation.graphrag.seed --clear
   .venv/Scripts/python.exe -m ufpr_automation.graphrag.enrich
   ```

3. **Verificação E2E** após as duas operações:
   - `python -m ufpr_automation.rag.retriever "regulamento de estágio" --orgao CCDG --top-k 5` → deve retornar `regulamento_estagio-DesignGrafico.pdf` + `FichaDoCurso.pdf`.
   - `python -m ufpr_automation.rag.retriever "estágio" --only-coordenacao` → só docs CCDG.
   - Cypher: `MATCH (n:Norma)-[:EMITIDO_POR]->(o:Orgao {sigla:'CCDG'}) RETURN n.codigo` → `Regulamento DG 2024`.
   - Cypher: `MATCH (t:Template)-[:EMITIDO_POR]->(o:Orgao {sigla:'CCDG'}) RETURN count(t)` → todos os templates.

### Próximos passos sugeridos (fora deste sprint)
- **Bench A/B**: rodar `python -m ufpr_automation.aflow.cli --topologies fleet --limit 20` antes (linha de base já está nos logs) vs depois das operações; medir se `tier0_hits/total` subiu para ≥0.85 e se zero drafts contêm "procure a Coordenação".
- **Recompilar DSPy** com prompts atualizados (`python -m ufpr_automation.dspy_modules.optimize --strategy gepa`) quando houver corpus de feedback ≥20.
- **Fixtures por intent novo**: criar 1–2 emails reais em `ufpr_automation/tests/fixtures/tier0_emails/` para os 25 intents novos e adicionar testes `test_intent_<nome>_routes_correctly` em `test_playbook.py`.

---

### Sessão de refinamento 2026-04-27 (revisão coordenador)

Após a autoria inicial, sessão interativa com o coordenador refinou vários intents e adicionou novos. Estado final:

**Total de intents Tier 0**: 24 originais + **34 novos** (originalmente 31 + 3 adicionados a pedido).

**Intents adicionados a pedido do coordenador**:

- **`enc_reserva_sala`** (§13) — reservas de salas/auditórios/laboratórios são do DDESIGN (`design@ufpr.br`), não da Coordenação. Template começa com `[INSTRUÇÃO PARA O REVISOR: enviar com CÓPIA (CC) para design@ufpr.br]` (CC manual até `email_cc` ser wirado).
- **`info_certificado_conclusao`** (§12) — certificado de conclusão **descontinuado** com a adoção do diploma digital. Mesma lógica de 4 cenários do `info_historico_escolar`.
- **`info_diploma_digital_acesso`** (§12) — intent dedicado: passo a passo SIGA → perfil "Discente Egresso da Graduação" → menu Diploma → Visualizar → 4 arquivos (XML+PDF Diploma, XML+PDF Histórico). Único intent que carrega URLs do PROGRAP/UDIP no corpo do email (https://prograp.ufpr.br/udip/ + tutorial PDF). Fonte: `Tutorial-Diploma-Digital-Perfil-Egresso.pdf`.

**Intents refatorados a pedido do coordenador**:

- **`enc_ementa_ficha_disciplina`** (substitui `info_ementa_disciplina`) — corrigiu o framing: ementas estão hospedadas em `https://sacod.ufpr.br/coordesign/grade-curricular-grafico/` mas a **responsabilidade é dos Departamentos**, não da Coordenação. Keywords expandidas (ficha 01, programa, plano de ensino). Template traz instrução pro revisor adicionar CC manual ao DDESIGN.
- **`info_declaracao_provavel_formando`** — corrigiu framing inicial errôneo (que dizia "Coordenação prepara em 3 dias úteis"). Agora 2 casos: (A) aluno ativo → self-service via SIGA Documentos→Gerar; (B) já colou ou perdeu acesso → Coordenação gera via SIGA-Secretaria (passo a passo no bloco do revisor).
- **`info_historico_escolar`** — reescrito com **4 cenários**: (1) ativo/trancado/mobilidade → self-service via Portal de Sistemas → SIGA → Documentos → Gerar; (2) egresso ≥2023 com diploma digital → resposta enxuta "está no mesmo lugar do diploma digital" (detalhes em `info_diploma_digital_acesso`); (3) egresso/evadido ≥2021 → Coordenação OU PROGRAD; (4) egresso/evadido <2021 (ou formado <2005, com diploma) → exclusivamente atendimento@ufpr.br.

**Outras correções**:

- **`afc_atividades_validas`** — link `https://sacod.ufpr.br/coordesign/atividades-formativas-complementares-dg/` confirmado pelo coordenador.
- **`estagio_nao_obrig_pendencia`** (template antigo) — removido "entre em contato com a Coordenação"; substituído por "responda este e-mail. Para falar diretamente com a COAPPE: estagio@ufpr.br".

**Tasks de engenharia consolidadas (futuro)**:

1. **`email_cc` no `Intent`** — wirar campo `email_cc: list[str]` em `procedures/playbook.py:Intent`, propagar via `tier0_lookup` e fazer `gmail/client.py:save_draft` aplicar CC. Hoje 2 intents (`enc_reserva_sala`, `enc_ementa_ficha_disciplina`) usam instrução manual ao revisor.
2. **`siga_action: fetch_documento_por_grr`** — wirar em `siga/client.py` parametrizável por `doc_type` (`historico_escolar`, `declaracao_provavel_formando`, `declaracao_conclusao`). Discente → Consultar → buscar GRR/nome → aba Documentos → Gerar → download → anexar ao rascunho. Hoje 3 intents (`info_declaracao_provavel_formando`, `info_historico_escolar` Caso 3, `info_certificado_conclusao` Caso 3) executam via revisor humano.
3. **Ingestão do tutorial PROGRAP/UDIP no RAG** — copiar `Tutorial-Diploma-Digital-Perfil-Egresso.pdf` para `G:/Meu Drive/ufpr_rag/docs/` (subset apropriado) para que o RAG cubra o detalhe se algum email cair em Tier 1.

**Pontos de atenção pendentes de confirmação** (8 itens) — ver [`INTENTS_PARA_REVISAO.md`](INTENTS_PARA_REVISAO.md): telefone PRAE, janela edital PIBIC, PROGRAP vs PROGRAD em monitoria, nome exato do tipo SEI estágio obrigatório, COE vs Colegiado em IC-substitui-estágio, número da Res 91/14-CEPE PROVAR, menu "Regularidade ENADE" no SIGA, prazo de "5 dias úteis" em atestado frequência.

**Suite final**: `pytest tests/test_anti_self_referral.py tests/test_playbook.py` → **119 passed** (template + despacho), incluindo todos os intents novos/refinados.

**Checklist de revisão**: [`INTENTS_PARA_REVISAO.md`](INTENTS_PARA_REVISAO.md) — 34 intents novos com link `PROCEDURES.md:linha` para cada um e checkboxes para o coordenador marcar à medida que aprova.
