from datetime import timedelta

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from shared.models import Notification
from .models import CapaTicket


class CapaService:
    @staticmethod
    @transaction.atomic
    def send_due_reminders():
        today = timezone.localdate()
        reminder_until = today + timedelta(days=2)
        open_statuses = [
            CapaTicket.CapaStatus.IDENTIFIED,
            CapaTicket.CapaStatus.PLANNED,
            CapaTicket.CapaStatus.IN_PROGRESS,
            CapaTicket.CapaStatus.LATE,
        ]
        tickets = CapaTicket.objects.filter(
            due_date__isnull=False,
            due_date__lte=reminder_until,
            status__in=open_statuses,
            is_active=True,
            is_deleted=False,
            tenant__status__in=["active", "trial"],
        ).select_related("tenant", "pilot__user_account", "created_by")

        summary = {
            "checked": 0,
            "notifications_created": 0,
            "emails_sent": 0,
            "skipped_without_recipient": 0,
            "duplicates_skipped": 0,
        }
        for ticket in tickets:
            summary["checked"] += 1
            recipient_user = getattr(ticket.pilot, "user_account", None)
            if not recipient_user:
                summary["skipped_without_recipient"] += 1
                continue
            if Notification.objects.filter(
                tenant=ticket.tenant,
                recipient=recipient_user,
                notification_type="capa_due_reminder",
                related_object_id=ticket.id,
                created_at__date=today,
            ).exists():
                summary["duplicates_skipped"] += 1
                continue

            title = f"CAPA due reminder: {ticket.title}"
            message = CapaService._build_due_reminder_message(ticket)
            Notification.objects.create(
                tenant=ticket.tenant,
                created_by=ticket.created_by,
                recipient=recipient_user,
                title=title,
                message=message,
                type="warning",
                notification_type="capa_due_reminder",
                related_object_id=ticket.id,
                link=f"/capa/{ticket.id}",
            )
            summary["notifications_created"] += 1
            if recipient_user.email:
                sent = send_mail(
                    title,
                    message,
                    None,
                    [recipient_user.email],
                    fail_silently=True,
                )
                summary["emails_sent"] += sent
        return summary

    @staticmethod
    def _build_due_reminder_message(ticket):
        urgency = ticket.urgency or "medium"
        return "\n".join([
            f"CAPA: {ticket.title}",
            f"Reference: {ticket.id}",
            f"Due date: {ticket.due_date}",
            f"Status: {ticket.status}",
            f"Priority: {urgency}",
            f"Link: /capa/{ticket.id}",
        ])
