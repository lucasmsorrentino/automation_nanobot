"""Gera MANIFEST.json com contadores do LanceDB local + Neo4j local.

Uso:
    python scripts/generate_manifest.py --output PATH

Saida JSON com schema_version, timestamp, machine, git_sha, lancedb (total
de chunks por tabela + tamanho do diretorio) e neo4j (total de nos e
relacoes + breakdown por label).

Pareado com sync_to_drive.ps1 / sync_from_drive.ps1: ambos os PCs geram
manifests apos sync e comparam contadores para detectar drift entre
casa <-> trabalho. Consistencia do RAG e Neo4j entre os 2 PCs depende
de re-seed apos cada robocopy do G: -- esse manifest e o sinal.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Garante que o pacote ufpr_automation esta no path quando rodado direto
# do diretorio scripts/.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ufpr_automation.config import settings  # noqa: E402


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return "unknown"


def _dir_size_mb(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return round(total / (1024 * 1024))


def _lancedb_stats() -> dict:
    import lancedb

    store_dir = Path(settings.RAG_STORE_DIR) / "ufpr.lance"
    if not store_dir.exists():
        return {"available": False, "store_path": str(store_dir)}

    db = lancedb.connect(str(store_dir))
    # NOTE: list_tables() retorna pyarrow.Table com colunas (.tables = [...]).
    # table_names() retorna list[str]; deprecated mas funcional. Usar a forma
    # que o codigo do projeto ja usa em ingest.py:266.
    raw = db.list_tables() if hasattr(db, "list_tables") else None
    if raw is not None and hasattr(raw, "tables"):
        table_names = list(raw.tables)
    elif raw is not None:
        # API mais nova devolve list[str] direto
        table_names = list(raw)
    else:
        table_names = list(db.table_names())
    tables = {}
    total = 0
    for name in table_names:
        try:
            tbl = db.open_table(name)
            count = tbl.count_rows()
            tables[name] = count
            total += count
        except Exception as e:
            tables[name] = f"error: {e}"

    return {
        "available": True,
        "store_path": str(store_dir),
        "total_chunks": total,
        "tables": tables,
        "store_size_mb": _dir_size_mb(store_dir),
    }


def _neo4j_stats() -> dict:
    try:
        from ufpr_automation.graphrag.client import Neo4jClient
    except Exception as e:
        return {"available": False, "error": f"import: {e}"}

    try:
        c = Neo4jClient()
    except Exception as e:
        return {"available": False, "error": f"connect: {e}"}

    try:
        rows = c.run_query("MATCH (n) RETURN count(n) AS cnt")
        total_nodes = rows[0]["cnt"] if rows else 0
        rows = c.run_query("MATCH ()-[r]->() RETURN count(r) AS cnt")
        total_rels = rows[0]["cnt"] if rows else 0

        rows = c.run_query("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY label")
        nodes_by_label = {r["label"]: r["cnt"] for r in rows if r["label"]}

        rows = c.run_query(
            "MATCH ()-[r]->() RETURN type(r) AS rtype, count(r) AS cnt ORDER BY rtype"
        )
        rels_by_type = {r["rtype"]: r["cnt"] for r in rows}

        rows = c.run_query("MATCH (n:Norma)-[:EMITIDO_POR]->() RETURN count(n) AS cnt")
        normas_with_emissor = rows[0]["cnt"] if rows else 0

        return {
            "available": True,
            "uri": settings.NEO4J_URI,
            "total_nodes": total_nodes,
            "total_relationships": total_rels,
            "nodes_by_label": nodes_by_label,
            "rels_by_type": rels_by_type,
            "normas_with_emissor": normas_with_emissor,
        }
    finally:
        try:
            c.close()
        except Exception:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, help="Caminho de saida do MANIFEST.json")
    p.add_argument(
        "--machine",
        default=os.environ.get("COMPUTERNAME") or socket.gethostname() or "unknown",
        help="Nome da maquina (default: COMPUTERNAME ou socket.gethostname())",
    )
    args = p.parse_args()

    manifest = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "machine": args.machine,
        "git_sha": _git_sha(),
        "lancedb": _lancedb_stats(),
        "neo4j": _neo4j_stats(),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Manifest gravado em: {out}")
    lancedb = manifest["lancedb"]
    neo4j = manifest["neo4j"]
    print(f"  LanceDB: {lancedb.get('total_chunks', 'N/A')} chunks ({lancedb.get('store_size_mb', '?')} MB)")
    if neo4j.get("available"):
        print(f"  Neo4j:   {neo4j['total_nodes']} nos / {neo4j['total_relationships']} relacoes")
    else:
        print(f"  Neo4j:   indisponivel ({neo4j.get('error', '')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
