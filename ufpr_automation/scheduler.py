"""Scheduler for running the UFPR automation pipeline at fixed times.

Runs the LangGraph pipeline 3 times per day (configurable via .env).
Uses APScheduler for lightweight, dependency-free scheduling.

Usage:
    python -m ufpr_automation --schedule           # start scheduler (3x/day)
    python -m ufpr_automation --schedule --once     # run once now and exit

Environment variables:
    SCHEDULE_HOURS=8,13,17          # comma-separated hours (24h format)
    SCHEDULE_TZ=America/Sao_Paulo   # timezone for scheduling
"""

from __future__ import annotations

import os
import time
from datetime import datetime

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ufpr_automation.config import settings
from ufpr_automation.notify.telegram import notify_run_summary
from ufpr_automation.utils.logging import logger

SCHEDULE_HOURS = os.getenv("SCHEDULE_HOURS", "8,13,17")
SCHEDULE_TZ = os.getenv("SCHEDULE_TZ", "America/Sao_Paulo")


def _check_drive_freshness() -> None:
    """Pre-flight check: avisa se o RAG/Neo4j local esta defasado em relacao ao G:.

    NAO aborta o pipeline em caso de drift — apenas loga WARNING. A logica e:
    melhor processar emails com RAG levemente defasado do que perder triggers
    enquanto o operador resolve o sync. Sem MANIFEST.json em algum lado o
    check vira no-op silencioso (DEBUG only).
    """
    try:
        from scripts import check_drive_freshness  # noqa: WPS433 (lazy import)
    except ImportError:
        try:
            import importlib.util
            from pathlib import Path
            spec_path = Path(__file__).resolve().parent.parent / "scripts" / "check_drive_freshness.py"
            if not spec_path.exists():
                return
            spec = importlib.util.spec_from_file_location("_check_drive_freshness", spec_path)
            check_drive_freshness = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(check_drive_freshness)
        except Exception as e:
            logger.debug("Scheduler: pre-flight check indisponivel: %s", e)
            return

    try:
        result = check_drive_freshness.evaluate()
    except Exception as e:
        logger.debug("Scheduler: pre-flight check falhou: %s", e)
        return

    status = result.get("status")
    if status == "SYNCED":
        logger.info("Scheduler: pre-flight RAG/Neo4j SYNCED com G:")
    elif status == "STALE":
        logger.warning(
            "Scheduler: G: tem versao mais recente que este PC — RAG/Neo4j "
            "pode estar defasado. Rode scripts/sync_from_drive.ps1 quando puder. "
            "Pipeline vai prosseguir com o estado local."
        )
    elif status == "AHEAD":
        logger.info(
            "Scheduler: pre-flight — local mais recente que G: "
            "(rode scripts/sync_to_drive.ps1 pra publicar)."
        )
    elif status == "CONFLICT":
        logger.warning(
            "Scheduler: pre-flight — manifests divergem mas timestamps batem (CONFLICT). "
            "Investigar antes do proximo sync."
        )
    elif status in ("NO_REMOTE", "NO_LOCAL"):
        logger.debug("Scheduler: pre-flight — %s (sem manifest pra comparar)", status)


def run_scheduled_pipeline() -> None:
    """Execute the LangGraph pipeline once.

    Called by the scheduler at each configured time, or directly via --once.
    """
    from ufpr_automation.graph.builder import build_graph

    _check_drive_freshness()

    channel = settings.EMAIL_CHANNEL
    start_time = datetime.now()
    started_at = time.monotonic()
    logger.info(
        "Scheduler: iniciando pipeline (canal=%s) em %s",
        channel,
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    try:
        graph = build_graph(channel=channel)
        result = graph.invoke({"channel": channel})

        emails = result.get("emails", [])
        classifications = result.get("classifications", {})
        drafts = result.get("drafts_saved", [])
        procedures = result.get("procedures_logged", 0)

        duration = time.monotonic() - started_at
        logger.info(
            "Scheduler: pipeline concluido — %d email(s), %d classificado(s), "
            "%d rascunho(s), %d procedimento(s) registrado(s)",
            len(emails),
            len(classifications),
            len(drafts),
            procedures,
        )
        notify_run_summary(
            result,
            duration_s=duration,
            start_time=start_time,
            channel=channel,
        )
    except Exception as e:
        logger.error("Scheduler: pipeline falhou: %s", e, exc_info=True)
        notify_run_summary(
            None,
            duration_s=time.monotonic() - started_at,
            start_time=start_time,
            channel=channel,
            error=str(e),
        )


def _job_listener(event):
    """Log job execution results."""
    if event.exception:
        logger.error("Scheduler: job falhou com excecao: %s", event.exception)
    else:
        logger.info("Scheduler: job executado com sucesso")


def start_scheduler() -> None:
    """Start the blocking scheduler with configured cron jobs.

    This function blocks until interrupted (Ctrl+C).
    """
    hours = [h.strip() for h in SCHEDULE_HOURS.split(",") if h.strip()]
    if not hours:
        logger.error("SCHEDULE_HOURS vazio — nenhum horario configurado")
        return

    scheduler = BlockingScheduler(timezone=SCHEDULE_TZ)
    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    for hour in hours:
        try:
            h = int(hour)
            trigger = CronTrigger(hour=h, minute=0, timezone=SCHEDULE_TZ)
            scheduler.add_job(
                run_scheduled_pipeline,
                trigger=trigger,
                id=f"pipeline_{h:02d}h",
                name=f"Pipeline {h:02d}:00",
                misfire_grace_time=3600,  # allow 1h grace for missed fires
            )
            logger.info("Scheduler: job agendado para %02d:00 (%s)", h, SCHEDULE_TZ)
        except (ValueError, TypeError) as e:
            logger.warning("Scheduler: horario invalido '%s': %s", hour, e)

    print(f"\nScheduler iniciado — {len(hours)} execucao(oes)/dia")
    print(f"Horarios: {', '.join(f'{int(h):02d}:00' for h in hours)}")
    print(f"Timezone: {SCHEDULE_TZ}")
    print(f"Canal: {settings.EMAIL_CHANNEL}")
    print("Pressione Ctrl+C para parar.\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler: encerrado pelo usuario")
        print("\nScheduler encerrado.")
