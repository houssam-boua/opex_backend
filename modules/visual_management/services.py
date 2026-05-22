# modules/visual_management/services.py
from django.utils import timezone
from django.db.models import Avg
from .models import AndonCall, AndonAlert, ProductionLine
from shared.models import Notification

class AndonService:
    @staticmethod
    def calculate_response_time(tenant):
        """Calculates average response time per line."""
        lines = ProductionLine.objects.filter(tenant=tenant)
        results = []
        for line in lines:
            avg_time = AndonCall.objects.filter(
                line=line,
                tenant=tenant,
                status__in=[AndonCall.Status.ACKNOWLEDGED, AndonCall.Status.RESOLVED],
                responses__response_time_seconds__isnull=False
            ).aggregate(avg=Avg('responses__response_time_seconds'))['avg']
            
            results.append({
                "line_id": str(line.id),
                "line_name": line.name,
                "avg_response_time_seconds": avg_time or 0
            })
        return results

    @staticmethod
    def check_andon_sla_breach(call_id):
        """
        Executed by Celery 10 minutes after call creation.
        If the call is still OPEN, triggers SLA breach logic.
        """
        try:
            call = AndonCall.objects.get(id=call_id)
        except AndonCall.DoesNotExist:
            return

        if call.status == AndonCall.Status.OPEN:
            message = f"SLA Breach: Andon call on line {call.line.name} unacknowledged after 10 minutes."
            alert, _created = AndonAlert.objects.get_or_create(
                call=call,
                is_resolved=False,
                tenant=call.tenant,
                defaults={
                    "message": message,
                    "created_by": call.created_by,
                },
            )

            # Route to shared.models.Notification (to supervisor/manager)
            # Find a supervisor (here we could just notify the line manager or tenant admin,
            # but for robustness we'll notify all users with manager role in this context or hardcode to a specific supervisor logic).
            # Assuming operator has a manager:
            operator_manager = call.operator.manager if call.operator else None
            
            if operator_manager and operator_manager.user_account:
                if Notification.objects.filter(
                    tenant=call.tenant,
                    recipient=operator_manager.user_account,
                    notification_type="andon_sla_breach",
                    related_object_id=call.id,
                    created_at__date=timezone.localdate(),
                ).exists():
                    return
                Notification.objects.create(
                    recipient=operator_manager.user_account,
                    title=f"ANDON SLA BREACH: {call.line.name}",
                    message=alert.message,
                    notification_type="andon_sla_breach",
                    related_object_id=str(call.id),
                    tenant=call.tenant
                )
