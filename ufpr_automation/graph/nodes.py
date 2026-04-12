"""Node functions for the LangGraph email processing pipeline.

Each function takes the current state and returns a partial state update.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ufpr_automation.graph.state import EmailState
from ufpr_automation.utils.logging import logger

# Confidence thresholds for routing
CONFIDENCE_HIGH = 0.95   # auto-draft
CONFIDENCE_MEDIUM = 0.70  # human review


def perceber_gmail(state: EmailState) -> dict[str, Any]:
    """Read unread emails from Gmail IMAP."""
    from ufpr_automation.gmail.client import GmailClient

    limit = state.get("limit")
    try:
        client = GmailClient()
        emails = client.list_unread(limit=limit) if limit is not None else client.list_unread()
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
    limit = state.get("limit")
    try:
        emails = asyncio.run(_perceber_owa_async())
        if limit is not None:
            emails = emails[:limit]
        logger.info("Perceber (OWA): %d e-mail(s) nao lido(s)", len(emails))
        return {"emails": emails, "errors": state.get("errors", [])}
    except Exception as e:
        logger.error("Perceber (OWA) falhou: %s", e)
        return {
            "emails": [],
            "errors": state.get("errors", []) + [{"node": "perceber_owa", "error": str(e)}],
        }


def tier0_lookup(state: EmailState) -> dict[str, Any]:
    """Route each email through the Tier 0 playbook (Hybrid Memory).

    For each email, we score against the playbook:
      - Keyword match (regex) → score 1.0 → instant Tier 0
      - Semantic match (e5-large cosine) → score > 0.90 → Tier 0
      - Otherwise → fall through to Tier 1 (rag_retrieve + classificar)

    Tier 0 hits get a fully-formed :class:`EmailClassification` produced
    locally from the intent template — *no* RAG retrieval and *no* LLM
    classification call. ``rag_retrieve`` and ``classificar`` skip any
    email already present in ``state['classifications']``.

    Staleness: if ``intent.last_update`` is older than the RAG store mtime
    we treat the intent as out-of-date and force a Tier 1 fallback.
    """
    emails = state.get("emails", [])
    if not emails:
        return {"tier0_hits": [], "classifications": {}}

    try:
        from ufpr_automation.procedures.playbook import (
            extract_variables,
            get_playbook,
            missing_required_fields,
        )
    except Exception as e:  # pragma: no cover - import-time failures only
        logger.warning("Tier 0: playbook indisponivel: %s", e)
        return {"tier0_hits": [], "classifications": {}}

    from ufpr_automation.core.models import EmailClassification
    from ufpr_automation.gmail.thread import split_reply_and_quoted

    playbook = get_playbook()
    if not playbook.intents:
        logger.info("Tier 0: nenhum intent carregado — pulando")
        return {"tier0_hits": [], "classifications": {}}

    hits: list[str] = []
    classifications: dict[str, Any] = {}
    stale_count = 0
    missing_count = 0

    for email in emails:
        # Use only the new reply (not the quoted history) so the lookup
        # query reflects what the sender is asking *now*.
        split = split_reply_and_quoted(email.body or email.preview)
        query_body = split.new_reply or (email.body or email.preview)
        query = f"{email.subject} {query_body[:500]}"

        match = playbook.lookup(query)
        if match is None:
            continue

        if playbook.is_stale(match.intent):
            logger.info(
                "Tier 0: intent '%s' STALE (last_update=%s) — fallback Tier 1",
                match.intent.intent_name,
                match.intent.last_update,
            )
            stale_count += 1
            continue

        # Extract variables and validate required fields
        variables = extract_variables(email, match.intent)
        missing = missing_required_fields(match.intent, variables)
        if missing:
            logger.info(
                "Tier 0: intent '%s' faltando %s — fallback Tier 1",
                match.intent.intent_name,
                ", ".join(missing),
            )
            missing_count += 1
            continue

        draft = playbook.fill(match.intent, variables)
        # Confidence = intent.confidence × match score (semantic ≤ 1.0).
        # Keyword matches keep the intent's declared confidence intact.
        confianca = max(0.0, min(1.0, match.intent.confidence * match.score))

        try:
            cls = EmailClassification(
                categoria=match.intent.categoria,
                resumo=f"Tier 0 ({match.method}): {match.intent.intent_name}",
                acao_necessaria=match.intent.action,
                sugestao_resposta=draft,
                confianca=confianca,
            )
        except Exception as e:
            logger.warning(
                "Tier 0: classificacao invalida para intent '%s': %s",
                match.intent.intent_name,
                e,
            )
            continue

        classifications[email.stable_id] = cls
        hits.append(email.stable_id)
        logger.info(
            "Tier 0 HIT [%s/%.2f] '%s' -> %s (%s)",
            match.method,
            match.score,
            email.subject[:40],
            match.intent.intent_name,
            match.intent.categoria,
        )

    logger.info(
        "Tier 0: %d hit(s) | %d stale | %d missing fields | %d -> Tier 1",
        len(hits),
        stale_count,
        missing_count,
        len(emails) - len(hits),
    )
    return {"tier0_hits": hits, "classifications": classifications}


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


def _get_reflexion_context_single(email) -> str:
    """Retrieve past error reflections for a single email (Reflexion pattern).

    Single-email variant of :func:`_get_reflexion_context`, used by the
    Fleet sub-agent (:func:`ufpr_automation.graph.fleet.process_one_email`)
    which operates on one email at a time. Returns a formatted context
    string, or empty string if ReflexionMemory is unavailable or empty.
    """
    try:
        from ufpr_automation.feedback.reflexion import ReflexionMemory
        memory = ReflexionMemory()
        if memory.count() == 0:
            return ""
        query = f"{email.subject} {(email.body or email.preview)[:200]}"
        ctx = memory.retrieve_formatted(query, top_k=3)
        return ctx or ""
    except Exception as e:
        logger.debug("Reflexion (single) nao disponivel: %s", e)
        return ""


def _get_retriever():
    """Get the best available retriever (RAPTOR > flat)."""
    try:
        import lancedb

        from ufpr_automation.rag.raptor import RAPTOR_TABLE, STORE_DIR, RaptorRetriever

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

    # Skip Tier 0 hits — they were already classified by tier0_lookup
    # without paying the RAG retrieval cost. Only Tier 1 emails need RAG.
    tier0_hits = set(state.get("tier0_hits", []))
    tier1_emails = [e for e in emails if e.stable_id not in tier0_hits]

    if not tier1_emails:
        logger.info("RAG: todos os e-mails atendidos pelo Tier 0 — pulando RAG")
        return {"rag_contexts": {}}

    try:
        retriever = _get_retriever()
    except Exception as e:
        logger.debug("RAG nao disponivel: %s", e)
        retriever = None

    from ufpr_automation.gmail.thread import split_reply_and_quoted

    contexts: dict[str, str] = {}
    for email in tier1_emails:
        parts: list[str] = []
        # Use only the new reply (not the quoted history) for RAG retrieval.
        # The quoted history is noise that drags the query off-topic toward
        # whatever the previous message was about.
        split = split_reply_and_quoted(email.body or email.preview)
        query_body = split.new_reply or (email.body or email.preview)
        query = f"{email.subject} {query_body[:300]}"

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

    # Append Reflexion (past error) contexts — Tier 1 emails only
    reflexion_contexts = _get_reflexion_context(tier1_emails)
    for sid, ref_ctx in reflexion_contexts.items():
        if sid in contexts:
            contexts[sid] += f"\n\n{ref_ctx}"
        else:
            contexts[sid] = ref_ctx

    logger.info(
        "RAG: contexto recuperado para %d/%d e-mail(s) Tier 1",
        len(contexts),
        len(tier1_emails),
    )
    return {"rag_contexts": contexts}


def _compiled_prompt_paths() -> list:
    """Return candidate compiled prompt paths for DSPy.
    Imports OPTIMIZED_DIR lazily so settings reloads / monkeypatches work in tests.
    """
    from ufpr_automation.dspy_modules.optimize import OPTIMIZED_DIR as _OPT_DIR
    return [
        _OPT_DIR / "gepa_optimized.json",
        _OPT_DIR / "mipro_optimized.json",
    ]


def _has_compiled_prompt() -> bool:
    """True if at least one compiled DSPy prompt file exists on disk."""
    return any(p.exists() for p in _compiled_prompt_paths())


def _should_use_dspy() -> bool:
    """Tri-state gate for DSPy activation (see settings.USE_DSPY).

    - "off" / "0" / "false" -> never use DSPy.
    - "on"  / "1" / "true"  -> require DSPy + compiled file (raises otherwise).
    - "auto" (default)      -> use DSPy only if dspy importable AND compiled
      prompt file exists; otherwise fall back silently.
    """
    from ufpr_automation.config import settings

    flag = (getattr(settings, "USE_DSPY", "auto") or "auto").lower().strip()

    if flag in ("off", "0", "false", "no"):
        return False

    if flag in ("on", "1", "true", "yes"):
        try:
            import dspy  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "USE_DSPY=1 but dspy package not installed. "
                "Install with: pip install -e '.[marco2]'"
            ) from e
        if not _has_compiled_prompt():
            raise RuntimeError(
                "USE_DSPY=1 but no compiled prompt file found in "
                "dspy_modules/optimized/ (expected gepa_optimized.json or "
                "mipro_optimized.json). Run: "
                "python -m ufpr_automation.dspy_modules.optimize --strategy gepa"
            )
        return True

    # "auto" (default)
    try:
        import dspy  # noqa: F401
    except ImportError:
        return False
    if not _has_compiled_prompt():
        logger.info(
            "DSPy USE_DSPY=auto but no compiled prompts yet; "
            "falling back to litellm"
        )
        return False
    return True


def _classify_with_dspy(emails, rag_contexts) -> dict[str, Any]:
    """Classify emails using DSPy modules (optimizable prompts).

    Raises RuntimeError if called without a compiled file. The
    ``_should_use_dspy()`` gate should prevent that, but the defensive
    check helps debugging.
    """
    import dspy as _dspy

    from ufpr_automation.config import settings
    from ufpr_automation.dspy_modules.modules import (
        SelfRefineModule,
        prediction_to_classification,
    )

    lm = _dspy.LM(model=settings.LLM_MODEL, temperature=0.2)
    _dspy.configure(lm=lm)

    module = SelfRefineModule()
    loaded: str | None = None
    for path in _compiled_prompt_paths():
        if path.exists():
            module.load(str(path))
            logger.info("DSPy: loaded optimized module from %s", path.name)
            loaded = path.name
            break

    if loaded is None:
        raise RuntimeError(
            "_classify_with_dspy called without a compiled prompt file. "
            "This indicates the USE_DSPY gate was bypassed — check "
            "_should_use_dspy() invariants."
        )

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

    Tier 0 hits (already classified by ``tier0_lookup``) are preserved
    untouched. Only emails missing from ``state['classifications']`` are
    sent to the LLM. The two sets are merged before being returned to the
    state, since LangGraph replaces dict values rather than merging them.
    """
    from ufpr_automation.llm.router import log_cascade_config

    emails = state.get("emails", [])
    rag_contexts = state.get("rag_contexts", {})
    existing = dict(state.get("classifications") or {})

    if not emails:
        return {"classifications": existing}

    # Tier 1 = emails not yet classified by Tier 0
    tier1_emails = [e for e in emails if e.stable_id not in existing]

    if not tier1_emails:
        logger.info(
            "Classificar: %d e-mail(s) atendido(s) pelo Tier 0 — pulando LLM",
            len(existing),
        )
        return {"classifications": existing}

    log_cascade_config()

    if _should_use_dspy():
        logger.info("Classificar: usando DSPy modules (compiled prompt)")
        new_results = _classify_with_dspy(tier1_emails, rag_contexts)
    else:
        logger.info("Classificar: usando LiteLLM direto (no DSPy)")
        new_results = _classify_with_litellm(tier1_emails, rag_contexts)

    merged = {**existing, **new_results}
    logger.info(
        "Classificar: %d Tier 0 + %d Tier 1 = %d/%d total",
        len(existing),
        len(new_results),
        len(merged),
        len(emails),
    )
    return {"classifications": merged}


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


def consultar_sei(state: EmailState) -> dict[str, Any]:
    """Consult SEI for emails that mention a process number.

    Only runs for emails classified as 'Estagios' that contain a SEI process
    number pattern (XXXXX.XXXXXX/XXXX-XX). READ-ONLY: no data is submitted.
    """
    emails = state.get("emails", [])
    classifications = state.get("classifications", {})
    if not emails:
        return {"sei_contexts": {}}

    from ufpr_automation.sei.client import extract_sei_process_number

    # Identify emails that need SEI consultation
    sei_candidates: dict[str, str] = {}  # stable_id -> process number
    for email in emails:
        cls = classifications.get(email.stable_id)
        if not cls or cls.categoria != "Estágios":
            continue
        text = f"{email.subject} {email.body or email.preview}"
        proc_num = extract_sei_process_number(text)
        if proc_num:
            sei_candidates[email.stable_id] = proc_num

    if not sei_candidates:
        return {"sei_contexts": {}}

    # Check if Playwright is available (SEI requires browser automation)
    try:
        from ufpr_automation.sei.browser import has_credentials as sei_has_credentials
    except ImportError:
        logger.info("SEI: playwright nao instalado, pulando consultas")
        return {"sei_contexts": {}}

    if not sei_has_credentials():
        logger.info("SEI: credenciais nao configuradas, pulando consultas")
        return {"sei_contexts": {}}

    # Run SEI consultations
    sei_results = asyncio.run(_consult_sei_async(sei_candidates))
    logger.info("SEI: %d consulta(s) realizadas", len(sei_results))
    return {"sei_contexts": sei_results}


async def _consult_sei_async(candidates: dict[str, str]) -> dict[str, Any]:
    """Internal async implementation for SEI consultations."""
    from ufpr_automation.config.settings import SEI_URL
    from ufpr_automation.sei.browser import (
        auto_login,
        create_browser_context,
        is_logged_in,
        launch_browser,
        save_session_state,
    )
    from ufpr_automation.sei.client import SEIClient

    results: dict[str, Any] = {}
    pw, browser = await launch_browser(headless=True)
    try:
        context = await create_browser_context(browser)
        page = await context.new_page()
        await page.goto(SEI_URL, wait_until="domcontentloaded")

        if not await is_logged_in(page):
            if not await auto_login(page):
                logger.error("SEI: login falhou")
                return results
            await save_session_state(context)

        client = SEIClient(page)
        for stable_id, proc_num in candidates.items():
            processo = await client.search_process(proc_num)
            if processo:
                results[stable_id] = {
                    "numero": processo.numero,
                    "status": processo.status,
                    "documentos": len(processo.documentos),
                    "interessados": processo.interessados,
                    "observacoes": processo.observacoes[:300] if processo.observacoes else "",
                }
    except Exception as e:
        logger.error("SEI: erro durante consultas: %s", e)
    finally:
        await browser.close()
        await pw.stop()
    return results


def consultar_siga(state: EmailState) -> dict[str, Any]:
    """Consult SIGA for emails that mention a student GRR.

    Only runs for emails classified as 'Estagios' that contain a GRR pattern.
    READ-ONLY: no data is submitted. Validates internship eligibility.
    """
    emails = state.get("emails", [])
    classifications = state.get("classifications", {})
    if not emails:
        return {"siga_contexts": {}}

    from ufpr_automation.sei.client import extract_grr

    # Identify emails that need SIGA consultation
    siga_candidates: dict[str, str] = {}  # stable_id -> GRR
    for email in emails:
        cls = classifications.get(email.stable_id)
        if not cls or cls.categoria != "Estágios":
            continue
        text = f"{email.subject} {email.body or email.preview}"
        grr = extract_grr(text)
        if grr:
            siga_candidates[email.stable_id] = grr

    if not siga_candidates:
        return {"siga_contexts": {}}

    try:
        from ufpr_automation.siga.browser import has_credentials as siga_has_credentials
    except ImportError:
        logger.info("SIGA: playwright nao instalado, pulando consultas")
        return {"siga_contexts": {}}

    if not siga_has_credentials():
        logger.info("SIGA: credenciais nao configuradas, pulando consultas")
        return {"siga_contexts": {}}

    siga_results = asyncio.run(_consult_siga_async(siga_candidates))
    logger.info("SIGA: %d consulta(s) realizadas", len(siga_results))
    return {"siga_contexts": siga_results}


async def _consult_siga_async(candidates: dict[str, str]) -> dict[str, Any]:
    """Internal async implementation for SIGA consultations."""
    from ufpr_automation.config.settings import SIGA_URL
    from ufpr_automation.siga.browser import (
        auto_login,
        create_browser_context,
        is_logged_in,
        launch_browser,
        save_session_state,
    )
    from ufpr_automation.siga.client import SIGAClient

    results: dict[str, Any] = {}
    pw, browser = await launch_browser(headless=True)
    try:
        context = await create_browser_context(browser)
        page = await context.new_page()
        await page.goto(SIGA_URL, wait_until="domcontentloaded")

        if not await is_logged_in(page):
            if not await auto_login(page):
                logger.error("SIGA: login falhou")
                return results
            await save_session_state(context)

        client = SIGAClient(page)
        for stable_id, grr in candidates.items():
            eligibility = await client.validate_internship_eligibility(grr)
            result_data: dict[str, Any] = {
                "grr": grr,
                "eligible": eligibility.eligible,
                "reasons": eligibility.reasons,
                "warnings": eligibility.warnings,
            }
            if eligibility.student:
                result_data["nome"] = eligibility.student.nome
                result_data["situacao"] = eligibility.student.situacao
                result_data["curso"] = eligibility.student.curso
            results[stable_id] = result_data
    except Exception as e:
        logger.error("SIGA: erro durante consultas: %s", e)
    finally:
        await browser.close()
        await pw.stop()
    return results


def _consult_sei_for_email(email, classification) -> dict[str, Any] | None:
    """Single-email SEI consultation used by Fleet sub-agents.

    Extracts the process number from the email, spins up a SEI Playwright
    session, and returns the data dict that would have been stored under
    ``state["sei_contexts"][email.stable_id]`` by the batch
    :func:`consultar_sei` node. Returns ``None`` if the classification is
    not Estágios, no process number is present, Playwright / credentials
    are missing, or the consultation fails.
    """
    if classification is None or classification.categoria != "Estágios":
        return None

    from ufpr_automation.sei.client import extract_sei_process_number

    text = f"{email.subject} {email.body or email.preview}"
    proc_num = extract_sei_process_number(text)
    if not proc_num:
        return None

    try:
        from ufpr_automation.sei.browser import has_credentials as sei_has_credentials
    except ImportError:
        logger.info("SEI (single): playwright nao instalado, pulando")
        return None

    if not sei_has_credentials():
        logger.info("SEI (single): credenciais nao configuradas, pulando")
        return None

    try:
        results = asyncio.run(_consult_sei_async({email.stable_id: proc_num}))
    except Exception as e:
        logger.warning("SEI (single) consulta falhou para '%s': %s", email.subject[:40], e)
        return None

    return results.get(email.stable_id)


def _consult_siga_for_email(email, classification) -> dict[str, Any] | None:
    """Single-email SIGA consultation used by Fleet sub-agents.

    Extracts the GRR from the email, spins up a SIGA Playwright session,
    and returns the data dict that would have been stored under
    ``state["siga_contexts"][email.stable_id]`` by the batch
    :func:`consultar_siga` node. Returns ``None`` if the classification is
    not Estágios, no GRR is present, Playwright / credentials are missing,
    or the consultation fails.
    """
    if classification is None or classification.categoria != "Estágios":
        return None

    from ufpr_automation.sei.client import extract_grr

    text = f"{email.subject} {email.body or email.preview}"
    grr = extract_grr(text)
    if not grr:
        return None

    try:
        from ufpr_automation.siga.browser import has_credentials as siga_has_credentials
    except ImportError:
        logger.info("SIGA (single): playwright nao instalado, pulando")
        return None

    if not siga_has_credentials():
        logger.info("SIGA (single): credenciais nao configuradas, pulando")
        return None

    try:
        results = asyncio.run(_consult_siga_async({email.stable_id: grr}))
    except Exception as e:
        logger.warning("SIGA (single) consulta falhou para '%s': %s", email.subject[:40], e)
        return None

    return results.get(email.stable_id)


def registrar_procedimento(state: EmailState) -> dict[str, Any]:
    """Log the procedure steps executed for each email in this pipeline run.

    Records what was done, how long it took, and the outcome, so the system
    can learn which procedures are most efficient over time.
    """
    import uuid

    from ufpr_automation.procedures.store import ProcedureRecord, ProcedureStep, ProcedureStore

    emails = state.get("emails", [])
    classifications = state.get("classifications", {})
    drafts_saved = set(state.get("drafts_saved", []))
    sei_contexts = state.get("sei_contexts", {})
    siga_contexts = state.get("siga_contexts", {})
    manual_escalation = set(state.get("manual_escalation", []))

    store = ProcedureStore()
    run_id = uuid.uuid4().hex[:12]
    logged = 0

    email_map = {e.stable_id: e for e in emails}
    for sid, cls in classifications.items():
        email = email_map.get(sid)
        if not email:
            continue

        steps: list[ProcedureStep] = [
            ProcedureStep(name="perceber", result="ok"),
            ProcedureStep(name="classificar", result="ok"),
        ]

        if sid in sei_contexts:
            steps.append(ProcedureStep(name="consultar_sei", result="ok"))
        if sid in siga_contexts:
            steps.append(ProcedureStep(name="consultar_siga", result="ok"))

        if sid in drafts_saved:
            steps.append(ProcedureStep(name="agir_draft", result="ok"))
            outcome = "draft_saved"
        elif sid in manual_escalation:
            outcome = "escalated"
        else:
            outcome = "human_review"

        record = ProcedureRecord(
            run_id=run_id,
            email_hash=sid,
            email_subject=email.subject[:100],
            email_categoria=cls.categoria,
            steps=steps,
            outcome=outcome,
            sei_process=sei_contexts.get(sid, {}).get("numero", ""),
            siga_grr=siga_contexts.get(sid, {}).get("grr", ""),
        )
        store.add(record)
        logged += 1

    logger.info("Procedimentos: %d registro(s) gravado(s) (run_id=%s)", logged, run_id)
    return {"procedures_logged": logged}


def agir_estagios(state: EmailState) -> dict[str, Any]:
    """Process Estágios emails that have a Tier 0 intent with sei_action != 'none'.

    Flow per eligible email:
        1. Run blocking_checks via ``procedures/checkers.run_checks``
        2. If hard_blocks → draft reply listing blockers (no SEI ops)
        3. If soft_blocks → draft reply requesting justification (no SEI ops)
        4. If all pass → SEIWriter chain:
           a. create_process (if sei_action == "create_process")
           b. attach_document(s) (for each required_attachment found)
           c. save_despacho_draft (using intent.despacho_template)
           d. update classification.sugestao_resposta with acuse

    This node runs BETWEEN registrar_feedback and agir_gmail. Emails
    processed here still flow through agir_gmail for the draft save step.
    """
    import asyncio

    from ufpr_automation.procedures.checkers import CheckContext, run_checks
    from ufpr_automation.procedures.doc_catalog import get_doc_classification
    from ufpr_automation.procedures.playbook import (
        extract_variables,
        fill_template,
        get_playbook,
    )

    emails = state.get("emails", [])
    classifications = state.get("classifications", {})
    tier0_hits = set(state.get("tier0_hits", []))
    sei_ops: list[dict] = []
    errors = []

    playbook = get_playbook()
    email_map = {e.stable_id: e for e in emails}

    for sid in tier0_hits:
        email = email_map.get(sid)
        cls = classifications.get(sid)
        if not email or not cls:
            continue

        # Only Estágios with SEI action
        if cls.categoria != "Estágios":
            continue

        # Look up the Tier 0 intent to get sei_action + blocking_checks
        match = playbook.lookup(email.body or email.subject)
        if not match or match.intent.sei_action == "none":
            continue

        intent = match.intent
        vars_ = extract_variables(email, intent)

        # Build check context with available SIGA/SEI data
        siga = state.get("siga_contexts", {}).get(sid, {})
        sei = state.get("sei_contexts", {}).get(sid, {})
        ctx = CheckContext(
            email=email, intent=intent, vars=vars_,
            siga_context=siga, sei_context=sei,
        )

        # Run blocking checks
        summary = run_checks(intent, ctx)

        if summary.hard_blocks:
            # Draft refusal email listing the hard blocks
            block_lines = "\n".join(
                f"- {r.check_id}: {r.reason}" for r in summary.hard_blocks
            )
            cls.sugestao_resposta = (
                f"Prezado(a) {vars_.get('nome_aluno', 'estudante')},\n\n"
                f"Não foi possível processar sua solicitação de estágio "
                f"devido aos seguintes impedimentos:\n\n{block_lines}\n\n"
                f"Favor regularizar a situação e reenviar a documentação.\n\n"
                f"Atenciosamente,\nCoordenação do Curso de Design Gráfico"
            )
            sei_ops.append({
                "stable_id": sid, "op": "blocked", "reason": "hard_block",
                "blocks": [{"id": r.check_id, "reason": r.reason} for r in summary.hard_blocks],
            })
            logger.info("agir_estagios[%s]: HARD BLOCK — %d bloqueio(s)", sid[:8], len(summary.hard_blocks))
            continue

        if summary.soft_blocks:
            # Draft email asking for justification
            soft_lines = "\n".join(
                f"- {r.check_id}: {r.reason}" for r in summary.soft_blocks
            )
            cls.sugestao_resposta = (
                f"Prezado(a) {vars_.get('nome_aluno', 'estudante')},\n\n"
                f"Sua solicitação de estágio requer esclarecimentos adicionais:\n\n"
                f"{soft_lines}\n\n"
                f"Favor enviar justificativa formal por e-mail para que possamos "
                f"dar prosseguimento ao processo.\n\n"
                f"Atenciosamente,\nCoordenação do Curso de Design Gráfico"
            )
            sei_ops.append({
                "stable_id": sid, "op": "blocked", "reason": "soft_block",
                "blocks": [{"id": r.check_id, "reason": r.reason} for r in summary.soft_blocks],
            })
            logger.info("agir_estagios[%s]: SOFT BLOCK — %d pendência(s)", sid[:8], len(summary.soft_blocks))
            continue

        # All checks passed — proceed with SEI operations
        logger.info("agir_estagios[%s]: checks OK — executando SEI ops (intent: %s)", sid[:8], intent.intent_name)

        try:
            sei_result = asyncio.run(_run_sei_chain(intent, vars_, email, sid))
            sei_ops.append(sei_result)

            # Update classification with acuse
            processo_id = sei_result.get("processo_id", "")
            if processo_id:
                acuse = fill_template(
                    intent.template or "",
                    {**vars_, "numero_processo_sei": processo_id},
                )
                cls.sugestao_resposta = acuse

        except Exception as e:
            logger.error("agir_estagios[%s]: SEI chain failed: %s", sid[:8], e)
            errors.append({"node": "agir_estagios", "stable_id": sid, "error": str(e)})
            sei_ops.append({"stable_id": sid, "op": "error", "error": str(e)})

    logger.info("agir_estagios: %d operação(ões) SEI processada(s)", len(sei_ops))
    result: dict[str, Any] = {"sei_operations": sei_ops}
    if errors:
        result["errors"] = errors
    return result


async def _run_sei_chain(intent, vars_: dict, email, stable_id: str) -> dict:
    """Execute the SEI write chain for a single Estágios email.

    Returns a dict summary suitable for the ``sei_operations`` state field.
    """
    from unittest.mock import AsyncMock

    from ufpr_automation.procedures.doc_catalog import get_doc_classification
    from ufpr_automation.procedures.playbook import fill_template
    from ufpr_automation.sei.writer import SEIWriter

    # Create a mock page — SEI ops are dry-run by default (SEI_WRITE_MODE env).
    # In live mode, the page should come from BrowserPagePool.
    page = AsyncMock()
    writer = SEIWriter(page)

    result: dict = {"stable_id": stable_id, "ops": []}

    # Step 1: create_process (if sei_action == "create_process")
    if intent.sei_action == "create_process":
        create = await writer.create_process(
            tipo_processo=intent.sei_process_type,
            especificacao=vars_.get("curso", "Design Gráfico"),
            interessado=f"{vars_.get('nome_aluno', 'N/A')} - GRR{vars_.get('grr', 'N/A')}",
        )
        result["processo_id"] = create.processo_id
        result["ops"].append({"op": "create_process", "success": create.success, "dry_run": create.dry_run})
        logger.info("  create_process: %s (dry_run=%s)", create.processo_id, create.dry_run)
    else:
        result["processo_id"] = vars_.get("numero_processo_sei", "")

    processo_id = result["processo_id"]

    # Step 2: attach_document(s) — for each required_attachment
    for att_label in intent.required_attachments:
        classification = get_doc_classification(att_label)
        if classification is None:
            logger.warning("  attach: unknown doc label '%s' — skipping", att_label)
            result["ops"].append({"op": "attach", "label": att_label, "skipped": True})
            continue

        # In dry-run, we just log intent. In live, we'd look for the actual
        # attachment file on the email's downloaded attachments.
        from pathlib import Path

        att_file = None
        if email.attachments:
            for att in email.attachments:
                if att.filename and att.filename.lower().endswith(".pdf"):
                    att_file = Path(att.local_path) if hasattr(att, "local_path") and att.local_path else None
                    break

        if att_file and att_file.exists():
            attach = await writer.attach_document(processo_id, att_file, classification)
            result["ops"].append({"op": "attach", "label": att_label, "success": attach.success, "dry_run": attach.dry_run})
        else:
            # No file available — log as planned but not executed
            result["ops"].append({"op": "attach", "label": att_label, "skipped": True, "reason": "file_not_available"})

    # Step 3: save_despacho_draft
    if intent.despacho_template:
        draft = await writer.save_despacho_draft(
            processo_id,
            tipo=intent.intent_name,
            variables=vars_,
            body_override=fill_template(intent.despacho_template, vars_),
        )
        result["ops"].append({"op": "despacho", "success": draft.success, "dry_run": draft.dry_run})

    result["op"] = "sei_chain"
    result["success"] = all(
        op.get("success", True) for op in result["ops"] if not op.get("skipped")
    )
    return result


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
