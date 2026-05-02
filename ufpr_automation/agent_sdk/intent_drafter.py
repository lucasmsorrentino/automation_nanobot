"""Intent Drafter — auto-learns Tier 0 playbook intents from Tier 1 data.

Analyses ``procedures_data/procedures.jsonl`` and ``feedback_data/feedback.jsonl``
to identify clusters of emails that consistently fall through to Tier 1 (RAG + LLM).
For each qualifying cluster, it builds a prompt and invokes ``claude -p`` to generate
a candidate ``Intent`` YAML block, then appends it to ``workspace/PROCEDURES_CANDIDATES.md``.

Human reviews candidates and promotes them to ``PROCEDURES.md`` manually.

See ``SDD_CLAUDE_CODE_AUTOMATIONS.md §3`` for the full spec.

CLI::

    python -m ufpr_automation.agent_sdk.intent_drafter
    python -m ufpr_automation.agent_sdk.intent_drafter --last-days 14 --min-frequency 3
    python -m ufpr_automation.agent_sdk.intent_drafter --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ufpr_automation.config import settings
from ufpr_automation.procedures.playbook import Intent, parse_procedures_md

logger = logging.getLogger(__name__)

PROCEDURES_MD = settings.PACKAGE_ROOT / "workspace" / "PROCEDURES.md"
CANDIDATES_MD = settings.PACKAGE_ROOT / "workspace" / "PROCEDURES_CANDIDATES.md"
SOUL_MD = settings.PACKAGE_ROOT / "workspace" / "SOUL.md"
SEI_DOC_CATALOG = settings.PACKAGE_ROOT / "workspace" / "SEI_DOC_CATALOG.yaml"
BRIEFING_PATH = Path(__file__).parent / "skills" / "intent_drafter.md"


@dataclass
class EmailCluster:
    """A group of Tier 1 emails sharing a category and subject pattern."""

    categoria: str
    pattern: str  # Normalized common subject pattern
    sample_subjects: list[str] = field(default_factory=list)
    sample_senders: list[str] = field(default_factory=list)
    count: int = 0
    feedback_corrections: list[dict[str, Any]] = field(default_factory=list)


def _normalize_subject(subject: str) -> str:
    """Strip noise from email subject for clustering.

    Removes Fwd:/Re:/Enc: prefixes, numbers, dates, and normalises whitespace
    so that e.g. "Fwd: TCE João Silva 12345" and "Re: TCE Maria Santos 67890"
    both become "tce".
    """
    s = re.sub(r"^(Re|Fwd|Enc|FW|RES):\s*", "", subject, flags=re.IGNORECASE).strip()
    # Drop student names, GRRs, numbers, dates
    s = re.sub(r"GRR\d+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\d{2,}", "", s)
    s = re.sub(r"\b\d+\b", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip().lower()
    # Keep only first 3 significant words (the "topic")
    words = [w for w in s.split() if len(w) > 2]
    return " ".join(words[:3])


def cluster_tier1_emails(
    last_days: int = 14,
    min_frequency: int = 5,
    *,
    procedures_path: Path | None = None,
    feedback_path: Path | None = None,
) -> list[EmailCluster]:
    """Identify clusters of Tier 1 emails from procedure + feedback stores.

    Only includes procedure records whose ``outcome`` is NOT ``"tier0_hit"``
    (i.e. emails that went through RAG+LLM).

    Returns clusters sorted by frequency (descending).
    """
    from ufpr_automation.feedback.store import FeedbackStore
    from ufpr_automation.procedures.store import ProcedureStore

    store = ProcedureStore(path=procedures_path)
    records = store.list_recent(days=last_days)

    # Filter to Tier 1 only (not resolved by playbook)
    tier1 = [r for r in records if r.outcome and r.outcome != "tier0_hit"]

    # Group by (categoria, normalized_subject_pattern)
    groups: dict[tuple[str, str], list[Any]] = {}
    for rec in tier1:
        cat = rec.email_categoria or "Outros"
        pattern = _normalize_subject(rec.email_subject)
        if not pattern:
            pattern = cat.lower().replace(" / ", "_").replace(" ", "_")
        key = (cat, pattern)
        groups.setdefault(key, []).append(rec)

    # Load feedback corrections for enrichment
    fb_store = FeedbackStore(path=feedback_path)
    fb_records = fb_store.list_all()
    fb_by_hash: dict[str, list[dict[str, Any]]] = {}
    for fb in fb_records:
        fb_by_hash.setdefault(fb.email_hash, []).append(
            {
                "original_cat": fb.original.categoria,
                "corrected_cat": fb.corrected.categoria,
                "subject": fb.email_subject,
                "notes": fb.notes,
            }
        )

    clusters: list[EmailCluster] = []
    for (cat, pat), recs in groups.items():
        if len(recs) < min_frequency:
            continue
        subjects = list({r.email_subject for r in recs if r.email_subject})[:5]
        senders = list(
            {getattr(r, "email_sender", "") for r in recs if getattr(r, "email_sender", "")}
        )[:5]
        corrections: list[dict[str, Any]] = []
        for r in recs:
            if r.email_hash in fb_by_hash:
                corrections.extend(fb_by_hash[r.email_hash])
        clusters.append(
            EmailCluster(
                categoria=cat,
                pattern=pat,
                sample_subjects=subjects,
                sample_senders=senders,
                count=len(recs),
                feedback_corrections=corrections[:10],
            )
        )

    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters


def _existing_intent_names(path: Path | None = None) -> set[str]:
    """Load names of all existing intents to avoid duplication."""
    p = path or PROCEDURES_MD
    if not p.exists():
        return set()
    intents = parse_procedures_md(p)
    return {i.intent_name for i in intents}


def _candidate_hashes(path: Path | None = None) -> set[str]:
    """Extract content hashes from existing PROCEDURES_CANDIDATES.md headers."""
    p = path or CANDIDATES_MD
    if not p.exists():
        return set()
    text = p.read_text(encoding="utf-8")
    return set(re.findall(r"Hash:\s*([a-f0-9]+)", text))


def _content_hash(text: str) -> str:
    """Compute a short hash for idempotency."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def build_cluster_prompt(
    cluster: EmailCluster,
    existing_names: set[str],
    soul_excerpt: str,
) -> str:
    """Build the Claude prompt for generating an intent from a cluster."""
    samples = "\n".join(f"  - {s}" for s in cluster.sample_subjects) or "  (sem amostras)"
    senders = "\n".join(f"  - {s}" for s in cluster.sample_senders) or "  (desconhecidos)"

    corrections_text = ""
    if cluster.feedback_corrections:
        lines = []
        for c in cluster.feedback_corrections[:5]:
            lines.append(
                f"  - Subject: {c.get('subject', '?')} | "
                f"Original: {c.get('original_cat', '?')} → Corrigido: {c.get('corrected_cat', '?')}"
                + (f" | Nota: {c['notes']}" if c.get("notes") else "")
            )
        corrections_text = "\nCorreções humanas relevantes:\n" + "\n".join(lines)

    existing_list = ", ".join(sorted(existing_names)[:20]) or "(nenhum)"

    return f"""Você é um especialista em automação de emails da UFPR (Universidade Federal do Paraná).

Analise o seguinte cluster de emails que está caindo repetidamente no Tier 1 (RAG + LLM) em vez de ser resolvido pelo Tier 0 (playbook de intents). Seu trabalho é propor um bloco YAML de intent que, se adicionado ao playbook, resolveria esses emails instantaneamente sem precisar de RAG ou LLM.

## Cluster
- Categoria: {cluster.categoria}
- Padrão de assunto: "{cluster.pattern}"
- Frequência: {cluster.count} emails nos últimos dias
- Assuntos amostrais:
{samples}
- Remetentes amostrais:
{senders}
{corrections_text}

## Intents existentes (NÃO duplicar):
{existing_list}

## Regras SOUL.md relevantes (resumo):
{soul_excerpt[:2000]}

## Schema do Intent (YAML) — TODOS os campos:
```
intent_name: <snake_case único, ex: estagio_nao_obrig_prorrogacao>
keywords:
  - "keyword exata 1"
  - "keyword exata 2"
categoria: "{cluster.categoria}"
action: "Redigir Resposta"  # ou "Abrir Processo SEI", "Encaminhar"
required_fields:
  - nome_aluno  # campos que DEVEM estar no email
sources:
  - "SOUL.md §X"
  - "Resolução XX/YY-CEPE"
last_update: "{datetime.now(timezone.utc).strftime("%Y-%m-%d")}"
confidence: 0.85  # 0.5 se sem fonte confirmada
template: "Prezado(a) [NOME_ALUNO], ..."
sei_action: "none"  # ou "create_process" ou "append_to_existing"
sei_process_type: ""
required_attachments: []
blocking_checks: []
despacho_template: ""
```

## Instruções:
1. Proponha UM intent YAML completo que cubra este cluster
2. Se já existe um intent similar na lista acima, proponha EXPANSÃO (novos keywords) em vez de um novo intent — neste caso, escreva `# EXPANSÃO DE: <nome_existente>` antes do bloco
3. Keywords devem ser frases que aparecem literalmente nos subjects/bodies dos emails (NÃO genéricas)
4. Se não tem certeza das fontes normativas, use `confidence: 0.5` e `sources: ["pendente_revisao_humana"]`
5. O template deve usar placeholders [NOME_ALUNO], [GRR], [NUMERO_PROCESSO_SEI], etc.
6. NÃO invente leis ou resoluções — só cite o que está no trecho SOUL.md acima

Responda APENAS com o bloco YAML dentro de ``` markers, precedido de um comentário `# PROPOSTA:` ou `# EXPANSÃO DE:`.
Nenhum texto adicional fora do bloco."""


def _load_soul_excerpt() -> str:
    """Load SOUL.md summary relevant to intent generation."""
    if not SOUL_MD.exists():
        return "(SOUL.md não encontrado)"
    text = SOUL_MD.read_text(encoding="utf-8")
    # Extract key sections: categories, rules, procedures
    sections = []
    for section_name in ["Categorias", "Estágios", "Acadêmic", "Formativas", "Diplom"]:
        idx = text.find(f"## {section_name}")
        if idx == -1:
            idx = text.find(section_name)
        if idx >= 0:
            end = text.find("\n## ", idx + 1)
            if end == -1:
                end = idx + 2000
            sections.append(text[idx : min(end, idx + 1500)])
    return "\n---\n".join(sections) if sections else text[:3000]


def _process_cluster(
    cluster: EmailCluster,
    existing_names: set[str],
    soul: str,
    dry_run: bool,
    existing_hashes: set[str],
) -> tuple[str | None, str]:
    """Generate a candidate intent block for a single cluster.

    Returns ``(candidate_block, status)`` where ``status`` is one of:

    - ``"candidate"`` — new candidate produced (block is the comment +
      fenced YAML to append to ``CANDIDATES.md``).
    - ``"candidate_expansion"`` — same as above, but the LLM proposed an
      expansion of an existing intent (so callers bump the ``expansions``
      counter alongside ``candidates``).
    - ``"dry_run_marker"`` — dry-run only; block is a ``DRY_RUN: …``
      comment so the candidates file still records the analysis.
    - ``"skipped"`` — content hash already in ``existing_hashes``.
    - ``"failed"`` — claude failed, YAML missing, or YAML invalid; nothing
      to write.

    The outer ``run_intent_drafter`` is then a thin orchestrator that
    aggregates statuses into a stats dict.
    """
    from ufpr_automation.agent_sdk.runner import run_claude_oneshot

    prompt = build_cluster_prompt(cluster, existing_names, soul)
    content_hash = _content_hash(f"{cluster.categoria}|{cluster.pattern}|{cluster.count}")

    if content_hash in existing_hashes:
        logger.info(
            "Intent Drafter: cluster '%s/%s' já processado (hash %s), skip",
            cluster.categoria,
            cluster.pattern,
            content_hash,
        )
        return None, "skipped"

    if dry_run:
        logger.info(
            "Intent Drafter [DRY_RUN]: cluster '%s/%s' (%d emails) — prompt %d chars",
            cluster.categoria,
            cluster.pattern,
            cluster.count,
            len(prompt),
        )
        block = (
            f"<!-- DRY_RUN: cluster {cluster.categoria}/{cluster.pattern} "
            f"({cluster.count} emails)\n"
            f"     Hash: {content_hash} -->"
        )
        return block, "dry_run_marker"

    result = run_claude_oneshot(
        task="intent_drafter",
        prompt=prompt,
        output_format="text",
        timeout_s=120,
    )

    if not result.success:
        logger.warning(
            "Intent Drafter: claude falhou para cluster '%s/%s': %s",
            cluster.categoria,
            cluster.pattern,
            result.error or result.stderr,
        )
        return None, "failed"

    yaml_match = re.search(r"```(?:yaml|intent)?\s*\n(.*?)```", result.output_text, re.DOTALL)
    if not yaml_match:
        logger.warning(
            "Intent Drafter: nenhum bloco YAML na resposta para '%s/%s'",
            cluster.categoria,
            cluster.pattern,
        )
        return None, "failed"

    yaml_block = yaml_match.group(1).strip()

    try:
        import yaml as _yaml

        data = _yaml.safe_load(yaml_block)
        Intent.model_validate(data)
    except Exception as e:
        logger.warning(
            "Intent Drafter: YAML inválido para '%s/%s': %s",
            cluster.categoria,
            cluster.pattern,
            e,
        )
        return None, "failed"

    is_expansion = "EXPANSÃO DE:" in result.output_text.split("```")[0]

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    header = (
        f"<!-- Candidato gerado por agent_sdk/intent_drafter em {now_str}\n"
        f"     Baseado em {cluster.count} emails Tier 1"
        f" (categoria: {cluster.categoria})\n"
        f'     Cluster: "{cluster.pattern}"\n'
        f"     Samples: {cluster.sample_subjects[:3]}\n"
        f"     Hash: {content_hash}\n"
        f"     Para promover: revise abaixo e mova o bloco para PROCEDURES.md -->\n"
    )
    block = f"\n{header}\n```intent\n{yaml_block}\n```\n"
    return block, "candidate_expansion" if is_expansion else "candidate"


def run_intent_drafter(
    last_days: int = 14,
    min_frequency: int = 5,
    dry_run: bool = False,
    *,
    procedures_path: Path | None = None,
    feedback_path: Path | None = None,
    candidates_path: Path | None = None,
) -> dict[str, Any]:
    """Main entry point: cluster → prompt → claude → write candidates.

    Returns a summary dict with counts of clusters analysed, candidates
    generated, duplicates skipped, and expansions proposed.
    """
    from ufpr_automation.agent_sdk.runner import is_claude_available

    cand_path = candidates_path or CANDIDATES_MD

    clusters = cluster_tier1_emails(
        last_days=last_days,
        min_frequency=min_frequency,
        procedures_path=procedures_path,
        feedback_path=feedback_path,
    )

    if not clusters:
        logger.info(
            "Intent Drafter: nenhum cluster com >= %d emails nos últimos %d dias",
            min_frequency,
            last_days,
        )
        return {"clusters": 0, "candidates": 0, "skipped": 0, "expansions": 0}

    existing_names = _existing_intent_names(procedures_path)
    existing_hashes = _candidate_hashes(cand_path)
    soul_excerpt = _load_soul_excerpt()

    if not dry_run and not is_claude_available():
        logger.error("Intent Drafter: claude CLI não disponível — rode `claude /login` primeiro")
        return {
            "clusters": len(clusters),
            "candidates": 0,
            "skipped": 0,
            "expansions": 0,
            "error": "claude_unavailable",
        }

    stats: dict[str, int] = {
        "clusters": len(clusters),
        "candidates": 0,
        "skipped": 0,
        "expansions": 0,
    }
    candidate_blocks: list[str] = []

    for cluster in clusters:
        block, status = _process_cluster(
            cluster, existing_names, soul_excerpt, dry_run, existing_hashes
        )
        if status == "skipped":
            stats["skipped"] += 1
        elif status == "dry_run_marker":
            stats["candidates"] += 1
            if block is not None:
                candidate_blocks.append(block)
        elif status in ("candidate", "candidate_expansion"):
            stats["candidates"] += 1
            if status == "candidate_expansion":
                stats["expansions"] += 1
            if block is not None:
                candidate_blocks.append(block)
        # status == "failed" → no stats bump, no block

    if candidate_blocks:
        _append_candidates(cand_path, candidate_blocks)
        logger.info(
            "Intent Drafter: %d candidato(s) escritos em %s",
            len(candidate_blocks),
            cand_path,
        )

    logger.info(
        "Intent Drafter concluído: %d clusters, %d candidatos, %d skips, %d expansões",
        stats["clusters"],
        stats["candidates"],
        stats["skipped"],
        stats["expansions"],
    )
    return stats


def _append_candidates(path: Path, blocks: list[str]) -> None:
    """Append candidate intent blocks to PROCEDURES_CANDIDATES.md."""
    if not path.exists():
        header = (
            "# PROCEDURES_CANDIDATES.md\n\n"
            "> Candidatos gerados automaticamente pelo Intent Drafter.\n"
            "> Revise cada bloco e, se aprovado, mova para `workspace/PROCEDURES.md`.\n"
            "> NÃO edite este arquivo diretamente — ele é append-only.\n\n"
        )
        path.write_text(header, encoding="utf-8")

    with open(path, "a", encoding="utf-8") as f:
        for block in blocks:
            f.write(block)
            f.write("\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="intent_drafter",
        description="Analyse Tier 1 email clusters and propose Tier 0 playbook intents",
    )
    parser.add_argument(
        "--last-days",
        type=int,
        default=14,
        help="Look back window in days (default: 14)",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=5,
        help="Minimum cluster size to generate a candidate (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyse clusters but do not invoke Claude or write candidates",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
    )

    stats = run_intent_drafter(
        last_days=args.last_days,
        min_frequency=args.min_frequency,
        dry_run=args.dry_run,
    )

    print(f"\nResultado: {stats}")
    sys.exit(0 if stats.get("error") is None else 1)


if __name__ == "__main__":
    main()
