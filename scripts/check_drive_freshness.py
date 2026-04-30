"""Verifica se o RAG store local esta sincronizado com o do G:.

Le ``G:/Meu Drive/ufpr_rag/store/MANIFEST.json`` e
``<RAG_STORE_DIR>/MANIFEST.json`` (gerados por ``generate_manifest.py``)
e compara timestamps + counts.

Exit codes:
  0 = SYNCED       manifests batem em counts e timestamps
  1 = STALE        G: tem versao mais recente -- rodar sync_from_drive.ps1
  2 = AHEAD        local tem versao mais recente -- rodar sync_to_drive.ps1
  3 = NO_REMOTE    G:/MANIFEST.json nao existe (primeira vez no projeto)
  4 = NO_LOCAL     manifest local nao existe (primeira vez neste PC)
  5 = CONFLICT     timestamps divergem em direcoes ambiguas (raro)
  6 = ERROR        qualquer erro de leitura/parsing

Saida humano-legivel em stdout (default) ou JSON com ``--json``.

Pareado com generate_manifest.py / sync_to_drive.ps1 / sync_from_drive.ps1.
Usado em 3 lugares:
  1. SessionStart hook do Claude Code (.claude/settings.json)
  2. Pre-flight do pipeline (scheduler.py:run_scheduled_pipeline)
  3. Manual via scripts/check_drive_status.ps1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ufpr_automation.config import settings  # noqa: E402

REMOTE_MANIFEST = Path("G:/Meu Drive/ufpr_rag/store/MANIFEST.json")


def _local_manifest_path() -> Path:
    return Path(settings.RAG_STORE_DIR) / "MANIFEST.json"


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ts(m: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(m["timestamp"])
    except (KeyError, ValueError, TypeError):
        return None


def _counts(m: dict) -> tuple[int, int, int]:
    """Retorna (chunks, nodes, rels) — 0 se faltar campo."""
    lance = m.get("lancedb") or {}
    neo4j = m.get("neo4j") or {}
    return (
        int(lance.get("total_chunks") or 0),
        int(neo4j.get("total_nodes") or 0),
        int(neo4j.get("total_relationships") or 0),
    )


def evaluate() -> dict:
    """Compara manifests local e remoto. Retorna dict com status detalhado."""
    local_path = _local_manifest_path()
    remote = _read(REMOTE_MANIFEST)
    local = _read(local_path)

    result = {
        "remote_path": str(REMOTE_MANIFEST),
        "local_path": str(local_path),
        "remote_exists": remote is not None,
        "local_exists": local is not None,
        "remote": remote,
        "local": local,
    }

    if remote is None and local is None:
        result.update(status="NO_REMOTE", code=3,
                      message="Nem o G: nem o local tem MANIFEST.json. "
                              "Provavelmente este eh o primeiro setup. "
                              "Rode scripts/sync_to_drive.ps1 apos o ingest "
                              "inicial para popular o G:.")
        return result

    if remote is None:
        result.update(status="NO_REMOTE", code=3,
                      message="G:/MANIFEST.json nao existe. "
                              "Rode scripts/sync_to_drive.ps1 daqui para "
                              "publicar o estado deste PC para o outro.")
        return result

    if local is None:
        result.update(status="NO_LOCAL", code=4,
                      message="Manifest local nao existe mas o G: tem um. "
                              "Rode scripts/sync_from_drive.ps1 para "
                              "puxar o RAG/Neo4j do G:.")
        return result

    rt = _ts(remote)
    lt = _ts(local)
    rc, rn, rr = _counts(remote)
    lc, ln, lr = _counts(local)

    counts_match = (rc, rn, rr) == (lc, ln, lr)
    git_sha_match = remote.get("git_sha") == local.get("git_sha")

    diff_chunks = lc - rc
    diff_nodes = ln - rn
    diff_rels = lr - rr
    result["delta"] = {
        "chunks": diff_chunks, "nodes": diff_nodes, "rels": diff_rels,
        "counts_match": counts_match, "git_sha_match": git_sha_match,
    }

    if counts_match and rt and lt and rt == lt:
        result.update(status="SYNCED", code=0,
                      message=f"OK - este PC esta alinhado com o G: "
                              f"({rc} chunks, {rn} nos, {rr} rels).")
        return result

    if rt and lt:
        if rt > lt:
            result.update(status="STALE", code=1,
                          message=f"G: eh mais recente que o local "
                                  f"(remoto={rt.isoformat()}, "
                                  f"local={lt.isoformat()}). "
                                  f"Rode scripts/sync_from_drive.ps1 antes "
                                  f"de tocar RAG/Neo4j.")
            return result
        if lt > rt:
            result.update(status="AHEAD", code=2,
                          message=f"Local eh mais recente que o G: "
                                  f"(local={lt.isoformat()}, "
                                  f"remoto={rt.isoformat()}). "
                                  f"Rode scripts/sync_to_drive.ps1 para "
                                  f"publicar para o outro PC.")
            return result

    # Mesmo timestamp mas counts divergem — anomalia
    result.update(status="CONFLICT", code=5,
                  message=f"Timestamps iguais mas counts divergem "
                          f"(delta chunks={diff_chunks}, nodes={diff_nodes}, "
                          f"rels={diff_rels}). Investigar antes de "
                          f"sobrescrever qualquer lado.")
    return result


def _format_human(result: dict) -> str:
    lines = [f"[{result['status']}] {result['message']}"]
    if result.get("remote") and result.get("local"):
        r = result["remote"]
        l = result["local"]
        lines.append("")
        lines.append(f"  Remoto (G:):    machine={r.get('machine')}  "
                     f"timestamp={r.get('timestamp')}  git_sha={r.get('git_sha')}")
        lines.append(f"  Local:          machine={l.get('machine')}  "
                     f"timestamp={l.get('timestamp')}  git_sha={l.get('git_sha')}")
        rc, rn, rr = _counts(r)
        lc, ln, lrr = _counts(l)
        lines.append(f"  Counts remoto:  {rc} chunks / {rn} nos / {rr} rels")
        lines.append(f"  Counts local:   {lc} chunks / {ln} nos / {lrr} rels")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true", help="Saida em JSON em vez de texto.")
    p.add_argument("--quiet", action="store_true",
                   help="Suprime saida quando status=SYNCED (so imprime se houver problema).")
    args = p.parse_args()

    try:
        result = evaluate()
    except Exception as e:
        out = {"status": "ERROR", "code": 6, "message": str(e)}
        if args.json:
            print(json.dumps(out, ensure_ascii=False))
        else:
            print(f"[ERROR] {e}")
        return 6

    if args.quiet and result["code"] == 0:
        return 0

    if args.json:
        # Remove dicts grandes para nao explodir o output
        compact = {k: v for k, v in result.items() if k not in ("remote", "local")}
        print(json.dumps(compact, ensure_ascii=False, indent=2))
    else:
        print(_format_human(result))

    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
