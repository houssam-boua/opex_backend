import logging

from celery import shared_task

from core.models import Tenant
from .services import RoutineService


logger = logging.getLogger(__name__)


@shared_task(name="modules.routines.tasks.check_missed_routine_executions_task")
def check_missed_routine_executions_task(tenant_id=None):
    """Detect missed mandatory routine executions."""
    logger.info("Running missed routine execution task.")
    tenant = None
    if tenant_id:
        tenant = Tenant.objects.filter(id=tenant_id, status__in=["active", "trial"]).first()
        if not tenant:
            return {"skipped": True, "reason": "tenant not found or inactive", "tenant_id": str(tenant_id)}
    results = RoutineService.mark_missed_executions(tenant=tenant)
    summary = {"missed_marked": len(results), "results": results}
    logger.info("Missed routine execution task completed: %s", summary)
    return summary
