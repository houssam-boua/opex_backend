# modules/gemba/tasks.py
import logging

from celery import shared_task

from .services import GembaService


logger = logging.getLogger(__name__)


@shared_task(name="modules.gemba.tasks.send_weekly_summary")
def send_weekly_summary():
    """Weekly tenant-safe Gemba summary task."""
    logger.info("Running Gemba weekly summary task.")
    summary = GembaService.send_weekly_summary()
    logger.info("Gemba weekly summary completed: %s", summary)
    return summary
