# modules/skills/tasks.py
import logging
from celery import shared_task
from .services import SkillsService

logger = logging.getLogger(__name__)

@shared_task
def check_expiring_certifications_task():
    """
    Celery Beat task to check for certifications expiring in < 30 days.
    """
    logger.info("Running check_expiring_certifications_task...")
    from core.models import Tenant
    tenants = Tenant.objects.filter(status__in=["active", "trial"])
    if not tenants.exists():
        return "Skipped — no active tenants"

    try:
        SkillsService.check_expiring_certifications()
        logger.info("Successfully checked expiring certifications.")
    except Exception as e:
        logger.error(f"Error checking expiring certifications: {e}")
