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
_TIMEOUT_S = 30

# Telegram hard limit is 4096 chars per message; stay comfortably under it.
_MAX_MESSAGE_CHARS = 3800
# Cap how many per-email blocks we render to keep the digest scannable.
_MAX_EMAILS_IN_DIGEST = 15
_ACTION_TRUNCATE = 110
_SUBJECT_TRUNCATE = 55


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


def _truncate(text: str, limit: int) -> str:
    """Shorten ``text`` to ``limit`` chars with a single-character ellipsis."""
    text = (text or "").strip().replace("\n", " ").replace("\r", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _priority_rank(
    email: Any,
    *,
    manual_escalation: set[str],
    human_review: set[str],
    auto_draft: set[str],
    drafts_skipped: set[str],
) -> tuple[int, float]:
    """Sort key — smaller = higher priority. Ties broken by lower confidence."""
    sid = getattr(email, "stable_id", "")
    cls = getattr(email, "classification", None)
    categoria = getattr(cls, "categoria", "") if cls else ""
    confianca = float(getattr(cls, "confianca", 0.0) or 0.0) if cls else 0.0
    if categoria == "Urgente":
        return (0, confianca)
    if sid in manual_escalation:
        return (1, confianca)
    if sid in human_review:
        return (2, confianca)
    if sid in auto_draft:
        return (3, -confianca)  # higher conf first inside the auto bucket
    if sid in drafts_skipped:
        return (4, confianca)
    return (5, confianca)


def _render_email_block(
    email: Any,
    *,
    manual_escalation: set[str],
    human_review: set[str],
    auto_draft: set[str],
    drafts_saved: set[str],
    drafts_skipped: set[str],
    tier0_hits: set[str],
) -> str:
    """Format a single email's details for the digest body.

    Output is 3 lines: priority icon + subject, metadata (categoria / conf /
    tier), and the suggested next action. Callers concatenate the blocks with
    blank lines between them.
    """
    sid = getattr(email, "stable_id", "")
    subject = _truncate(getattr(email, "subject", "") or "(sem assunto)", _SUBJECT_TRUNCATE)
    cls = getattr(email, "classification", None)
    categoria = (getattr(cls, "categoria", "") if cls else "") or "—"
    acao = (getattr(cls, "acao_necessaria", "") if cls else "") or ""
    conf = float(getattr(cls, "confianca", 0.0) or 0.0) if cls else 0.0

    is_urgent = categoria == "Urgente"
    if is_urgent:
        prio_icon = "🔴 URGENTE"
    elif sid in manual_escalation:
        prio_icon = "⚠️ Escalação"
    elif sid in human_review:
        prio_icon = "👁️ Revisão"
    elif sid in drafts_skipped:
        prio_icon = "⏭️ Já respondido"
    elif sid in auto_draft or sid in drafts_saved:
        prio_icon = "🤖 Auto-draft"
    else:
        prio_icon = "•"

    tier = "⚡ T0" if sid in tier0_hits else "🧠 T1"
    draft_tag = " · ✅ rascunho salvo" if sid in drafts_saved else ""

    lines = [
        f"{prio_icon} · {subject}",
        f"   📂 {categoria} · 🎯 {int(conf * 100)}% conf. · {tier}{draft_tag}",
    ]
    if acao:
        lines.append(f"   ➜ {_truncate(acao, _ACTION_TRUNCATE)}")
    return "\n".join(lines)


def _format_counts_block(state: dict[str, Any]) -> str:
    """Render the routing-counts strip (Tier 0/1, urgent, auto/review/escalação).

    Two lines: tier breakdown then routing parts. Always non-empty.
    """
    classifications = state["classifications"]
    drafts_count = state["drafts_count"]
    tier0_count = state["tier0_count"]
    tier1_count = state["tier1_count"]
    auto_draft = state["auto_draft"]
    human_review = state["human_review"]
    manual_escalation = state["manual_escalation"]

    urgent_count = sum(
        1 for c in classifications.values() if getattr(c, "categoria", None) == "Urgente"
    )

    routing_parts = []
    if urgent_count:
        routing_parts.append(f"🔴 {urgent_count} urgente(s)")
    routing_parts.append(f"🤖 {len(auto_draft) or drafts_count} auto")
    routing_parts.append(f"👁️ {len(human_review)} revisão")
    routing_parts.append(f"⚠️ {len(manual_escalation)} escalação")

    return (
        f"⚡ Tier 0 (playbook): {tier0_count}   🧠 Tier 1 (RAG+LLM): {tier1_count}\n"
        + " · ".join(routing_parts)
    )


def _format_tier0_block(state: dict[str, Any]) -> str:
    """Render the rascunhos / corpus / procedures strip.

    Multi-line. Returns at least the "Rascunhos salvos" line; conditionally
    appends drafts-skipped, corpus, and procedures rows.
    """
    drafts_count = state["drafts_count"]
    drafts_skipped = state["drafts_skipped"]
    corpus = state["corpus"]
    procedures = state["procedures"]

    lines = [f"✅ Rascunhos salvos: {drafts_count}"]
    if drafts_skipped:
        lines.append(f"⏭️ Já respondidos pela humana: {len(drafts_skipped)}")
    if corpus:
        lines.append(f"📚 Threads no corpus: {len(corpus)}")
    if procedures:
        lines.append(f"📒 Procedimentos: {procedures}")
    return "\n".join(lines)


def _format_sei_ops_block(state: dict[str, Any]) -> str:
    """Render the SEI ops summary, or empty string when no ops were logged."""
    sei_ops = state["sei_ops"]
    if not sei_ops:
        return ""
    sei_success = sum(1 for op in sei_ops if op.get("success") is True)
    sei_failed = sum(1 for op in sei_ops if op.get("op") == "error" or op.get("success") is False)
    return f"📝 SEI ops: {sei_success} ok / {sei_failed} falha(s)"


def _format_errors_block(state: dict[str, Any]) -> str:
    """Render the errors footer (or "no errors" pill)."""
    errors = state["errors"]
    if not errors:
        return "🟢 Sem erros"
    first = errors[0]
    node = first.get("node") or "?"
    err_msg = str(first.get("error") or "")[:120]
    return f"🔴 Erros: {len(errors)}\n   └─ [{node}] {err_msg}"


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

    def _as_set(value: Any) -> set[str]:
        """Coerce a state field into a set of stable_ids.

        Orchestrator path stores pre-counted ints; only the LangGraph state
        supplies actual id lists. When we get an int there's no per-email
        bucket to render, so fall back to an empty set.
        """
        if not value or isinstance(value, int):
            return set()
        try:
            return set(value)
        except TypeError:
            return set()

    state = state or {}
    emails = state.get("emails", []) or []
    classifications = state.get("classifications", {}) or {}
    tier0_hits = _as_set(state.get("tier0_hits"))
    drafts_saved = _as_set(state.get("drafts_saved"))
    drafts_skipped = _as_set(state.get("drafts_skipped_already_replied"))
    auto_draft = _as_set(state.get("auto_draft"))
    human_review = _as_set(state.get("human_review"))
    manual_escalation = _as_set(state.get("manual_escalation"))
    corpus = state.get("corpus_captured", []) or []
    procedures = int(state.get("procedures_logged", 0) or 0)
    sei_ops = state.get("sei_operations", []) or []
    errors = state.get("errors", []) or []

    total_emails = _count(emails) or _count(state.get("total_unread"))
    drafts_count = _count(state.get("drafts_saved"))
    classified_count = _count(classifications) or _count(state.get("classified"))
    tier0_count = len(tier0_hits)
    tier1_count = max(0, classified_count - tier0_count)

    # Bag of pre-computed values shared between the section formatters; keeps
    # each helper's signature simple while preserving the single-pass coerce
    # over the raw state dict above.
    section_state = {
        "classifications": classifications,
        "drafts_count": drafts_count,
        "drafts_skipped": drafts_skipped,
        "tier0_count": tier0_count,
        "tier1_count": tier1_count,
        "auto_draft": auto_draft,
        "human_review": human_review,
        "manual_escalation": manual_escalation,
        "corpus": corpus,
        "procedures": procedures,
        "sei_ops": sei_ops,
        "errors": errors,
    }

    lines = [
        header,
        f"📧 {total_emails} email(s) · ⏱️ {duration} · canal: {channel}",
        "",
        _format_counts_block(section_state),
        _format_tier0_block(section_state),
    ]
    sei_block = _format_sei_ops_block(section_state)
    if sei_block:
        lines.append(sei_block)
    lines.append(_format_errors_block(section_state))

    # Attach classifications to emails when the caller didn't already —
    # the scheduler path hands us raw state without that side-effect.
    emails_with_cls: list[Any] = []
    for e in emails:
        sid = getattr(e, "stable_id", "")
        if getattr(e, "classification", None) is None and sid in classifications:
            try:
                e.classification = classifications[sid]
            except Exception:
                pass
        emails_with_cls.append(e)

    if emails_with_cls:
        ordered = sorted(
            emails_with_cls,
            key=lambda e: _priority_rank(
                e,
                manual_escalation=manual_escalation,
                human_review=human_review,
                auto_draft=auto_draft,
                drafts_skipped=drafts_skipped,
            ),
        )
        visible = ordered[:_MAX_EMAILS_IN_DIGEST]
        lines.append("")
        lines.append("— Detalhes —")
        for i, email in enumerate(visible, 1):
            block = _render_email_block(
                email,
                manual_escalation=manual_escalation,
                human_review=human_review,
                auto_draft=auto_draft,
                drafts_saved=drafts_saved,
                drafts_skipped=drafts_skipped,
                tier0_hits=tier0_hits,
            )
            # Prefix first line with a 1-based index for scannability.
            first_nl = block.find("\n")
            if first_nl == -1:
                block = f"{i}. {block}"
            else:
                block = f"{i}. {block[:first_nl]}\n{block[first_nl + 1 :]}"
            lines.append(block)
        overflow = len(ordered) - len(visible)
        if overflow > 0:
            lines.append(f"… e mais {overflow} email(s) não exibido(s).")

    text = "\n".join(lines)
    if len(text) > _MAX_MESSAGE_CHARS:
        text = text[: _MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return text


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
