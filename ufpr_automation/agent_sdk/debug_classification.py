"""Classification Debugger — diagnoses misclassified emails.

Replays the Tier 0 playbook for a given ``stable_id``, loads procedure
logs, and produces a diagnostic Markdown report showing exactly why the
email was classified the way it was — and what could be done to fix it.

See ``SDD_CLAUDE_CODE_AUTOMATIONS.md §5`` for the full spec.

CLI::

    python -m ufpr_automation.agent_sdk.debug_classification --stable-id b02f093d
    python -m ufpr_automation.agent_sdk.debug_classification --last 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ufpr_automation.config import settings

logger = logging.getLogger(__name__)

FEEDBACK_DIR = settings.FEEDBACK_DATA_DIR
LAST_RUN_FILE = FEEDBACK_DIR / "last_run.jsonl"
REPORT_BASE = settings.PACKAGE_ROOT / "procedures_data" / "agent_sdk" / "debug_classification"


@dataclass
class DebugTrace:
    """Full diagnostic trace for one email."""

    stable_id: str
    email_subject: str = ""
    email_sender: str = ""
    email_body_snippet: str = ""

    # Tier 0 replay
    tier0_match: bool = False
    tier0_intent_name: str = ""
    tier0_score: float = 0.0
    tier0_method: str = ""
    tier0_matched_keywords: list[str] = field(default_factory=list)
    tier0_stale: bool = False

    # Pipeline classification
    pipeline_categoria: str = ""
    pipeline_acao: str = ""
    pipeline_confianca: float = 0.0

    # Procedure log
    procedure_steps: list[dict[str, Any]] = field(default_factory=list)
    procedure_outcome: str = ""

    # Feedback (if any correction exists)
    has_correction: bool = False
    corrected_categoria: str = ""
    correction_notes: str = ""

    # Proposals
    proposals: list[dict[str, str]] = field(default_factory=list)


def _load_last_run(path: Path | None = None) -> dict[str, dict]:
    """Load last_run.jsonl as {stable_id: entry}."""
    p = path or LAST_RUN_FILE
    if not p.exists():
        return {}
    entries: dict[str, dict] = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                sid = entry.get("email_hash", "")
                if sid:
                    entries[sid] = entry
            except json.JSONDecodeError:
                continue
    return entries


def _load_procedure_records(stable_id: str) -> list[dict[str, Any]]:
    """Find procedure log entries for a given stable_id."""
    from ufpr_automation.procedures.store import ProcedureStore

    store = ProcedureStore()
    all_records = store.list_all()
    return [r.model_dump() for r in all_records if r.email_hash == stable_id]


def _load_feedback_for(stable_id: str) -> dict[str, Any] | None:
    """Find feedback correction for a given stable_id."""
    from ufpr_automation.feedback.store import FeedbackStore

    store = FeedbackStore()
    for rec in store.list_all():
        if rec.email_hash == stable_id:
            return {
                "original_cat": rec.original.categoria,
                "corrected_cat": rec.corrected.categoria,
                "notes": rec.notes,
            }
    return None


def replay_tier0(subject: str, body: str) -> dict[str, Any]:
    """Replay Tier 0 playbook lookup and return diagnostic info."""
    try:
        from ufpr_automation.gmail.thread import split_reply_and_quoted
        from ufpr_automation.procedures.playbook import get_playbook

        split = split_reply_and_quoted(body)
        query_body = split.new_reply or body
        query = f"{subject} {query_body[:500]}"

        playbook = get_playbook()
        if not playbook.intents:
            return {"match": False, "reason": "no intents loaded"}

        match = playbook.lookup(query)
        if match is None:
            return {"match": False, "reason": "no keyword or semantic match above threshold"}

        stale = playbook.is_stale(match.intent)
        return {
            "match": True,
            "intent_name": match.intent.intent_name,
            "score": match.score,
            "method": match.method,
            "matched_keywords": match.matched_keywords,
            "stale": stale,
            "categoria": match.intent.categoria,
        }
    except Exception as e:
        return {"match": False, "reason": f"replay error: {e}"}


def _generate_proposals(trace: DebugTrace) -> list[dict[str, str]]:
    """Generate fix proposals based on the diagnostic trace."""
    proposals: list[dict[str, str]] = []

    if trace.has_correction and trace.corrected_categoria != trace.pipeline_categoria:
        # Pipeline got it wrong
        if not trace.tier0_match:
            proposals.append(
                {
                    "type": "intent_creation",
                    "description": (
                        f"Create a new Tier 0 intent for '{trace.corrected_categoria}' "
                        f"with keywords from this email's subject"
                    ),
                    "risk": "low",
                    "effort": "~10 LoC in PROCEDURES.md",
                }
            )
        elif trace.tier0_match and trace.tier0_stale:
            proposals.append(
                {
                    "type": "intent_refresh",
                    "description": (
                        f"Update last_update on intent '{trace.tier0_intent_name}' "
                        f"— it's stale and fell through to Tier 1"
                    ),
                    "risk": "low",
                    "effort": "~1 line in PROCEDURES.md",
                }
            )

        proposals.append(
            {
                "type": "feedback_entry",
                "description": (
                    f"Add a feedback correction: {trace.pipeline_categoria} → "
                    f"{trace.corrected_categoria} (recorded in feedback store for audit)"
                ),
                "risk": "low",
                "effort": "Already recorded in feedback.jsonl",
            }
        )

    if trace.tier0_match and not trace.has_correction:
        # Tier 0 matched but we don't know if it was right
        proposals.append(
            {
                "type": "review_needed",
                "description": (
                    f"Tier 0 matched intent '{trace.tier0_intent_name}' "
                    f"(score={trace.tier0_score:.2f}, method={trace.tier0_method}). "
                    f"Verify classification is correct."
                ),
                "risk": "info",
                "effort": "Manual review",
            }
        )

    if not trace.tier0_match and not trace.has_correction:
        proposals.append(
            {
                "type": "intent_expansion",
                "description": (
                    f"Consider adding keywords from this email to an existing "
                    f"'{trace.pipeline_categoria}' intent, or create a new intent "
                    f"if none covers this pattern."
                ),
                "risk": "low",
                "effort": "~5 LoC in PROCEDURES.md",
            }
        )

    return proposals


def debug_email(
    stable_id: str,
    *,
    last_run_path: Path | None = None,
) -> DebugTrace:
    """Build a full diagnostic trace for one email."""
    entries = _load_last_run(last_run_path)
    entry = entries.get(stable_id)

    trace = DebugTrace(stable_id=stable_id)

    if entry:
        trace.email_subject = entry.get("subject", "")
        trace.email_sender = entry.get("sender", "")
        trace.email_body_snippet = entry.get("body", "")[:300]

        cls = entry.get("classification", {})
        trace.pipeline_categoria = cls.get("categoria", "")
        trace.pipeline_acao = cls.get("acao_necessaria", "")
        trace.pipeline_confianca = cls.get("confianca", 0.0)

        # Replay Tier 0
        tier0 = replay_tier0(trace.email_subject, entry.get("body", ""))
        trace.tier0_match = tier0.get("match", False)
        trace.tier0_intent_name = tier0.get("intent_name", "")
        trace.tier0_score = tier0.get("score", 0.0)
        trace.tier0_method = tier0.get("method", "")
        trace.tier0_matched_keywords = tier0.get("matched_keywords", [])
        trace.tier0_stale = tier0.get("stale", False)

    # Procedure logs
    proc_records = _load_procedure_records(stable_id)
    if proc_records:
        latest = proc_records[-1]
        trace.procedure_steps = latest.get("steps", [])
        trace.procedure_outcome = latest.get("outcome", "")

    # Feedback corrections
    fb = _load_feedback_for(stable_id)
    if fb:
        trace.has_correction = True
        trace.corrected_categoria = fb["corrected_cat"]
        trace.correction_notes = fb.get("notes", "")

    # Generate proposals
    trace.proposals = _generate_proposals(trace)

    return trace


def format_report(trace: DebugTrace) -> str:
    """Format a DebugTrace as a Markdown report."""
    lines = [
        f"# Classification Debug: {trace.stable_id[:12]}",
        "",
        f"**Subject:** {trace.email_subject}",
        f"**Sender:** {trace.email_sender}",
        f"**Body snippet:** {trace.email_body_snippet[:200]}...",
        "",
        "## Pipeline Classification",
        f"- Categoria: **{trace.pipeline_categoria}**",
        f"- Acao: {trace.pipeline_acao}",
        f"- Confianca: {trace.pipeline_confianca}",
        "",
        "## Tier 0 Replay",
    ]

    if trace.tier0_match:
        lines.extend(
            [
                f"- Match: **YES** (intent: `{trace.tier0_intent_name}`)",
                f"- Score: {trace.tier0_score:.3f}",
                f"- Method: {trace.tier0_method}",
                f"- Keywords matched: {trace.tier0_matched_keywords}",
                f"- Stale: {'YES' if trace.tier0_stale else 'no'}",
            ]
        )
    else:
        lines.append("- Match: **NO** — email went to Tier 1 (RAG + LLM)")

    lines.append("")
    lines.append("## Procedure Log")
    if trace.procedure_steps:
        for step in trace.procedure_steps:
            name = step.get("name", "?")
            result = step.get("result", "?")
            dur = step.get("duration_ms", 0)
            lines.append(f"- {name}: {result} ({dur}ms)")
        lines.append(f"- **Outcome:** {trace.procedure_outcome}")
    else:
        lines.append("- No procedure log found for this stable_id")

    lines.append("")
    lines.append("## Feedback")
    if trace.has_correction:
        lines.extend(
            [
                f"- Corrected to: **{trace.corrected_categoria}**",
                f"- Notes: {trace.correction_notes}"
                if trace.correction_notes
                else "- Notes: (none)",
            ]
        )
    else:
        lines.append("- No human correction on record")

    if trace.proposals:
        lines.append("")
        lines.append("## Proposed Fixes")
        for p in trace.proposals:
            lines.append(f"### [{p['risk']}] {p['type']}")
            lines.append(f"{p['description']}")
            lines.append(f"- Effort: {p['effort']}")
            lines.append("")

    return "\n".join(lines)


def run_debug(
    stable_ids: list[str],
    *,
    last_run_path: Path | None = None,
    report_dir: Path | None = None,
) -> list[DebugTrace]:
    """Debug one or more emails and write reports."""
    out_dir = report_dir or REPORT_BASE
    run_id = uuid.uuid4().hex[:12]
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    traces: list[DebugTrace] = []
    for sid in stable_ids:
        trace = debug_email(sid, last_run_path=last_run_path)
        traces.append(trace)

        report_path = run_dir / f"{sid[:12]}.md"
        report_path.write_text(format_report(trace), encoding="utf-8")
        logger.info("Debug report written: %s", report_path)

    return traces


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="debug_classification",
        description="Diagnose classification decisions for specific emails",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--stable-id",
        type=str,
        help="Debug a specific email by stable_id (prefix match supported)",
    )
    group.add_argument(
        "--last",
        type=int,
        help="Debug the last N emails from last_run.jsonl",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
    )

    if args.stable_id:
        # Support prefix matching
        entries = _load_last_run()
        matches = [sid for sid in entries if sid.startswith(args.stable_id)]
        if not matches:
            print(f"No email found with stable_id starting with '{args.stable_id}'")
            sys.exit(1)
        stable_ids = matches
    else:
        entries = _load_last_run()
        stable_ids = list(entries.keys())[-args.last :]
        if not stable_ids:
            print("No entries found in last_run.jsonl")
            sys.exit(1)

    traces = run_debug(stable_ids)

    for t in traces:
        status = (
            "MISMATCH"
            if t.has_correction and t.corrected_categoria != t.pipeline_categoria
            else "ok"
        )
        tier0_info = f"tier0={t.tier0_intent_name}" if t.tier0_match else "tier1"
        print(f"  [{status}] {t.stable_id[:12]} | {t.pipeline_categoria} | {tier0_info}")

    print(
        f"\n{len(traces)} email(s) debugged. Reports in procedures_data/agent_sdk/debug_classification/"
    )


if __name__ == "__main__":
    main()
