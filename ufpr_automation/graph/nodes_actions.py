"""Action nodes for the LangGraph pipeline.

Split out of ``nodes.py`` for readability. Re-exported from ``nodes`` so
callers that import from ``ufpr_automation.graph.nodes`` keep working.
"""

from __future__ import annotations

import json
from typing import Any

from ufpr_automation.graph.state import EmailState
from ufpr_automation.utils.logging import logger


def capturar_corpus_humano(state: EmailState) -> dict[str, Any]:
    """Copy every Gmail thread where the human already replied into the
    learning corpus label and record an entry in
    ``feedback_data/learning_corpus.jsonl``.

    Runs after ``agir_gmail``. Triggered per-email by
    ``EmailData.already_replied_by_us`` (set by ``perceber_gmail``). After
    a successful capture the CC'd reply is marked read so subsequent
    pipeline runs don't re-process it. Failures are non-fatal — the
    pipeline continues even if Gmail IMAP is momentarily unavailable.
    """
    from datetime import datetime, timezone

    from ufpr_automation.config import settings
    from ufpr_automation.feedback.store import FEEDBACK_DIR
    from ufpr_automation.gmail.client import GmailClient

    label = getattr(settings, "GMAIL_LEARNING_LABEL", "") or ""
    emails = state.get("emails", [])
    classifications = state.get("classifications", {})
    eligible = [e for e in emails if e.already_replied_by_us and e.gmail_message_id]

    if not eligible:
        return {"corpus_captured": []}

    if not label:
        logger.info(
            "Corpus humano: GMAIL_LEARNING_LABEL vazio — %d thread(s) elegivel(is) ignorada(s)",
            len(eligible),
        )
        return {"corpus_captured": []}

    corpus_file = FEEDBACK_DIR / "learning_corpus.jsonl"
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

    # Idempotency — don't re-copy threads already captured in a prior run.
    known_threads: set[str] = set()
    if corpus_file.exists():
        try:
            with corpus_file.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        tid = entry.get("thread_id")
                        if tid:
                            known_threads.add(str(tid))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            logger.warning("Corpus humano: falha ao ler %s: %s", corpus_file, e)

    gmail = GmailClient()
    captured: list[dict[str, Any]] = []

    for email in eligible:
        cls = classifications.get(email.stable_id)
        try:
            count, thread_id = gmail.copy_thread_to_label(email.gmail_message_id, label)
        except Exception as e:
            logger.warning(
                "Corpus humano: exceção copiando thread (stable_id=%s): %s",
                email.stable_id[:8],
                e,
            )
            continue

        if not thread_id:
            logger.debug("Corpus humano: thread não resolvida (stable_id=%s)", email.stable_id[:8])
            continue

        email.thread_id = thread_id

        if thread_id in known_threads:
            logger.debug(
                "Corpus humano: thread %s ja registrada — pulando JSONL",
                thread_id,
            )
        else:
            entry = {
                "thread_id": thread_id,
                "stable_id": email.stable_id,
                "subject": email.subject,
                "sender": email.sender,
                "categoria": cls.categoria if cls else "",
                "intent_name": "",  # populated when Tier 0 matched the thread
                "message_count": count,
                "label": label,
                "labeled_at": datetime.now(timezone.utc).isoformat(),
            }
            # Intent name when available — Tier 0 hit stored in state.
            tier0_hits = set(state.get("tier0_hits", []))
            if email.stable_id in tier0_hits:
                try:
                    from ufpr_automation.procedures.playbook import get_playbook

                    pb = get_playbook()
                    match = pb.lookup(email.body or email.subject)
                    if match:
                        entry["intent_name"] = match.intent.intent_name
                except Exception as e:
                    logger.debug("Corpus humano: intent lookup falhou: %s", e)

            try:
                with corpus_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                known_threads.add(thread_id)
            except OSError as e:
                logger.warning("Corpus humano: falha ao escrever JSONL: %s", e)

            captured.append(entry)

        # Mark the CC'd reply as read so the next run doesn't re-queue it.
        if email.gmail_msg_id:
            try:
                gmail.mark_read(email.gmail_msg_id)
            except Exception as e:
                logger.debug("Corpus humano: falha ao marcar lido: %s", e)

    logger.info(
        "Corpus humano: %d thread(s) capturada(s) no label '%s'",
        len(captured),
        label,
    )
    return {"corpus_captured": captured}
