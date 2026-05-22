from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Employee
from core.models import Tenant
from shared.models import Action, Notification
from .models import PokaYokeCheck, PokaYokeDefect, PokaYokeDevice, PokaYokeImprovement


class PokaYokeService:
    DEVICE_TRANSITIONS = {
        PokaYokeDevice.Status.DRAFT: {
            PokaYokeDevice.Status.ACTIVE,
            PokaYokeDevice.Status.INACTIVE,
            PokaYokeDevice.Status.UNDER_REVIEW,
        },
        PokaYokeDevice.Status.ACTIVE: {
            PokaYokeDevice.Status.INACTIVE,
            PokaYokeDevice.Status.UNDER_REVIEW,
            PokaYokeDevice.Status.RETIRED,
        },
        PokaYokeDevice.Status.INACTIVE: {
            PokaYokeDevice.Status.ACTIVE,
            PokaYokeDevice.Status.RETIRED,
        },
        PokaYokeDevice.Status.UNDER_REVIEW: {
            PokaYokeDevice.Status.ACTIVE,
            PokaYokeDevice.Status.INACTIVE,
            PokaYokeDevice.Status.RETIRED,
        },
        PokaYokeDevice.Status.RETIRED: set(),
    }
    DEFECT_TRANSITIONS = {
        PokaYokeDefect.Status.OPEN: {
            PokaYokeDefect.Status.INVESTIGATING,
            PokaYokeDefect.Status.ACTION_REQUIRED,
            PokaYokeDefect.Status.RESOLVED,
            PokaYokeDefect.Status.CLOSED,
        },
        PokaYokeDefect.Status.INVESTIGATING: {
            PokaYokeDefect.Status.ACTION_REQUIRED,
            PokaYokeDefect.Status.RESOLVED,
            PokaYokeDefect.Status.CLOSED,
        },
        PokaYokeDefect.Status.ACTION_REQUIRED: {
            PokaYokeDefect.Status.RESOLVED,
            PokaYokeDefect.Status.CLOSED,
        },
        PokaYokeDefect.Status.RESOLVED: {
            PokaYokeDefect.Status.VERIFIED,
            PokaYokeDefect.Status.CLOSED,
        },
        PokaYokeDefect.Status.VERIFIED: {PokaYokeDefect.Status.CLOSED},
        PokaYokeDefect.Status.CLOSED: set(),
    }
    IMPROVEMENT_TRANSITIONS = {
        PokaYokeImprovement.Status.PROPOSED: {
            PokaYokeImprovement.Status.APPROVED,
            PokaYokeImprovement.Status.REJECTED,
        },
        PokaYokeImprovement.Status.APPROVED: {
            PokaYokeImprovement.Status.IN_PROGRESS,
            PokaYokeImprovement.Status.REJECTED,
        },
        PokaYokeImprovement.Status.IN_PROGRESS: {
            PokaYokeImprovement.Status.IMPLEMENTED,
            PokaYokeImprovement.Status.REJECTED,
        },
        PokaYokeImprovement.Status.IMPLEMENTED: {PokaYokeImprovement.Status.VERIFIED},
        PokaYokeImprovement.Status.VERIFIED: set(),
        PokaYokeImprovement.Status.REJECTED: set(),
    }

    @staticmethod
    def validate_transition(current_status, next_status, transitions, label):
        if current_status == next_status:
            return
        if next_status not in transitions.get(current_status, set()):
            raise ValidationError(f"Invalid {label} status transition: {current_status} -> {next_status}.")

    @staticmethod
    @transaction.atomic
    def evaluate_check(check):
        check = PokaYokeCheck.objects.select_for_update().select_related("device").get(pk=check.pk)
        if check.result == PokaYokeCheck.Result.FAILED:
            check.requires_action = True
            action = PokaYokeService._sync_check_action(check)
            check.linked_action = action
            check.save(update_fields=["requires_action", "linked_action", "updated_at"])
            PokaYokeService._notify_employee_once_today(
                check.device.owner,
                "Poka-Yoke check failed",
                f"{check.device.name} failed verification.",
                check.tenant,
                check.created_by,
                check.id,
                "poka_yoke_check_failed",
                "warning",
            )
        elif check.result == PokaYokeCheck.Result.PASSED:
            check.requires_action = False
            check.save(update_fields=["requires_action", "updated_at"])
            device = check.device
            device.last_verified_at = check.checked_at
            if device.verification_interval_days:
                device.next_verification_due = check.checked_at.date() + timedelta(
                    days=device.verification_interval_days
                )
            device.save(update_fields=[
                "last_verified_at",
                "next_verification_due",
                "updated_at",
            ])
            if check.linked_action and check.linked_action.status in ["open", "in_progress"]:
                PokaYokeService._close_action(check.linked_action)
        return check

    @staticmethod
    def _sync_check_action(check):
        title = f"Poka-Yoke check failed: {check.device.name}"
        description = "\n".join([
            f"Device: {check.device.name}",
            f"Checked at: {check.checked_at}",
            f"Observation: {check.observation}",
            f"Measured value: {check.measured_value}",
            f"Expected value: {check.expected_value}",
        ])
        priority = PokaYokeService._criticality_to_priority(check.device.criticality)
        return PokaYokeService._upsert_action(
            tenant=check.tenant,
            created_by=check.created_by,
            reference_id=check.id,
            action_type="failed_check",
            title=title,
            description=description,
            priority=priority,
            assigned_to=check.device.owner,
            existing=check.linked_action,
        )

    @staticmethod
    @transaction.atomic
    def register_defect(defect):
        defect = PokaYokeDefect.objects.select_for_update().get(pk=defect.pk)
        if defect.severity in [PokaYokeDefect.Severity.MAJOR, PokaYokeDefect.Severity.CRITICAL]:
            action = PokaYokeService._sync_defect_action(defect)
            defect.linked_action = action
            if defect.status == PokaYokeDefect.Status.OPEN:
                defect.status = PokaYokeDefect.Status.ACTION_REQUIRED
            defect.save(update_fields=["linked_action", "status", "updated_at"])
            if defect.device:
                defect.device.status = PokaYokeDevice.Status.UNDER_REVIEW
                defect.device.save(update_fields=["status", "updated_at"])
            PokaYokeService._notify_employee(
                defect.device.owner if defect.device else defect.detected_by,
                "Critical Poka-Yoke defect" if defect.severity == PokaYokeDefect.Severity.CRITICAL else "Major Poka-Yoke defect",
                defect.title,
                defect.tenant,
                defect.created_by,
                defect.id,
                "poka_yoke_defect",
                "error" if defect.severity == PokaYokeDefect.Severity.CRITICAL else "warning",
            )
        return defect

    @staticmethod
    def _sync_defect_action(defect):
        title = f"Poka-Yoke defect: {defect.title}"
        description = "\n".join([
            f"Severity: {defect.severity}",
            f"Source: {defect.defect_source}",
            f"Detected at: {defect.detected_at}",
            f"Description: {defect.description}",
            f"Notes: {defect.notes}",
        ])
        return PokaYokeService._upsert_action(
            tenant=defect.tenant,
            created_by=defect.created_by,
            reference_id=defect.id,
            action_type="defect",
            title=title,
            description=description,
            priority=PokaYokeService._severity_to_priority(defect.severity),
            assigned_to=defect.device.owner if defect.device else defect.detected_by,
            existing=defect.linked_action,
        )

    @staticmethod
    @transaction.atomic
    def verify_defect(defect, verified_by):
        defect = PokaYokeDefect.objects.select_for_update().get(pk=defect.pk)
        if defect.status not in [
            PokaYokeDefect.Status.RESOLVED,
            PokaYokeDefect.Status.ACTION_REQUIRED,
            PokaYokeDefect.Status.INVESTIGATING,
        ]:
            raise ValidationError("Only resolved, action-required, or investigating defects can be verified.")
        if verified_by and verified_by.tenant_id != defect.tenant_id:
            raise ValidationError("Verifier does not belong to this tenant.")
        defect.status = PokaYokeDefect.Status.VERIFIED
        defect.verified_by = verified_by
        defect.verified_at = timezone.now()
        defect.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
        if defect.linked_action:
            PokaYokeService._close_action(defect.linked_action)
        return defect

    @staticmethod
    @transaction.atomic
    def sync_improvement_action(improvement):
        improvement = PokaYokeImprovement.objects.select_for_update().get(pk=improvement.pk)
        if improvement.status in [
            PokaYokeImprovement.Status.APPROVED,
            PokaYokeImprovement.Status.IN_PROGRESS,
            PokaYokeImprovement.Status.IMPLEMENTED,
        ]:
            title = f"Poka-Yoke improvement: {improvement.title}"
            description = "\n".join([
                f"Status: {improvement.status}",
                f"Priority: {improvement.priority}",
                f"Due date: {improvement.due_date}",
                f"Description: {improvement.description}",
            ])
            action = PokaYokeService._upsert_action(
                tenant=improvement.tenant,
                created_by=improvement.created_by,
                reference_id=improvement.id,
                action_type="improvement",
                title=title,
                description=description,
                priority=PokaYokeService._priority_to_action_priority(improvement.priority),
                assigned_to=improvement.owner,
                existing=improvement.linked_action,
            )
            improvement.linked_action = action
            improvement.save(update_fields=["linked_action", "updated_at"])
        if improvement.status in [
            PokaYokeImprovement.Status.APPROVED,
            PokaYokeImprovement.Status.REJECTED,
        ]:
            PokaYokeService._notify_employee(
                improvement.proposed_by,
                f"Poka-Yoke improvement {improvement.status}",
                improvement.title,
                improvement.tenant,
                improvement.created_by,
                improvement.id,
                "poka_yoke_improvement_status",
                "info" if improvement.status == PokaYokeImprovement.Status.APPROVED else "warning",
            )
        return improvement

    @staticmethod
    def _upsert_action(tenant, created_by, reference_id, action_type, title, description, priority, assigned_to=None, existing=None):
        action = existing or Action.objects.filter(
            tenant=tenant,
            module_source="poka_yoke",
            reference_id=reference_id,
            action_type=action_type,
            is_active=True,
            is_deleted=False,
        ).first()
        if action:
            action.title = title
            action.description = description
            action.priority = priority
            action.assigned_to = assigned_to
            action.module_source = "poka_yoke"
            action.reference_id = reference_id
            action.action_type = action_type
            action.save(update_fields=[
                "title",
                "description",
                "priority",
                "assigned_to",
                "module_source",
                "reference_id",
                "action_type",
                "updated_at",
            ])
            return action
        return Action.objects.create(
            tenant=tenant,
            created_by=created_by,
            title=title,
            description=description,
            priority=priority,
            status="open",
            assigned_to=assigned_to,
            module_source="poka_yoke",
            reference_id=reference_id,
            action_type=action_type,
        )

    @staticmethod
    def _close_action(action):
        action.status = "done"
        action.closed_at = timezone.now()
        action.save(update_fields=["status", "closed_at", "updated_at"])

    @staticmethod
    def _notify_employee(employee, title, message, tenant, created_by=None, related_object_id=None, notification_type="poka_yoke", type_value="info"):
        user = getattr(employee, "user_account", None)
        if not user:
            return None
        return Notification.objects.create(
            tenant=tenant,
            created_by=created_by,
            recipient=user,
            title=title,
            message=message,
            type=type_value,
            notification_type=notification_type,
            related_object_id=related_object_id,
        )

    @staticmethod
    def _notify_employee_once_today(employee, title, message, tenant, created_by=None, related_object_id=None, notification_type="poka_yoke", type_value="info"):
        user = getattr(employee, "user_account", None)
        if not user:
            return None
        if Notification.objects.filter(
            tenant=tenant,
            recipient=user,
            notification_type=notification_type,
            related_object_id=related_object_id,
            created_at__date=timezone.localdate(),
        ).exists():
            return None
        return PokaYokeService._notify_employee(
            employee,
            title,
            message,
            tenant,
            created_by,
            related_object_id,
            notification_type,
            type_value,
        )

    @staticmethod
    @transaction.atomic
    def check_overdue_verifications(tenant=None):
        today = timezone.localdate()
        tenants = [tenant] if tenant else Tenant.objects.filter(status__in=["active", "trial"])
        results = []
        for current_tenant in tenants:
            devices = PokaYokeDevice.objects.filter(
                tenant=current_tenant,
                status=PokaYokeDevice.Status.ACTIVE,
                next_verification_due__lt=today,
                is_active=True,
                is_deleted=False,
            ).select_related("owner")
            for device in devices:
                notification = PokaYokeService._notify_employee_once_today(
                    device.owner,
                    "Poka-Yoke verification overdue",
                    f"{device.name} verification was due on {device.next_verification_due}.",
                    device.tenant,
                    device.created_by,
                    device.id,
                    "poka_yoke_verification_overdue",
                    "warning",
                )
                if device.criticality in [PokaYokeDevice.Criticality.HIGH, PokaYokeDevice.Criticality.CRITICAL]:
                    action = PokaYokeService._upsert_action(
                        tenant=device.tenant,
                        created_by=device.created_by,
                        reference_id=device.id,
                        action_type="overdue_verification",
                        title=f"Poka-Yoke verification overdue: {device.name}",
                        description=f"Verification due date: {device.next_verification_due}",
                        priority=PokaYokeService._criticality_to_priority(device.criticality),
                        assigned_to=device.owner,
                    )
                    results.append({
                        "device_id": str(device.id),
                        "action_id": str(action.id),
                        "notification_created": bool(notification),
                    })
                else:
                    results.append({
                        "device_id": str(device.id),
                        "action_id": None,
                        "notification_created": bool(notification),
                    })
        return results

    @staticmethod
    def dashboard_metrics(tenant):
        today = timezone.localdate()
        devices = PokaYokeDevice.objects.filter(tenant=tenant, is_active=True, is_deleted=False)
        checks = PokaYokeCheck.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
            device__is_active=True,
            device__is_deleted=False,
        )
        defects = PokaYokeDefect.objects.filter(tenant=tenant, is_active=True, is_deleted=False)
        improvements = PokaYokeImprovement.objects.filter(tenant=tenant, is_active=True, is_deleted=False)
        active_device_count = devices.filter(status=PokaYokeDevice.Status.ACTIVE).count()
        due_count = devices.filter(status=PokaYokeDevice.Status.ACTIVE, next_verification_due__isnull=False).count()
        compliant_count = devices.filter(
            status=PokaYokeDevice.Status.ACTIVE,
            next_verification_due__gte=today,
        ).count()
        compliance_rate = 0
        if due_count:
            compliance_rate = round((compliant_count / due_count) * 100, 2)
        return {
            "active_devices": active_device_count,
            "failed_checks": checks.filter(result=PokaYokeCheck.Result.FAILED).count(),
            "open_defects": defects.exclude(status__in=[
                PokaYokeDefect.Status.VERIFIED,
                PokaYokeDefect.Status.CLOSED,
            ]).count(),
            "defects_by_severity": list(
                defects.values("severity").annotate(count=Count("id")).order_by("severity")
            ),
            "overdue_verifications": devices.filter(
                status=PokaYokeDevice.Status.ACTIVE,
                next_verification_due__lt=today,
            ).count(),
            "actions_open": Action.objects.filter(
                tenant=tenant,
                module_source="poka_yoke",
                status__in=["open", "in_progress"],
                is_active=True,
                is_deleted=False,
            ).count(),
            "improvements_in_progress": improvements.filter(
                status=PokaYokeImprovement.Status.IN_PROGRESS
            ).count(),
            "verification_compliance_rate": compliance_rate,
        }

    @staticmethod
    @transaction.atomic
    def create_device(serializer, **save_kwargs):
        return serializer.save(**save_kwargs)

    @staticmethod
    @transaction.atomic
    def update_device(serializer):
        requested_status = serializer.validated_data.get("status")
        if requested_status:
            PokaYokeService.validate_transition(
                serializer.instance.status,
                requested_status,
                PokaYokeService.DEVICE_TRANSITIONS,
                "device",
            )
        return serializer.save()

    @staticmethod
    @transaction.atomic
    def save_check(serializer, **save_kwargs):
        instance = serializer.save(**save_kwargs)
        return PokaYokeService.evaluate_check(instance)

    @staticmethod
    @transaction.atomic
    def save_defect(serializer, **save_kwargs):
        requested_status = serializer.validated_data.get("status")
        if serializer.instance and requested_status:
            PokaYokeService.validate_transition(
                serializer.instance.status,
                requested_status,
                PokaYokeService.DEFECT_TRANSITIONS,
                "defect",
            )
        instance = serializer.save(**save_kwargs)
        return PokaYokeService.register_defect(instance)

    @staticmethod
    @transaction.atomic
    def save_improvement(serializer, **save_kwargs):
        requested_status = serializer.validated_data.get("status")
        if serializer.instance and requested_status:
            PokaYokeService.validate_transition(
                serializer.instance.status,
                requested_status,
                PokaYokeService.IMPROVEMENT_TRANSITIONS,
                "improvement",
            )
        instance = serializer.save(**save_kwargs)
        return PokaYokeService.sync_improvement_action(instance)

    @staticmethod
    @transaction.atomic
    def soft_delete(instance, user=None):
        instance.soft_delete(user=user)
        return instance

    @staticmethod
    def employee_for_user(user, tenant_id):
        try:
            employee = user.employee_profile
        except Employee.DoesNotExist:
            employee = None
        if not employee:
            employee = Employee.objects.filter(user_account=user, tenant_id=tenant_id).first()
        if not employee or employee.tenant_id != tenant_id:
            raise ValidationError("Current user is not linked to an Employee in this tenant.")
        return employee

    @staticmethod
    def _severity_to_priority(severity):
        return {
            PokaYokeDefect.Severity.CRITICAL: "critical",
            PokaYokeDefect.Severity.MAJOR: "high",
            PokaYokeDefect.Severity.MINOR: "low",
        }.get(severity, "medium")

    @staticmethod
    def _criticality_to_priority(criticality):
        return {
            PokaYokeDevice.Criticality.CRITICAL: "critical",
            PokaYokeDevice.Criticality.HIGH: "high",
            PokaYokeDevice.Criticality.MEDIUM: "medium",
            PokaYokeDevice.Criticality.LOW: "low",
        }.get(criticality, "medium")

    @staticmethod
    def _priority_to_action_priority(priority):
        return {
            PokaYokeImprovement.Priority.CRITICAL: "critical",
            PokaYokeImprovement.Priority.HIGH: "high",
            PokaYokeImprovement.Priority.MEDIUM: "medium",
            PokaYokeImprovement.Priority.LOW: "low",
        }.get(priority, "medium")
