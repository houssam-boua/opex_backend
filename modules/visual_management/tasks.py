# modules/visual_management/tasks.py
import logging
from celery import shared_task
from .services import AndonService

logger = logging.getLogger(__name__)

@shared_task
def check_andon_sla_breach_task(call_id):
    """
    Celery task delayed by 10 minutes to verify SLA.
    """
    logger.info(f"Running SLA check for AndonCall: {call_id}")
    try:
        from .models import AndonCall
        call = AndonCall.objects.select_related("tenant").get(id=call_id)
        tenant = call.tenant
        if not tenant.is_active:
            return f"Skipped — tenant {tenant.slug} is not active (status: {tenant.status})"
    except AndonCall.DoesNotExist:
        return

    try:
        AndonService.check_andon_sla_breach(call_id)
    except Exception as e:
        logger.error(f"Error in check_andon_sla_breach_task: {e}")
