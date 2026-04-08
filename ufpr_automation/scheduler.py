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
from datetime import datetime

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ufpr_automation.config import settings
from ufpr_automation.utils.logging import logger

SCHEDULE_HOURS = os.getenv("SCHEDULE_HOURS", "8,13,17")
SCHEDULE_TZ = os.getenv("SCHEDULE_TZ", "America/Sao_Paulo")


def run_scheduled_pipeline() -> None:
    """Execute the LangGraph pipeline once.

    Called by the scheduler at each configured time, or directly via --once.
    """
    from ufpr_automation.graph.builder import build_graph

    channel = settings.EMAIL_CHANNEL
    logger.info(
        "Scheduler: iniciando pipeline (canal=%s) em %s",
        channel,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    try:
        graph = build_graph(channel=channel)
        result = graph.invoke({"channel": channel})

        emails = result.get("emails", [])
        classifications = result.get("classifications", {})
        drafts = result.get("drafts_saved", [])
        procedures = result.get("procedures_logged", 0)

        logger.info(
            "Scheduler: pipeline concluido — %d email(s), %d classificado(s), "
            "%d rascunho(s), %d procedimento(s) registrado(s)",
            len(emails),
            len(classifications),
            len(drafts),
            procedures,
        )
    except Exception as e:
        logger.error("Scheduler: pipeline falhou: %s", e, exc_info=True)


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
