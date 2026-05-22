"""
Gemba Walk Module - Business Logic Services.
"""
from datetime import timedelta

from django.core.mail import send_mail
from django.db.models import Count
from django.utils import timezone

from accounts.models import CustomUser
from core.models import Tenant
from shared.models import Action, Notification
from .models import Anomaly, Tour


class GembaService:
    @staticmethod
    def send_weekly_summary():
        today = timezone.localdate()
        start_date = today - timedelta(days=7)
        tenants = Tenant.objects.filter(status__in=["active", "trial"])
        summary = {
            "tenants_checked": 0,
            "notifications_created": 0,
            "emails_sent": 0,
            "duplicates_skipped": 0,
            "recipients_missing": 0,
        }
        for tenant in tenants:
            summary["tenants_checked"] += 1
            metrics = GembaService._weekly_metrics(tenant, start_date, today)
            recipients = CustomUser.objects.filter(
                tenant=tenant,
                role__in=["tenant_admin", "plant_manager", "quality_mgr"],
                is_active=True,
            )
            if not recipients.exists():
                summary["recipients_missing"] += 1
                continue

            subject = f"Weekly Gemba summary - {tenant.name}"
            message = GembaService._build_summary_message(tenant, metrics)
            for user in recipients:
                if Notification.objects.filter(
                    tenant=tenant,
                    recipient=user,
                    notification_type="gemba_weekly_summary",
                    created_at__date=today,
                ).exists():
                    summary["duplicates_skipped"] += 1
                    continue
                Notification.objects.create(
                    tenant=tenant,
                    recipient=user,
                    title=subject,
                    message=message,
                    type="info",
                    notification_type="gemba_weekly_summary",
                    link="/gemba/dashboard",
                )
                summary["notifications_created"] += 1
                if user.email:
                    sent = send_mail(
                        subject,
                        message,
                        None,
                        [user.email],
                        fail_silently=True,
                    )
                    summary["emails_sent"] += sent
        return summary

    @staticmethod
    def _weekly_metrics(tenant, start_date, today):
        tours = Tour.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
        )
        anomalies = Anomaly.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
        )
        actions = Action.objects.filter(
            tenant=tenant,
            module_source="gemba",
            is_active=True,
            is_deleted=False,
        )
        open_statuses = [
            Anomaly.AnomalyStatus.TODO,
            Anomaly.AnomalyStatus.IN_PROGRESS,
            Anomaly.AnomalyStatus.PENDING_VALIDATION,
        ]
        key_open_issues = list(
            anomalies.filter(status__in=open_statuses)
            .order_by("-severity", "due_date")
            .values("title", "severity", "due_date")[:5]
        )
        return {
            "period_start": start_date,
            "period_end": today,
            "tours_completed": tours.filter(
                status=Tour.Status.COMPLETED,
                date__gte=start_date,
                date__lte=today,
            ).count(),
            "anomalies_found": anomalies.filter(created_at__date__gte=start_date).count(),
            "open_anomalies": anomalies.filter(status__in=open_statuses).count(),
            "resolved_anomalies": anomalies.filter(
                status=Anomaly.AnomalyStatus.CLOSED,
                resolved_at__date__gte=start_date,
            ).count(),
            "overdue_actions": actions.filter(
                status__in=["open", "in_progress"],
                due_date__lt=today,
            ).count(),
            "anomalies_by_severity": list(
                anomalies.filter(created_at__date__gte=start_date)
                .values("severity")
                .annotate(count=Count("id"))
                .order_by("severity")
            ),
            "key_open_issues": key_open_issues,
        }

    @staticmethod
    def _build_summary_message(tenant, metrics):
        issue_lines = [
            f"- {issue['title']} ({issue['severity']}, due {issue['due_date'] or 'n/a'})"
            for issue in metrics["key_open_issues"]
        ]
        if not issue_lines:
            issue_lines = ["- No key open issues."]
        severity_lines = [
            f"- {item['severity']}: {item['count']}"
            for item in metrics["anomalies_by_severity"]
        ]
        if not severity_lines:
            severity_lines = ["- None"]
        return "\n".join([
            f"Weekly Gemba summary for {tenant.name}",
            f"Period: {metrics['period_start']} to {metrics['period_end']}",
            "",
            f"Tours/walks completed: {metrics['tours_completed']}",
            f"Anomalies found: {metrics['anomalies_found']}",
            f"Open anomalies: {metrics['open_anomalies']}",
            f"Resolved anomalies: {metrics['resolved_anomalies']}",
            f"Overdue Gemba actions: {metrics['overdue_actions']}",
            "",
            "Anomalies by severity:",
            *severity_lines,
            "",
            "Key open issues:",
            *issue_lines,
            "",
            "Dashboard: /gemba/dashboard",
        ])
