# modules/skills/services.py
from datetime import timedelta
from django.utils import timezone
from .models import EmployeeSkill, Certification
from shared.models import Notification

class SkillsService:
    @staticmethod
    def calculate_machine_coverage(tenant, skill_id, required_level=2):
        """
        Versatility/Polyvalence Math: Calculate Machine Coverage.
        Returns the count of employees who possess the required skill at or above the required_level.
        """
        count = EmployeeSkill.objects.filter(
            tenant=tenant,
            skill_id=skill_id,
            level__gte=required_level,
            is_active=True
        ).count()
        return count

    @staticmethod
    def check_expiring_certifications():
        """
        Finds certifications expiring in < 30 days and alerts the manager via shared.models.Notification.
        Intended to be run daily by Celery.
        """
        today = timezone.localdate()
        thirty_days_from_now = today + timedelta(days=30)

        # Get certifications expiring between today and 30 days from now
        expiring_certs = Certification.objects.filter(
            expiry_date__gt=today,
            expiry_date__lte=thirty_days_from_now,
            is_active=True
        ).select_related('employee__manager__user_account', 'tenant')

        for cert in expiring_certs:
            manager = cert.employee.manager
            if manager and manager.user_account:
                if Notification.objects.filter(
                    tenant=cert.tenant,
                    recipient=manager.user_account,
                    notification_type="certification_expiry",
                    related_object_id=cert.id,
                    created_at__date=today,
                ).exists():
                    continue
                # Use shared.models.Notification
                Notification.objects.create(
                    recipient=manager.user_account,
                    title=f"Certification Expiry Alert: {cert.employee.full_name}",
                    message=f"The certification '{cert.name}' for {cert.employee.full_name} will expire on {cert.expiry_date}.",
                    notification_type="certification_expiry",
                    related_object_id=str(cert.id),
                    tenant=cert.tenant
                )
