"""Enrich Neo4j graph from RAG vector store — extract norms and their lineage.

Strategy:
    1. First chunk of each resolution → extract code + ementa (identity)
    2. ALL chunks of each resolution → extract ALTERA/REVOGA references (lineage)
    3. Build lineage chains and mark each norm's status:
       - vigente: not revoked by any other norm
       - alterada: modified by a later norm (but still partially in effect)
       - revogada: fully replaced/cancelled by a later norm
    4. Add fonte_rag (arquivo) for traceability back to the vector store

The graph reflects the CURRENT state of legislation.
Historical text can be retrieved from the RAG vector store via the fonte_rag link.

Usage:
    python -m ufpr_automation.graphrag.enrich                    # extract + insert all
    python -m ufpr_automation.graphrag.enrich --dry-run           # extract only, print stats
    python -m ufpr_automation.graphrag.enrich --conselho cepe     # only CEPE resolutions
    python -m ufpr_automation.graphrag.enrich --limit 50          # first 50 resolutions
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field

from ufpr_automation.graphrag.client import Neo4jClient
from ufpr_automation.utils.logging import logger


@dataclass
class ExtractedNorm:
    """A norm extracted from a RAG chunk."""

    codigo: str
    tipo: str
    conselho: str
    ementa: str = ""
    arquivo: str = ""
    altera: list[str] = field(default_factory=list)
    revoga: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_RESOLUCAO = re.compile(
    r"RESOLU[ÇC][ÃA]O\s+N[°ºo.]\s*(\d+[A-Za-z]?[/-]?\d*[/-]?\d*)\s*[-–—]\s*"
    r"(CEPE|COPLAD|COUN|CONCUR)",
    re.IGNORECASE,
)

_RE_AD_REFERENDUM = re.compile(
    r"Ad[\s-]Referendum\s+(?:n[°ºo.]\s*)?(\d+[/-]?\d*[/-]?\d*)",
    re.IGNORECASE,
)

_RE_EMENTA = re.compile(
    r"(?:Estabelece|Aprova|Homologa|Altera|Dispõe|Regulamenta|Cria|Define|Fixa|"
    r"Autoriza|Institui|Revoga|Prorroga|Nomeia|Designa|Credencia|Reconhece|"
    r"Publica|Normatiza|Determina|Sobrestamento|Adesão|Prorrogação)"
    r"[^.]{10,300}\.",
    re.IGNORECASE,
)

# Broad patterns for capturing references in ALL chunks
_RE_REF_ALTERA = re.compile(
    r"(?:altera|alteração|alterada|alterando|modifica|modificada)"
    r"[^.]{0,120}"
    r"(?:Resolu[çc][ãa]o|Res\.?)\s*(?:n[°ºo.]\s*)?(\d+[A-Za-z]?[/-]?\d*[/-]?\d*)\s*[-–—]\s*"
    r"(CEPE|COPLAD|COUN|CONCUR)",
    re.IGNORECASE,
)

_RE_REF_REVOGA = re.compile(
    r"(?:revoga|revogação|revogada|revogando|fica\s+revogada|ficam\s+revogad)"
    r"[^.]{0,120}"
    r"(?:Resolu[çc][ãa]o|Res\.?)\s*(?:n[°ºo.]\s*)?(\d+[A-Za-z]?[/-]?\d*[/-]?\d*)\s*[-–—]\s*"
    r"(CEPE|COPLAD|COUN|CONCUR)",
    re.IGNORECASE,
)


def _normalize_code(num: str, conselho: str) -> str:
    """Normalize resolution code to canonical form."""
    num = num.strip().replace("–", "-").replace("—", "-")
    conselho = conselho.upper()
    return f"Resolução {num}-{conselho}"


def extract_identity(text: str, arquivo: str, conselho_meta: str) -> ExtractedNorm | None:
    """Extract norm identity (code + ementa) from a first chunk."""
    m = _RE_RESOLUCAO.search(text)
    if m:
        codigo = _normalize_code(m.group(1), m.group(2))
        tipo = "Resolução"
        conselho = m.group(2).upper()
    else:
        m_ad = _RE_AD_REFERENDUM.search(text)
        if m_ad:
            num = m_ad.group(1)
            conselho = conselho_meta.upper()
            codigo = f"Ad Referendum {num}-{conselho}"
            tipo = "Ad Referendum"
        else:
            return None

    ementa = ""
    m_em = _RE_EMENTA.search(text)
    if m_em:
        ementa = re.sub(r"\s+", " ", m_em.group(0).strip())

    return ExtractedNorm(
        codigo=codigo,
        tipo=tipo,
        conselho=conselho,
        ementa=ementa[:500],
        arquivo=arquivo,
    )


def extract_references(text: str, source_code: str) -> tuple[list[str], list[str]]:
    """Extract ALTERA and REVOGA references from any chunk text."""
    altera = []
    for m in _RE_REF_ALTERA.finditer(text):
        ref = _normalize_code(m.group(1), m.group(2))
        if ref != source_code and ref not in altera:
            altera.append(ref)

    revoga = []
    for m in _RE_REF_REVOGA.finditer(text):
        ref = _normalize_code(m.group(1), m.group(2))
        if ref != source_code and ref not in revoga:
            revoga.append(ref)

    return altera, revoga


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_all_chunks(conselho_filter: str | None = None):
    """Load all resolution chunks from LanceDB, grouped by file."""
    import lancedb

    from ufpr_automation.config.settings import RAG_STORE_DIR

    db_path = RAG_STORE_DIR / "ufpr.lance"
    if not db_path.exists():
        logger.error("RAG store não encontrado: %s", db_path)
        return {}

    db = lancedb.connect(str(db_path))
    table = db.open_table("ufpr_docs")
    df = table.to_pandas()

    mask = df["tipo"].isin(["resolucoes", "instrucoes-normativas"])
    if conselho_filter:
        mask &= df["conselho"] == conselho_filter.lower()
    subset = df[mask]

    # Group all chunks by arquivo
    grouped: dict[str, dict] = {}
    for _, row in subset.iterrows():
        arquivo = row["arquivo"]
        if arquivo not in grouped:
            grouped[arquivo] = {
                "conselho": row.get("conselho", ""),
                "chunks": [],
            }
        grouped[arquivo]["chunks"].append(row["text"])

    return grouped


def extract_all(
    conselho_filter: str | None = None,
    limit: int | None = None,
) -> list[ExtractedNorm]:
    """Extract norms from all resolution files, scanning ALL chunks for references."""
    grouped = load_all_chunks(conselho_filter)
    files = list(grouped.items())
    if limit:
        files = files[:limit]

    logger.info("Extraindo normas de %d arquivos de resolução...", len(files))

    norms: list[ExtractedNorm] = []
    failed = 0

    for arquivo, data in files:
        chunks = data["chunks"]
        conselho_meta = data["conselho"]

        # Step 1: Extract identity from first chunk
        norm = extract_identity(chunks[0], arquivo, conselho_meta)
        if not norm:
            failed += 1
            continue

        # Step 2: Scan ALL chunks for ALTERA/REVOGA references
        all_altera: list[str] = []
        all_revoga: list[str] = []
        for chunk_text in chunks:
            altera, revoga = extract_references(chunk_text, norm.codigo)
            for ref in altera:
                if ref not in all_altera:
                    all_altera.append(ref)
            for ref in revoga:
                if ref not in all_revoga:
                    all_revoga.append(ref)

        norm.altera = all_altera
        norm.revoga = all_revoga
        norms.append(norm)

    logger.info(
        "Extração: %d normas, %d não reconhecidas (%d total)",
        len(norms),
        failed,
        len(files),
    )
    return norms


# ---------------------------------------------------------------------------
# Neo4j insertion with lineage
# ---------------------------------------------------------------------------


def insert_norms(client: Neo4jClient, norms: list[ExtractedNorm]) -> dict[str, int]:
    """Insert norms into Neo4j with lineage relationships and status."""
    inserted = 0
    rel_altera = 0
    rel_revoga = 0
    rel_emitida = 0

    # Step 1: Insert all norms with fonte_rag
    for norm in norms:
        client.run_write(
            """
            MERGE (n:Norma {codigo: $codigo})
            SET n.tipo = $tipo,
                n.conselho = $conselho,
                n.nome = CASE WHEN $ementa <> '' THEN $ementa ELSE n.nome END,
                n.descricao = CASE WHEN $ementa <> '' THEN $ementa ELSE n.descricao END,
                n.fonte_rag = $arquivo
            """,
            {
                "codigo": norm.codigo,
                "tipo": norm.tipo,
                "conselho": norm.conselho,
                "ementa": norm.ementa,
                "arquivo": norm.arquivo,
            },
        )
        inserted += 1

        # Link to conselho
        client.run_write(
            """
            MATCH (n:Norma {codigo: $codigo}), (o:Orgao {sigla: $conselho})
            MERGE (n)-[:EMITIDA_POR]->(o)
            """,
            {"codigo": norm.codigo, "conselho": norm.conselho},
        )
        rel_emitida += 1

    # Step 2: Create ALTERA and REVOGA relationships
    for norm in norms:
        for ref in norm.altera:
            client.run_write(
                """
                MERGE (ref:Norma {codigo: $ref})
                WITH ref
                MATCH (n:Norma {codigo: $codigo})
                MERGE (n)-[:ALTERA]->(ref)
                """,
                {"codigo": norm.codigo, "ref": ref},
            )
            rel_altera += 1

        for ref in norm.revoga:
            client.run_write(
                """
                MERGE (ref:Norma {codigo: $ref})
                WITH ref
                MATCH (n:Norma {codigo: $codigo})
                MERGE (n)-[:REVOGA]->(ref)
                """,
                {"codigo": norm.codigo, "ref": ref},
            )
            rel_revoga += 1

    logger.info(
        "Neo4j norms: %d inseridas, %d ALTERA, %d REVOGA, %d EMITIDA_POR",
        inserted,
        rel_altera,
        rel_revoga,
        rel_emitida,
    )
    return {
        "inserted": inserted,
        "rel_altera": rel_altera,
        "rel_revoga": rel_revoga,
        "rel_emitida": rel_emitida,
    }


def compute_status(client: Neo4jClient) -> dict[str, int]:
    """Compute vigência status for all norms based on lineage.

    Rules:
        - revogada: another norm REVOGA this one
        - alterada: another norm ALTERA this one (but not revogada)
        - vigente: no one ALTERA or REVOGA this one

    Also sets:
        - alterada_por: list of codes that alter this norm
        - revogada_por: code of the norm that revokes this
        - fonte_rag: arquivo for RAG traceability
    """
    # Mark all as vigente first
    client.run_write("MATCH (n:Norma) SET n.status = 'vigente'")

    # Mark revogadas
    rows = client.run_query("""
        MATCH (newer:Norma)-[:REVOGA]->(old:Norma)
        SET old.status = 'revogada', old.revogada_por = newer.codigo
        RETURN count(old) AS cnt
    """)
    revogadas = rows[0]["cnt"] if rows else 0

    # Mark alteradas (only if not already revogada)
    rows = client.run_query("""
        MATCH (newer:Norma)-[:ALTERA]->(old:Norma)
        WHERE old.status <> 'revogada'
        SET old.status = 'alterada'
        RETURN count(DISTINCT old) AS cnt
    """)
    alteradas = rows[0]["cnt"] if rows else 0

    # Collect alterada_por list for each altered norm
    client.run_write("""
        MATCH (newer:Norma)-[:ALTERA]->(old:Norma)
        WITH old, collect(newer.codigo) AS modificadores
        SET old.alterada_por = modificadores
    """)

    # Count vigentes
    rows = client.run_query("""
        MATCH (n:Norma) WHERE n.status = 'vigente' RETURN count(n) AS cnt
    """)
    vigentes = rows[0]["cnt"] if rows else 0

    logger.info(
        "Status: %d vigentes, %d alteradas, %d revogadas",
        vigentes,
        alteradas,
        revogadas,
    )
    return {"vigentes": vigentes, "alteradas": alteradas, "revogadas": revogadas}


def build_consolidation_links(client: Neo4jClient) -> int:
    """Create CONSOLIDADA_EM links for chains of amendments.

    If A alters B, and C alters B, then B → CONSOLIDADA_EM → [A, C] (latest by code).
    This helps the retriever find the "current effective version" of a norm.
    """
    # For each altered norm, find the latest modifier and create a link
    rows = client.run_query("""
        MATCH (newer:Norma)-[:ALTERA]->(old:Norma)
        WITH old, newer ORDER BY newer.codigo DESC
        WITH old, collect(newer)[0] AS latest
        RETURN old.codigo AS base, latest.codigo AS latest
    """)

    count = 0
    for row in rows:
        client.run_write(
            """
            MATCH (old:Norma {codigo: $base}), (latest:Norma {codigo: $latest})
            MERGE (old)-[:CONSOLIDADA_EM]->(latest)
            """,
            {"base": row["base"], "latest": row["latest"]},
        )
        count += 1

    logger.info("Consolidação: %d links CONSOLIDADA_EM criados", count)
    return count


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def enrich(
    client: Neo4jClient | None = None,
    conselho: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Full enrichment pipeline: RAG → extract → Neo4j → lineage → status."""
    norms = extract_all(conselho_filter=conselho, limit=limit)

    if not norms:
        logger.warning("Nenhuma norma extraída.")
        return {"extracted": 0}

    # Compute extraction stats
    by_conselho: dict[str, int] = {}
    by_tipo: dict[str, int] = {}
    with_ementa = 0
    total_altera = sum(len(n.altera) for n in norms)
    total_revoga = sum(len(n.revoga) for n in norms)

    for n in norms:
        by_conselho[n.conselho] = by_conselho.get(n.conselho, 0) + 1
        by_tipo[n.tipo] = by_tipo.get(n.tipo, 0) + 1
        if n.ementa:
            with_ementa += 1

    stats: dict = {
        "extracted": len(norms),
        "with_ementa": with_ementa,
        "altera_refs": total_altera,
        "revoga_refs": total_revoga,
        "by_conselho": by_conselho,
        "by_tipo": by_tipo,
    }

    if dry_run:
        return stats

    own_client = client is None
    if own_client:
        client = Neo4jClient()

    # Phase 1: Insert norms + relationships
    insert_stats = insert_norms(client, norms)
    stats.update(insert_stats)

    # Phase 2: Compute vigência status
    status_stats = compute_status(client)
    stats.update(status_stats)

    # Phase 3: Build consolidation links
    consol = build_consolidation_links(client)
    stats["consolidation_links"] = consol

    if own_client:
        stats["total_nodes"] = client.node_count()
        stats["total_relationships"] = client.relationship_count()
        client.close()

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich Neo4j graph from RAG resolutions")
    parser.add_argument("--dry-run", action="store_true", help="Extract only, don't insert")
    parser.add_argument(
        "--conselho", choices=["cepe", "coplad", "coun", "concur"], help="Filter by conselho"
    )
    parser.add_argument("--limit", type=int, help="Limit number of resolutions to process")
    args = parser.parse_args()

    stats = enrich(conselho=args.conselho, limit=args.limit, dry_run=args.dry_run)

    print("\n=== Enrichment Results ===")
    print(f"  Normas extraídas:      {stats['extracted']}")
    print(f"  Com ementa:            {stats.get('with_ementa', '?')}")
    print(f"  Referências ALTERA:    {stats.get('altera_refs', '?')}")
    print(f"  Referências REVOGA:    {stats.get('revoga_refs', '?')}")
    print(f"\n  Por conselho: {stats.get('by_conselho', {})}")
    print(f"  Por tipo:     {stats.get('by_tipo', {})}")

    if not args.dry_run:
        print("\n  --- Vigência ---")
        print(f"  Vigentes:              {stats.get('vigentes', '?')}")
        print(f"  Alteradas:             {stats.get('alteradas', '?')}")
        print(f"  Revogadas:             {stats.get('revogadas', '?')}")
        print(f"  Links consolidação:    {stats.get('consolidation_links', '?')}")

        if "total_nodes" in stats:
            print(f"\n  Neo4j: {stats['total_nodes']} nós, {stats['total_relationships']} relações")


if __name__ == "__main__":
    main()
