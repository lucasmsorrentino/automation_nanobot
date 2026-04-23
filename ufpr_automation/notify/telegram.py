"""Telegram notifications for pipeline run summaries.

Uses the Telegram Bot HTTP API directly via ``urllib.request`` so the helper is
synchronous and safe to call from any context (scheduler, end of an async
pipeline, CLI wrappers). Credentials come from ``settings.TELEGRAM_BOT_TOKEN``
and ``settings.TELEGRAM_CHAT_ID``; when either is empty the helpers degrade to
a no-op with a log line — the pipeline never fails because of notifications.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from ufpr_automation.config import settings
from ufpr_automation.utils.logging import logger

TELEGRAM_API = "https://api.telegram.org"
_TIMEOUT_S = 10


def send_message(text: str, parse_mode: str | None = None) -> bool:
    """Send a plain-text message to the configured Telegram chat.

    Returns ``True`` on success, ``False`` otherwise. Never raises — failures
    are logged at ``warning`` level so callers can treat notifications as
    fire-and-forget.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.info("Telegram: bot não configurado — notificação ignorada")
        return False

    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(body) if body else {}
            if result.get("ok") is True:
                return True
            logger.warning("Telegram: resposta sem ok=true: %s", body[:200])
            return False
    except Exception as e:
        logger.warning("Telegram: falha ao enviar mensagem: %s", e)
        return False


def _format_duration(seconds: float) -> str:
    """Render a duration in ``mMsSs`` / ``sSs`` format (no leading zeros)."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def format_run_summary(
    state: dict[str, Any] | None,
    *,
    duration_s: float,
    start_time: datetime,
    channel: str,
    error: str | None = None,
) -> str:
    """Build the Telegram summary text from the final LangGraph state.

    Pass ``error=str(exc)`` (and an empty ``state``) to format a failure
    message. The output is plain text with emojis — no Markdown/HTML — so
    Telegram renders it without escaping concerns.
    """
    header = f"🤖 UFPR Automation — {start_time.strftime('%Y-%m-%d %H:%M')}"
    duration = _format_duration(duration_s)

    if error:
        return f"🔴 {header}\n⏱️ {duration} · canal: {channel}\n\nPipeline falhou:\n{error[:500]}"

    def _count(value: Any) -> int:
        """Return a count from either a collection or an already-tallied int.

        The LangGraph pipeline returns lists/dicts in ``EmailState``; the
        orchestrator (non-langgraph) path returns pre-counted ints. Support
        both so callers don't need to reshape the payload.
        """
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        try:
            return len(value)
        except TypeError:
            return 0

    state = state or {}
    emails = state.get("emails", []) or []
    classifications = state.get("classifications", {}) or {}
    tier0_hits = state.get("tier0_hits", []) or []
    drafts_skipped = state.get("drafts_skipped_already_replied", []) or []
    corpus = state.get("corpus_captured", []) or []
    procedures = int(state.get("procedures_logged", 0) or 0)
    sei_ops = state.get("sei_operations", []) or []
    errors = state.get("errors", []) or []

    total_emails = _count(emails) or _count(state.get("total_unread"))
    drafts_count = _count(state.get("drafts_saved"))
    classified_count = _count(classifications) or _count(state.get("classified"))
    tier0_count = _count(tier0_hits)
    tier1_count = max(0, classified_count - tier0_count)
    sei_success = sum(1 for op in sei_ops if op.get("success") is True)
    sei_failed = sum(1 for op in sei_ops if op.get("op") == "error" or op.get("success") is False)

    lines = [
        header,
        f"📧 {total_emails} email(s) · ⏱️ {duration} · canal: {channel}",
        "",
        f"⚡ Tier 0 (playbook): {tier0_count}",
        f"🧠 Tier 1 (RAG+LLM): {tier1_count}",
        "",
        f"✅ Rascunhos salvos: {drafts_count}",
    ]
    if drafts_skipped:
        lines.append(f"⏭️ Já respondidos pela humana: {len(drafts_skipped)}")
    if corpus:
        lines.append(f"📚 Threads no corpus: {len(corpus)}")
    if sei_ops:
        lines.append(f"📝 SEI ops: {sei_success} ok / {sei_failed} falha(s)")
    if procedures:
        lines.append(f"📒 Procedimentos registrados: {procedures}")
    if errors:
        lines.append(f"🔴 Erros: {len(errors)}")
        first = errors[0]
        node = first.get("node") or "?"
        err = str(first.get("error") or "")[:120]
        lines.append(f"   └─ [{node}] {err}")
    else:
        lines.append("🟢 Sem erros")

    return "\n".join(lines)


def notify_run_summary(
    state: dict[str, Any] | None,
    *,
    duration_s: float,
    start_time: datetime,
    channel: str,
    error: str | None = None,
) -> bool:
    """Format + send a run summary to Telegram. Never raises.

    Thin wrapper around ``format_run_summary`` + ``send_message`` used by
    ``cli.commands`` and ``scheduler`` at the end of every pipeline run.
    """
    try:
        text = format_run_summary(
            state,
            duration_s=duration_s,
            start_time=start_time,
            channel=channel,
            error=error,
        )
    except Exception as e:
        logger.warning("Telegram: falha ao formatar resumo: %s", e)
        return False
    return send_message(text)
