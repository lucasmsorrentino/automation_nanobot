"""Node functions for the LangGraph email processing pipeline.

Each function takes the current state and returns a partial state update.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.graph.state import EmailState
from ufpr_automation.utils.logging import logger

# Confidence thresholds for routing
CONFIDENCE_HIGH = 0.95   # auto-draft
CONFIDENCE_MEDIUM = 0.70  # human review


def perceber_gmail(state: EmailState) -> dict[str, Any]:
    """Read unread emails from Gmail IMAP."""
    from ufpr_automation.gmail.client import GmailClient

    try:
        client = GmailClient()
        emails = client.list_unread()
        logger.info("Perceber (Gmail): %d e-mail(s) nao lido(s)", len(emails))
        return {"emails": emails, "errors": state.get("errors", [])}
    except Exception as e:
        logger.error("Perceber (Gmail) falhou: %s", e)
        return {
            "emails": [],
            "errors": state.get("errors", []) + [{"node": "perceber_gmail", "error": str(e)}],
        }


def perceber_owa(state: EmailState) -> dict[str, Any]:
    """Read unread emails from OWA via Playwright.

    Manages its own browser lifecycle: launches Playwright, handles login
    (auto-login with MFA via Telegram if credentials configured), scrapes
    inbox, and closes the browser.
    """
    try:
        emails = asyncio.run(_perceber_owa_async())
        logger.info("Perceber (OWA): %d e-mail(s) nao lido(s)", len(emails))
        return {"emails": emails, "errors": state.get("errors", [])}
    except Exception as e:
        logger.error("Perceber (OWA) falhou: %s", e)
        return {
            "emails": [],
            "errors": state.get("errors", []) + [{"node": "perceber_owa", "error": str(e)}],
        }


async def _perceber_owa_async() -> list:
    """Internal async implementation for OWA scraping with full browser lifecycle."""
    from ufpr_automation.agents.perceber import PerceberAgent
    from ufpr_automation.config.settings import OWA_INBOX_URL
    from ufpr_automation.outlook.browser import (
        auto_login,
        create_browser_context,
        has_credentials,
        has_saved_session,
        is_logged_in,
        launch_browser,
        save_session_state,
    )

    session_exists = has_saved_session()
    credentials_ok = has_credentials()
    use_headless = session_exists or credentials_ok

    pw, browser = await launch_browser(headless=use_headless)
    try:
        context = await create_browser_context(browser, headless=use_headless)
        page = await context.new_page()

        await page.goto(OWA_INBOX_URL, wait_until="domcontentloaded")

        logged_in = await is_logged_in(page)
        if not logged_in:
            login_success = await auto_login(page)
            if not login_success:
                logger.error("OWA login falhou dentro do tempo limite")
                return []
            await save_session_state(context)

        agent = PerceberAgent(page)
        return await agent.run()
    finally:
        await browser.close()
        await pw.stop()


def _get_reflexion_context(emails: list) -> dict[str, str]:
    """Retrieve past error reflections for each email (Reflexion pattern)."""
    try:
        from ufpr_automation.feedback.reflexion import ReflexionMemory
        memory = ReflexionMemory()
        if memory.count() == 0:
            return {}
        contexts = {}
        for email in emails:
            query = f"{email.subject} {(email.body or email.preview)[:200]}"
            ctx = memory.retrieve_formatted(query, top_k=3)
            if ctx:
                contexts[email.stable_id] = ctx
        if contexts:
            logger.info("Reflexion: contexto de erros anteriores para %d e-mail(s)", len(contexts))
        return contexts
    except Exception as e:
        logger.debug("Reflexion nao disponivel: %s", e)
        return {}


def _get_retriever():
    """Get the best available retriever (RAPTOR > flat)."""
    try:
        from ufpr_automation.rag.raptor import RAPTOR_TABLE, STORE_DIR, RaptorRetriever

        import lancedb

        db_path = STORE_DIR / "ufpr.lance"
        if db_path.exists():
            db = lancedb.connect(str(db_path))
            if RAPTOR_TABLE in db.list_tables().tables:
                logger.info("RAG: usando RAPTOR (collapsed tree retrieval)")
                return RaptorRetriever()
    except Exception:
        pass

    from ufpr_automation.rag.retriever import Retriever

    return Retriever()


def _get_graph_context(email) -> str:
    """Retrieve structured context from Neo4j GraphRAG for an email."""
    try:
        from ufpr_automation.graphrag.retriever import GraphRetriever

        retriever = GraphRetriever()
        try:
            ctx = retriever.get_context_for_email(
                subject=email.subject,
                body=email.body or email.preview,
            )
            return ctx
        finally:
            retriever.close()
    except Exception as e:
        logger.debug("GraphRAG nao disponivel: %s", e)
        return ""


def rag_retrieve(state: EmailState) -> dict[str, Any]:
    """Fetch RAG context for each email from the vector store and knowledge graph.

    Combines three context sources:
    1. Vector RAG (RAPTOR/flat) — semantic search over institutional documents
    2. GraphRAG (Neo4j) — structured knowledge: workflows, norms, templates, hierarchy
    3. Reflexion — past error reflections for self-improvement
    """
    emails = state.get("emails", [])
    if not emails:
        return {"rag_contexts": {}}

    try:
        retriever = _get_retriever()
    except Exception as e:
        logger.debug("RAG nao disponivel: %s", e)
        retriever = None

    contexts: dict[str, str] = {}
    for email in emails:
        parts: list[str] = []
        query = f"{email.subject} {(email.body or email.preview)[:300]}"

        # Vector RAG
        if retriever:
            try:
                ctx = retriever.search_formatted(query, top_k=5)
                if ctx and ctx != "Nenhum documento relevante encontrado.":
                    parts.append(ctx)
            except Exception as e:
                logger.debug("RAG falhou para '%s': %s", email.subject[:40], e)

        # GraphRAG (Neo4j)
        graph_ctx = _get_graph_context(email)
        if graph_ctx:
            parts.append(graph_ctx)

        if parts:
            contexts[email.stable_id] = "\n\n".join(parts)

    # Append Reflexion (past error) contexts
    reflexion_contexts = _get_reflexion_context(emails)
    for sid, ref_ctx in reflexion_contexts.items():
        if sid in contexts:
            contexts[sid] += f"\n\n{ref_ctx}"
        else:
            contexts[sid] = ref_ctx

    logger.info("RAG: contexto recuperado para %d/%d e-mail(s)", len(contexts), len(emails))
    return {"rag_contexts": contexts}


def _classify_with_dspy(emails, rag_contexts) -> dict[str, Any]:
    """Classify emails using DSPy modules (optimizable prompts)."""
    import dspy as _dspy

    from ufpr_automation.config import settings
    from ufpr_automation.dspy_modules.modules import (
        SelfRefineModule,
        prediction_to_classification,
    )

    # Configure DSPy LM
    lm = _dspy.LM(model=f"litellm/{settings.LLM_MODEL}", temperature=0.2)
    _dspy.configure(lm=lm)

    # Try loading optimized module
    from ufpr_automation.dspy_modules.optimize import OPTIMIZED_DIR

    module = SelfRefineModule()
    for name in ("mipro_optimized.json", "gepa_optimized.json"):
        path = OPTIMIZED_DIR / name
        if path.exists():
            module.load(str(path))
            logger.info("DSPy: loaded optimized module from %s", path.name)
            break

    results = {}
    for email in emails:
        try:
            rag_ctx = rag_contexts.get(email.stable_id, "")
            pred = module(
                email_subject=email.subject,
                email_body=email.body or email.preview,
                email_sender=email.sender,
                rag_context=rag_ctx,
            )
            results[email.stable_id] = prediction_to_classification(pred)
        except Exception as e:
            logger.warning("DSPy classificacao falhou para '%s': %s", email.subject[:40], e)
    return results


def _classify_with_litellm(emails, rag_contexts) -> dict[str, Any]:
    """Classify emails using direct LiteLLM calls (original approach)."""
    from ufpr_automation.llm.client import LLMClient

    client = LLMClient()

    async def _classify_all():
        import litellm  # noqa: F401
        results = {}
        for email in emails:
            try:
                rag_ctx = rag_contexts.get(email.stable_id)
                cls = await client.classify_email_async(email, rag_context=rag_ctx)
                try:
                    cls = await client.self_refine_async(email, cls, rag_context=rag_ctx)
                except Exception as e:
                    logger.warning("Self-Refine falhou para '%s': %s", email.subject[:40], e)
                results[email.stable_id] = cls
            except Exception as e:
                logger.warning("Classificacao falhou para '%s': %s", email.subject[:40], e)
        return results

    return asyncio.run(_classify_all())


def classificar(state: EmailState) -> dict[str, Any]:
    """Classify emails using LLM with RAG context and Self-Refine.

    Uses DSPy modules if available (pip install dspy), otherwise falls back
    to direct LiteLLM calls. Model cascading routes classification to a
    cheaper/local model when configured (see llm/router.py).
    """
    from ufpr_automation.llm.router import log_cascade_config

    emails = state.get("emails", [])
    rag_contexts = state.get("rag_contexts", {})
    if not emails:
        return {"classifications": {}}

    log_cascade_config()

    try:
        import dspy as _dspy  # noqa: F401
        logger.info("Classificar: usando DSPy modules")
        classifications = _classify_with_dspy(emails, rag_contexts)
    except ImportError:
        logger.info("Classificar: DSPy nao disponivel, usando LiteLLM direto")
        classifications = _classify_with_litellm(emails, rag_contexts)

    logger.info("Classificar: %d/%d e-mail(s) classificados", len(classifications), len(emails))
    return {"classifications": classifications}


def rotear(state: EmailState) -> dict[str, Any]:
    """Route emails by confidence score into auto/review/escalation buckets."""
    classifications = state.get("classifications", {})

    auto_draft: list[str] = []
    human_review: list[str] = []
    manual_escalation: list[str] = []

    for sid, cls in classifications.items():
        if cls.confianca >= CONFIDENCE_HIGH:
            auto_draft.append(sid)
        elif cls.confianca >= CONFIDENCE_MEDIUM:
            human_review.append(sid)
        else:
            manual_escalation.append(sid)

    logger.info(
        "Roteamento: %d auto | %d revisao | %d escalacao",
        len(auto_draft), len(human_review), len(manual_escalation),
    )
    return {
        "auto_draft": auto_draft,
        "human_review": human_review,
        "manual_escalation": manual_escalation,
    }


def _save_run_results(emails: list, classifications: dict) -> None:
    """Save classification results for feedback review CLI.

    Writes a JSONL file that `python -m ufpr_automation.feedback review` reads
    to let the human reviewer accept or correct each classification.
    """
    from ufpr_automation.feedback.store import FEEDBACK_DIR

    results_file = FEEDBACK_DIR / "last_run.jsonl"
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

    email_map = {e.stable_id: e for e in emails}
    with open(results_file, "w", encoding="utf-8") as f:
        for sid, cls in classifications.items():
            email = email_map.get(sid)
            if not email:
                continue
            entry = {
                "email_hash": sid,
                "sender": email.sender,
                "subject": email.subject,
                "body": (email.body or email.preview)[:500],
                "classification": cls.model_dump(),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.debug("Run results saved to %s (%d entries)", results_file, len(classifications))


def registrar_feedback(state: EmailState) -> dict[str, Any]:
    """Record pipeline results in the FeedbackStore for later human review.

    This node runs after classification and routing. It:
    1. Saves the run results to last_run.jsonl (for the `review` CLI command)
    2. Records each classification in the FeedbackStore as a pending entry
       (original == corrected, notes="pipeline-auto") so DSPy has baseline data

    Human reviewers later use `python -m ufpr_automation.feedback review` to
    accept or correct these classifications, which triggers ReflexionMemory
    updates for misclassifications.
    """
    from ufpr_automation.feedback.store import FeedbackStore

    emails = state.get("emails", [])
    classifications = state.get("classifications", {})

    if not classifications:
        return {"feedback_recorded": 0}

    # Save run results for the review CLI
    _save_run_results(emails, classifications)

    # Record each classification in the FeedbackStore
    store = FeedbackStore()
    email_map = {e.stable_id: e for e in emails}
    recorded = 0

    for sid, cls in classifications.items():
        email = email_map.get(sid)
        if not email:
            continue
        try:
            store.add(
                email_hash=sid,
                original=cls,
                corrected=cls,  # same until human corrects
                email_sender=email.sender,
                email_subject=email.subject,
                notes="pipeline-auto",
            )
            recorded += 1
        except Exception as e:
            logger.warning("Feedback: falha ao registrar '%s': %s", email.subject[:40], e)

    logger.info("Feedback: %d classificacao(oes) registrada(s)", recorded)
    return {"feedback_recorded": recorded}


def agir_gmail(state: EmailState) -> dict[str, Any]:
    """Save drafts to Gmail for emails routed to auto_draft or human_review."""
    from ufpr_automation.gmail.client import GmailClient

    emails = state.get("emails", [])
    classifications = state.get("classifications", {})

    # Save drafts for both auto and review — human reviews the draft
    eligible = set(state.get("auto_draft", []) + state.get("human_review", []))

    if not eligible:
        return {"drafts_saved": []}

    email_map = {e.stable_id: e for e in emails}
    gmail = GmailClient()
    saved: list[str] = []

    for sid in eligible:
        email = email_map.get(sid)
        cls = classifications.get(sid)
        if not email or not cls or not cls.sugestao_resposta.strip():
            continue

        sender = email.sender
        if "<" in sender and ">" in sender:
            sender = sender.split("<")[1].rstrip(">")

        ok = gmail.save_draft(
            to_addr=sender,
            subject=email.subject,
            body=cls.sugestao_resposta,
            in_reply_to=email.gmail_message_id,
        )
        if ok:
            saved.append(sid)
            gmail.mark_read(email.gmail_msg_id)

    logger.info("Agir (Gmail): %d rascunho(s) salvo(s)", len(saved))
    return {"drafts_saved": saved}
