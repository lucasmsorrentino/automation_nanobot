"""Graph data model — node labels, relationship types, and constraints.

This schema models the institutional knowledge of UFPR's bureaucratic structure:

Nodes:
    Orgao           — Organizational unit (Reitoria, PROGRAD, COAFE, UE, SACOD, CCDG…)
    Norma           — Legal/regulatory document (Lei 11.788, Res 46/10-CEPE…)
    TipoProcesso    — SEI process type with frequency data
    Documento       — Document type used in workflows (TCE, Plano de Atividades…)
    Papel           — Role in a workflow (Coordenador, Secretário, Orientador…)
    Sistema         — IT system (SEI, SIGA, OWA, Gmail)
    Template        — Email or despacho template
    Fluxo           — Named workflow (TCE Inicial, Termo Aditivo, Rescisão…)
    Etapa           — Single step within a workflow
    Pessoa          — Named individual (docentes, coordenadores)
    Curso           — Academic course
    Disciplina      — Course subject (for internship validation)

Relationships:
    (:Orgao)-[:SUBORDINADO_A]->(:Orgao)
    (:Orgao)-[:OPERA_SISTEMA]->(:Sistema)
    (:Pessoa)-[:PERTENCE_A]->(:Orgao)
    (:Pessoa)-[:EXERCE]->(:Papel)
    (:Norma)-[:REGULAMENTA]->(:TipoProcesso)
    (:Norma)-[:ALTERA]->(:Norma)
    (:TipoProcesso)-[:TRAMITA_VIA]->(:Sistema)
    (:TipoProcesso)-[:REQUER]->(:Documento)
    (:Fluxo)-[:TEM_ETAPA {ordem: int}]->(:Etapa)
    (:Etapa)-[:EXECUTADA_POR]->(:Papel)
    (:Etapa)-[:USA_SISTEMA]->(:Sistema)
    (:Etapa)-[:GERA]->(:Documento)
    (:Template)-[:USADO_EM]->(:Fluxo)
    (:Template)-[:GERA]->(:Documento)
    (:Curso)-[:OFERECIDO_POR]->(:Orgao)
    (:Disciplina)-[:PERTENCE_A]->(:Curso)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Constraints and indexes (run once on empty database)
# ---------------------------------------------------------------------------

CONSTRAINTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Orgao) REQUIRE o.sigla IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Norma) REQUIRE n.codigo IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (tp:TipoProcesso) REQUIRE tp.nome IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Documento) REQUIRE d.nome IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Papel) REQUIRE p.nome IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Sistema) REQUIRE s.nome IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Template) REQUIRE t.nome IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (f:Fluxo) REQUIRE f.nome IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Curso) REQUIRE c.nome IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (pe:Pessoa) REQUIRE pe.nome IS UNIQUE",
]

# Full-text index for natural-language search over node names/descriptions
FULLTEXT_INDEXES = [
    (
        "CREATE FULLTEXT INDEX node_search IF NOT EXISTS "
        "FOR (n:Orgao|Norma|TipoProcesso|Documento|Papel|Template|Fluxo|Curso|Pessoa) "
        "ON EACH [n.nome, n.sigla, n.codigo, n.descricao]"
    ),
]


def apply_constraints(client) -> None:
    """Create all uniqueness constraints and indexes on the Neo4j database."""
    for cypher in CONSTRAINTS + FULLTEXT_INDEXES:
        client.run_write(cypher)
