"""Feedback Review Chat — interactive Claude CLI session for reviewing classifications.

Complements (does NOT replace) the Streamlit feedback UI. Builds a bootstrap
briefing from the latest pipeline run and launches ``claude`` in interactive
mode with the context pre-loaded.

**Streamlit remains mandatory fallback.** This module is strictly additive —
never import anything from ``agent_sdk/`` in ``feedback/web.py``.

See ``SDD_CLAUDE_CODE_AUTOMATIONS.md §4`` for the full spec.

CLI::

    python -m ufpr_automation.agent_sdk.feedback_chat
    python -m ufpr_automation.agent_sdk.feedback_chat --bootstrap-only  # print and exit
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ufpr_automation.config import settings

logger = logging.getLogger(__name__)

FEEDBACK_DIR = settings.FEEDBACK_DATA_DIR
LAST_RUN_FILE = FEEDBACK_DIR / "last_run.jsonl"
CHAT_DIR = settings.PACKAGE_ROOT / "procedures_data" / "agent_sdk" / "feedback_chat"
BRIEFING_PATH = Path(__file__).parent / "skills" / "feedback_chat_bootstrap.md"


@dataclass
class ChatSession:
    """A prepared feedback-chat session."""

    run_id: str
    session_dir: Path
    bootstrap_prompt: str
    last_run_summary: dict[str, Any] = field(default_factory=dict)


def _load_last_run(path: Path | None = None) -> list[dict]:
    """Load last_run.jsonl as a list of entries (ordered)."""
    p = path or LAST_RUN_FILE
    if not p.exists():
        return []
    entries: list[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def summarize_last_run(entries: list[dict]) -> dict[str, Any]:
    """Build a summary of the last pipeline run.

    Returns counts by category, action, and confidence bucket.
    """
    if not entries:
        return {
            "total": 0,
            "by_categoria": {},
            "by_acao": {},
            "confidence_buckets": {"high": 0, "medium": 0, "low": 0},
        }

    by_categoria: dict[str, int] = {}
    by_acao: dict[str, int] = {}
    high = med = low = 0

    for e in entries:
        cls = e.get("classification", {}) or {}
        cat = cls.get("categoria", "")
        acao = cls.get("acao_necessaria", "")
        conf = float(cls.get("confianca", 0.0) or 0.0)

        by_categoria[cat] = by_categoria.get(cat, 0) + 1
        by_acao[acao] = by_acao.get(acao, 0) + 1
        if conf >= 0.85:
            high += 1
        elif conf >= 0.60:
            med += 1
        else:
            low += 1

    return {
        "total": len(entries),
        "by_categoria": by_categoria,
        "by_acao": by_acao,
        "confidence_buckets": {"high": high, "medium": med, "low": low},
    }


def _load_briefing() -> str:
    """Load the briefing template from skills/feedback_chat_bootstrap.md."""
    if not BRIEFING_PATH.exists():
        logger.warning("Briefing not found: %s — using minimal default", BRIEFING_PATH)
        return "Você vai ajudar a revisar classificações do pipeline de emails da UFPR."
    return BRIEFING_PATH.read_text(encoding="utf-8")


def build_bootstrap_prompt(entries: list[dict], summary: dict[str, Any]) -> str:
    """Construct the full bootstrap prompt for the Claude CLI."""
    briefing = _load_briefing()

    lines = [
        briefing,
        "",
        "---",
        "",
        "## Última execução do pipeline",
        "",
        f"- Total de emails: {summary['total']}",
        "",
        "### Por categoria",
    ]
    for cat, count in sorted(summary["by_categoria"].items(), key=lambda x: -x[1]):
        lines.append(f"- {cat or '(vazio)'}: {count}")

    lines.append("")
    lines.append("### Por ação necessária")
    for acao, count in sorted(summary["by_acao"].items(), key=lambda x: -x[1]):
        lines.append(f"- {acao or '(vazio)'}: {count}")

    lines.append("")
    lines.append("### Confiança")
    cb = summary["confidence_buckets"]
    lines.append(f"- Alta (>=0.85): {cb['high']}")
    lines.append(f"- Média (0.60-0.85): {cb['medium']}")
    lines.append(f"- Baixa (<0.60): {cb['low']}")
    lines.append("")

    # Show up to 20 email summaries so the agent has context
    lines.append("## Emails (primeiros 20)")
    for i, e in enumerate(entries[:20], start=1):
        cls = e.get("classification", {}) or {}
        sid = e.get("email_hash", "?")[:12]
        subject = (e.get("subject") or "(sem assunto)")[:80]
        sender = e.get("sender", "?")
        cat = cls.get("categoria", "?")
        conf = cls.get("confianca", 0.0)
        lines.append(
            f"{i}. [{sid}] {sender} | \"{subject}\" → **{cat}** (conf={conf})"
        )

    if len(entries) > 20:
        lines.append("")
        lines.append(f"... e mais {len(entries) - 20} emails")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "Comece apresentando um resumo curto e pergunte qual email o operador "
        "quer revisar primeiro. Use o stable_id (primeiros 12 chars) como referência."
    )

    return "\n".join(lines)


def prepare_session(
    *,
    last_run_path: Path | None = None,
    chat_dir: Path | None = None,
) -> ChatSession:
    """Build a ChatSession without launching Claude yet."""
    entries = _load_last_run(last_run_path)
    summary = summarize_last_run(entries)

    run_id = uuid.uuid4().hex[:12]
    out_dir = chat_dir or CHAT_DIR
    session_dir = out_dir / run_id
    session_dir.mkdir(parents=True, exist_ok=True)

    bootstrap = build_bootstrap_prompt(entries, summary)

    # Save bootstrap for audit + replay
    (session_dir / "bootstrap.md").write_text(bootstrap, encoding="utf-8")
    (session_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Save start timestamp
    meta = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_emails": summary["total"],
    }
    (session_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Feedback chat session prepared at %s (run_id=%s)", session_dir, run_id)
    return ChatSession(
        run_id=run_id,
        session_dir=session_dir,
        bootstrap_prompt=bootstrap,
        last_run_summary=summary,
    )


def launch_claude(session: ChatSession) -> int:
    """Launch ``claude`` interactively, feeding the bootstrap prompt on stdin.

    Returns the subprocess exit code. Falls back gracefully if claude is
    unavailable.
    """
    from ufpr_automation.agent_sdk.runner import is_claude_available

    if not is_claude_available():
        print(
            "\n[feedback_chat] claude CLI não disponível. Use o fallback Streamlit:",
            "\n  streamlit run ufpr_automation/feedback/web.py",
            "\n\nBootstrap gerado em:",
            session.session_dir / "bootstrap.md",
            file=sys.stderr,
        )
        return 2

    bootstrap_path = session.session_dir / "bootstrap.md"
    print(
        f"\n[feedback_chat] Iniciando sessão {session.run_id} — "
        f"bootstrap em {bootstrap_path}\n",
        file=sys.stderr,
    )

    # Interactive claude — feed bootstrap via stdin but keep stdout/stderr on tty
    try:
        proc = subprocess.Popen(
            ["claude"],
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        proc.stdin.write(session.bootstrap_prompt)
        proc.stdin.close()
        return proc.wait()
    except Exception as e:
        logger.error("Failed to launch claude: %s", e)
        return 1


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="feedback_chat",
        description="Open a Claude interactive session pre-briefed with the latest pipeline run",
    )
    parser.add_argument(
        "--bootstrap-only", action="store_true",
        help="Build the bootstrap prompt and print it to stdout (do NOT launch claude)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
    )

    session = prepare_session()

    if args.bootstrap_only:
        print(session.bootstrap_prompt)
        sys.exit(0)

    exit_code = launch_claude(session)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
