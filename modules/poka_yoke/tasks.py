import logging

from celery import shared_task

from core.models import Tenant
from .services import PokaYokeService


logger = logging.getLogger(__name__)


@shared_task(name="modules.poka_yoke.tasks.check_overdue_poka_yoke_verifications_task")
def check_overdue_poka_yoke_verifications_task(tenant_id=None):
    """Detect overdue Poka-Yoke verifications."""
    logger.info("Running overdue Poka-Yoke verification task.")
    tenant = None
    if tenant_id:
        tenant = Tenant.objects.filter(id=tenant_id, status__in=["active", "trial"]).first()
        if not tenant:
            return {"skipped": True, "reason": "tenant not found or inactive", "tenant_id": str(tenant_id)}
    results = PokaYokeService.check_overdue_verifications(tenant=tenant)
    summary = {"overdue_devices": len(results), "results": results}
    logger.info("Overdue Poka-Yoke verification task completed: %s", summary)
    return summary
