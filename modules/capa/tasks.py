# modules/capa/tasks.py
import logging

from celery import shared_task

from .services import CapaService


logger = logging.getLogger(__name__)


@shared_task(name="modules.capa.tasks.send_due_reminders")
def send_due_reminders():
    """Daily CAPA due reminder task."""
    logger.info("Running CAPA due reminders task.")
    summary = CapaService.send_due_reminders()
    logger.info("CAPA due reminders completed: %s", summary)
    return summary
