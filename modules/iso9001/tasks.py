# modules/iso9001/tasks.py
import logging
from celery import shared_task
from .services import ISO9001Service

logger = logging.getLogger(__name__)

@shared_task
def check_iso_document_expiry_task():
    """
    Celery Beat task to check for ISO documents expiring exactly in 30 days.
    """
    logger.info("Running check_iso_document_expiry_task...")
    from core.models import Tenant
    tenants = Tenant.objects.filter(status__in=["active", "trial"])
    if not tenants.exists():
        return "Skipped — no active tenants"

    try:
        ISO9001Service.check_iso_document_expiry()
        logger.info("Successfully checked ISO document expirations.")
    except Exception as e:
        logger.error(f"Error checking ISO document expirations: {e}")
