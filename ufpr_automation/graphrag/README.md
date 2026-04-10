# GraphRAG — Grafo de Conhecimento Institucional (Marco III)

Módulo que modela o conhecimento burocrático da UFPR em um grafo Neo4j, complementando o RAG vetorial (LanceDB) com relações estruturadas entre entidades institucionais.

## Filosofia

- **Grafo = estado atual** — reflete a legislação vigente, hierarquia organizacional e fluxos de trabalho em vigor
- **RAG vetorial = arquivo histórico** — contém o texto integral de todas as versões (34.285 chunks, 3.316 PDFs)
- Cada nó `Norma` no grafo tem `fonte_rag` (nome do PDF) para rastrear a origem no banco vetorial
- Relações `ALTERA`, `REVOGA`, `CONSOLIDADA_EM` permitem seguir a linhagem completa de uma norma

## Arquitetura

```
graphrag/
├── __init__.py
├── client.py       # Wrapper do driver Neo4j (connect, query, health check)
├── schema.py       # Tipos de nó, relações, constraints, full-text index
├── seed.py         # Popula grafo com conhecimento base (SOUL.md, manuais SEI/SIGA)
├── enrich.py       # Extrai normas do RAG vetorial e insere com linhagem
├── retriever.py    # Retrieval graph-aware para o pipeline de email
└── README.md       # Este arquivo
```

## Modelo do Grafo

### Tipos de Nó (Labels)

| Label | Quantidade | Descrição | Propriedades-chave |
|-------|-----------|-----------|-------------------|
| `Norma` | ~1.600 | Resolução, Lei, IN, Ad Referendum | `codigo`, `status`, `fonte_rag`, `alterada_por`, `revogada_por` |
| `Etapa` | 47 | Passo de um fluxo de trabalho | `id`, `descricao`, `ordem` |
| `Orgao` | 21 | Unidade organizacional | `sigla`, `nome`, `email`, `telefone` |
| `TipoProcesso` | 20 | Tipo de processo SEI | `nome`, `frequencia` |
| `Template` | 15 | Template de email ou despacho SEI. Após Marco III, os 3 templates de despacho SEI também carregam `conteudo` + `despacho_tipo`, servidos em runtime via `graphrag/templates.py:TemplateRegistry` | `nome`, `tipo`, `descricao`, `conteudo` (despachos), `despacho_tipo` (despachos) |
| `Documento` | 14 | Tipo de documento (TCE, Relatório, etc.) | `nome`, `descricao` |
| `Pessoa` | 12 | Docente, coordenador, secretário | `nome`, `titulo`, `cargo` |
| `Papel` | 10 | Papel em um fluxo (Coordenador, Estagiário, etc.) | `nome`, `descricao` |
| `Norma` (seed) | 10 | Normas-chave manuais (Lei 11.788, etc.) | `codigo`, `tipo`, `nome` |
| `SigaAba` | 8 | Aba de consulta no SIGA | `nome`, `assunto`, `verificar` |
| `Fluxo` | 6 | Workflow nomeado (TCE, Aditivo, Rescisão, etc.) | `nome`, `descricao`, `prazo`, `regra_bloqueio` |
| `Sistema` | 6 | Sistema de TI (SEI, SIGA, OWA, Gmail, SOC) | `nome`, `url` |
| `Disciplina` | 2 | Disciplina curricular (OD501, ODDA5) | `codigo`, `nome`, `ch` |
| `Curso` | 1 | Curso de Design Gráfico | `nome`, `grau`, `vagas` |

### Tipos de Relação

| Relação | Descrição |
|---------|-----------|
| `SUBORDINADO_A` | Hierarquia organizacional (Orgao → Orgao) |
| `EMITIDA_POR` | Norma emitida por um conselho (Norma → Orgao) |
| `ALTERA` | Norma que modifica outra (Norma → Norma) |
| `REVOGA` | Norma que cancela outra (Norma → Norma) |
| `CONSOLIDADA_EM` | Link para a versão mais recente (Norma → Norma) |
| `REGULAMENTA` | Norma que regulamenta um tipo de processo (Norma → TipoProcesso) |
| `TRAMITA_VIA` | Processo que tramita por um sistema (TipoProcesso → Sistema) |
| `TEM_ETAPA` | Fluxo contém etapa ordenada (Fluxo → Etapa) |
| `EXECUTADA_POR` | Etapa executada por um papel (Etapa → Papel) |
| `USA_SISTEMA` | Etapa usa um sistema (Etapa → Sistema) |
| `USADO_EM` | Template usado em um fluxo (Template → Fluxo) |
| `PERTENCE_A` | Pessoa/SigaAba/Disciplina pertence a (→ Orgao/Sistema/Curso) |
| `EXERCE` | Pessoa exerce um papel (Pessoa → Papel) |
| `OPERA_SISTEMA` | Órgão opera um sistema (Orgao → Sistema) |
| `OFERECIDO_POR` | Curso oferecido por setor (Curso → Orgao) |

### Status de Vigência (Normas)

Cada `Norma` tem `status`:
- **`vigente`** — em vigor, nenhuma norma a revogou
- **`alterada`** — modificada por norma posterior (parcialmente em vigor)
- **`revogada`** — cancelada por norma posterior (fora de vigor)

Propriedades de rastreio:
- `alterada_por` — lista de códigos que alteram esta norma
- `revogada_por` — código da norma que a revogou
- `fonte_rag` — nome do arquivo PDF no RAG vetorial (para consultar texto completo)

## Fontes de Dados

### Seed (`seed.py`) — Conhecimento manual estruturado
- `ufpr_automation/workspace/SOUL.md` — Hierarquia, fluxos, templates, regras de estágio
- `ufpr_automation/ClaudeCowork/BaseDeConhecimento/SEI/manual.txt` — Manual do SEI (tipos de processo, frequências, ações)
- `ufpr_automation/ClaudeCowork/BaseDeConhecimento/SIGA/manual_siga.txt` — Manual do SIGA (URLs, abas, procedimentos)
- `ufpr_automation/ClaudeCowork/BaseDeConhecimento/FichaDoCurso.txt` — Dados do curso, docentes, contatos
- `ufpr_automation/ClaudeCowork/BaseDeConhecimento/estagios/` — Guias e templates de estágio

### Enrich (`enrich.py`) — Extração automática do RAG vetorial
- 1.473 resoluções extraídas de 1.577 PDFs (93% taxa de reconhecimento)
- 298 relações ALTERA e 151 REVOGA identificadas via regex em todos os chunks
- Distribuição: CEPE 582, COPLAD 457, COUN 424, CONCUR 10

## Como Usar

### Pré-requisitos
```bash
pip install -e ".[marco3]"  # instala neo4j>=5.20.0
```

Neo4j Desktop rodando em `bolt://localhost:7687`. Configurar no `.env`:
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=ufpr2026
```

### Comandos

```bash
# 1. Popular o grafo com conhecimento base (seed)
python -m ufpr_automation.graphrag.seed
python -m ufpr_automation.graphrag.seed --clear       # limpar e re-popular
python -m ufpr_automation.graphrag.seed --dry-run     # apenas testar conexão

# 2. Enriquecer com normas do RAG vetorial
python -m ufpr_automation.graphrag.enrich             # extrair + inserir tudo
python -m ufpr_automation.graphrag.enrich --dry-run   # apenas extrair, sem inserir
python -m ufpr_automation.graphrag.enrich --conselho cepe  # filtrar por conselho

# 3. O retriever é usado automaticamente pelo pipeline LangGraph
# (integrado em graph/nodes.py:rag_retrieve)
```

### Queries Cypher Úteis

```cypher
-- Hierarquia organizacional completa
MATCH (o:Orgao)-[r:SUBORDINADO_A]->(p:Orgao)
RETURN o, r, p

-- Cadeia de alterações de uma norma
MATCH path=(n:Norma)-[:ALTERA|CONSOLIDADA_EM*1..5]->(m:Norma)
WHERE n.nome CONTAINS 'estágio'
RETURN path

-- Normas revogadas e por quem
MATCH (nova:Norma)-[:REVOGA]->(velha:Norma)
RETURN nova.codigo, velha.codigo, velha.nome
ORDER BY velha.codigo

-- Status geral das normas
MATCH (n:Norma)
RETURN n.status, count(n) AS total
ORDER BY total DESC

-- Rastrear fonte no RAG vetorial
MATCH (n:Norma {status: 'alterada'})
RETURN n.codigo, n.alterada_por, n.fonte_rag
LIMIT 20

-- Fluxo completo de TCE com etapas, papéis e sistemas
MATCH (f:Fluxo {nome: 'TCE Não Obrigatório'})-[te:TEM_ETAPA]->(e:Etapa)
OPTIONAL MATCH (e)-[:EXECUTADA_POR]->(p:Papel)
OPTIONAL MATCH (e)-[:USA_SISTEMA]->(s:Sistema)
RETURN e.ordem, e.descricao, p.nome AS papel, s.nome AS sistema
ORDER BY e.ordem

-- Normas que regulamentam estágios
MATCH (n:Norma)-[:REGULAMENTA]->(tp:TipoProcesso)
WHERE tp.nome CONTAINS 'Estágio'
RETURN n.codigo, n.nome, tp.nome

-- Busca textual (full-text index)
CALL db.index.fulltext.queryNodes('node_search', 'estágio obrigatório')
YIELD node, score
RETURN labels(node)[0] AS tipo, node.nome, score
ORDER BY score DESC LIMIT 10
```

## Integração no Pipeline

O `GraphRetriever` é chamado automaticamente pelo nó `rag_retrieve` do LangGraph:

```
perceber → rag_retrieve → classificar → rotear → registrar_feedback → agir
               │
               ├── Vector RAG (LanceDB/RAPTOR) — busca semântica nos PDFs
               ├── GraphRAG (Neo4j) — fluxos, normas, templates, hierarquia
               └── Reflexion — erros passados como contexto negativo
```

O retriever combina 5 tipos de contexto:
1. **Workflow** — identifica o fluxo aplicável e lista todas as etapas
2. **Normas** — encontra legislação relevante via full-text search
3. **Templates** — sugere templates de email/despacho para o fluxo
4. **SIGA hints** — indica qual aba consultar para emails sobre alunos
5. **Contatos** — lista órgãos relevantes com email/telefone

O contexto é formatado e injetado no prompt do LLM junto com o contexto vetorial, permitindo classificações e respostas mais precisas e fundamentadas na legislação vigente.

## Estado Atual do Grafo (2026-04-08)

| Métrica | Valor |
|---------|-------|
| Total de nós | 1.757 |
| Total de relações | 2.296 |
| Normas (total) | ~1.600 |
| Normas vigentes | 1.281 |
| Normas alteradas | 174 |
| Normas revogadas | 148 |
| Relações ALTERA | 298 |
| Relações REVOGA | 151 |
| Links CONSOLIDADA_EM | 191 |
