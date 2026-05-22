from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Employee
from shared.models import Action, Notification
from .models import SFMEscalation, SFMKPI, SFMSession


class SFMService:
    TIER_ORDER = {
        SFMSession.TierLevel.TIER_1: 1,
        SFMSession.TierLevel.TIER_2: 2,
        SFMSession.TierLevel.TIER_3: 3,
        SFMSession.TierLevel.TIER_4: 4,
    }
    HIGH_PRIORITY_RED_CATEGORIES = {
        SFMKPI.Category.SAFETY,
        SFMKPI.Category.QUALITY,
        SFMKPI.Category.DELIVERY,
    }

    @staticmethod
    def evaluate_kpi_color(target, actual, trend_logic, orange_threshold_pct=90):
        target = Decimal(str(target or 0))
        actual = Decimal(str(actual or 0))
        threshold_pct = Decimal(str(orange_threshold_pct or 0))

        if threshold_pct <= 0:
            return SFMKPI.ColorStatus.RED

        if trend_logic == SFMKPI.TrendLogic.HIGHER_IS_BETTER:
            if actual >= target:
                return SFMKPI.ColorStatus.GREEN
            orange_floor = target * threshold_pct / Decimal("100")
            return SFMKPI.ColorStatus.ORANGE if actual >= orange_floor else SFMKPI.ColorStatus.RED

        if trend_logic == SFMKPI.TrendLogic.LOWER_IS_BETTER:
            if actual <= target:
                return SFMKPI.ColorStatus.GREEN
            orange_ceiling = target / (threshold_pct / Decimal("100"))
            return SFMKPI.ColorStatus.ORANGE if actual <= orange_ceiling else SFMKPI.ColorStatus.RED

        raise ValidationError("Unsupported SFM KPI trend logic.")

    @staticmethod
    @transaction.atomic
    def evaluate_kpi(kpi):
        kpi = SFMKPI.objects.select_for_update().select_related("session").get(pk=kpi.pk)
        color = SFMService.evaluate_kpi_color(
            kpi.target,
            kpi.actual,
            kpi.trend_logic,
            kpi.orange_threshold_pct,
        )
        kpi.color_status = color
        kpi.requires_action = color == SFMKPI.ColorStatus.RED
        update_fields = ["color_status", "requires_action", "updated_at"]

        if color == SFMKPI.ColorStatus.RED:
            action = SFMService.sync_red_kpi_action(kpi)
            kpi.linked_action = action
            update_fields.append("linked_action")

        kpi.save(update_fields=update_fields)
        return kpi

    @staticmethod
    def sync_red_kpi_action(kpi):
        owner = kpi.owner or kpi.session.facilitated_by
        priority = (
            "high"
            if kpi.category in SFMService.HIGH_PRIORITY_RED_CATEGORIES
            else "medium"
        )
        title = f"SFM RED KPI: {kpi.category} - {kpi.kpi_name}"
        description = "\n".join([
            f"Session date: {kpi.session.date}",
            f"Line: {kpi.session.line}",
            f"Tier level: {kpi.session.tier_level}",
            f"Category: {kpi.category}",
            f"Target: {kpi.target}",
            f"Actual: {kpi.actual}",
            f"Unit: {kpi.unit}",
            f"Comment: {kpi.comment}",
        ])

        action = kpi.linked_action
        if action:
            action.title = title
            action.description = description
            action.priority = priority
            action.assigned_to = owner
            action.module_source = "sfm"
            action.reference_id = kpi.id
            action.action_type = "red_kpi"
            action.tenant = kpi.tenant
            action.save(update_fields=[
                "title",
                "description",
                "priority",
                "assigned_to",
                "module_source",
                "reference_id",
                "action_type",
                "tenant",
                "updated_at",
            ])
            return action

        return Action.objects.create(
            tenant=kpi.tenant,
            created_by=kpi.created_by,
            title=title,
            description=description,
            priority=priority,
            status="open",
            assigned_to=owner,
            module_source="sfm",
            reference_id=kpi.id,
            action_type="red_kpi",
        )

    @staticmethod
    @transaction.atomic
    def evaluate_session(session):
        session = SFMSession.objects.select_for_update().get(pk=session.pk)
        kpis = SFMKPI.objects.filter(
            session=session,
            tenant=session.tenant,
            is_active=True,
            is_deleted=False,
        )

        for kpi in kpis:
            SFMService.evaluate_kpi(kpi)

        has_red = kpis.filter(color_status=SFMKPI.ColorStatus.RED).exists()
        if has_red and session.status not in [
            SFMSession.Status.COMPLETED,
            SFMSession.Status.CANCELLED,
        ]:
            session.status = SFMSession.Status.ESCALATED
            session.save(update_fields=["status", "updated_at"])
        return session

    @staticmethod
    @transaction.atomic
    def escalate_kpi(kpi, target_tier, escalated_by, reason):
        kpi = SFMKPI.objects.select_for_update().select_related("session").get(pk=kpi.pk)
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("Escalation reason is required.")
        SFMService.validate_target_tier(kpi.session.tier_level, target_tier)
        if escalated_by and escalated_by.tenant_id != kpi.tenant_id:
            raise ValidationError("Escalated by employee does not belong to this tenant.")

        kpi.color_status = SFMKPI.ColorStatus.RED
        kpi.requires_action = True
        action = SFMService.sync_red_kpi_action(kpi)
        kpi.linked_action = action
        kpi.save(update_fields=["color_status", "requires_action", "linked_action", "updated_at"])

        escalation = SFMEscalation.objects.create(
            tenant=kpi.tenant,
            created_by=getattr(escalated_by, "user_account", None),
            session=kpi.session,
            kpi=kpi,
            escalated_from_tier=kpi.session.tier_level,
            escalated_to_tier=target_tier,
            escalated_by=escalated_by,
            reason=reason,
        )
        kpi.session.status = SFMSession.Status.ESCALATED
        kpi.session.save(update_fields=["status", "updated_at"])
        SFMService.create_escalation_notifications(escalation)
        return escalation

    @staticmethod
    def create_escalation_notifications(escalation):
        employees = [
            escalation.kpi.owner,
            escalation.session.facilitated_by,
        ]
        seen_user_ids = set()
        for employee in employees:
            user = getattr(employee, "user_account", None)
            if not user or user.id in seen_user_ids:
                continue
            seen_user_ids.add(user.id)
            Notification.objects.create(
                tenant=escalation.tenant,
                created_by=escalation.created_by,
                recipient=user,
                title="SFM KPI escalation",
                message=(
                    f"{escalation.kpi.kpi_name} was escalated from "
                    f"{escalation.escalated_from_tier} to {escalation.escalated_to_tier}."
                ),
                type="warning",
                notification_type="sfm_escalation",
                related_object_id=escalation.id,
            )

    @staticmethod
    def validate_target_tier(current_tier, target_tier):
        if target_tier not in SFMService.TIER_ORDER:
            raise ValidationError("Invalid escalation target tier.")
        if SFMService.TIER_ORDER[target_tier] <= SFMService.TIER_ORDER[current_tier]:
            raise ValidationError("Escalation target tier must be higher than current tier.")

    @staticmethod
    @transaction.atomic
    def complete_session(session):
        session = SFMService.evaluate_session(session)
        red_kpis = SFMKPI.objects.filter(
            session=session,
            tenant=session.tenant,
            is_active=True,
            is_deleted=False,
            color_status=SFMKPI.ColorStatus.RED,
        )
        unresolved_red_exists = red_kpis.filter(
            linked_action__isnull=True,
        ).exclude(
            escalations__is_active=True,
            escalations__is_deleted=False,
        ).exists()
        if unresolved_red_exists:
            raise ValidationError("Cannot complete SFM session with RED KPIs lacking an action or escalation.")

        session.status = SFMSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "completed_at", "updated_at"])
        return session

    @staticmethod
    @transaction.atomic
    def create_session(serializer, **save_kwargs):
        return serializer.save(**save_kwargs)

    @staticmethod
    @transaction.atomic
    def update_session(serializer):
        requested_status = serializer.validated_data.get("status")
        session = serializer.save()
        if requested_status == SFMSession.Status.COMPLETED:
            return SFMService.complete_session(session)
        return session

    @staticmethod
    @transaction.atomic
    def delete_session(instance, user=None):
        instance.soft_delete(user=user)
        return instance

    @staticmethod
    @transaction.atomic
    def save_kpi(serializer, **save_kwargs):
        previous_session = serializer.instance.session if serializer.instance else None
        instance = serializer.save(**save_kwargs)
        SFMService.evaluate_kpi(instance)
        SFMService.evaluate_session(instance.session)
        if previous_session and previous_session.pk != instance.session_id:
            SFMService.evaluate_session(previous_session)
        return instance

    @staticmethod
    @transaction.atomic
    def delete_kpi(instance, user=None):
        session = instance.session
        instance.soft_delete(user=user)
        SFMService.evaluate_session(session)
        return instance

    @staticmethod
    @transaction.atomic
    def create_escalation_from_serializer(serializer, user):
        employee = serializer.validated_data.get("escalated_by")
        if not employee:
            kpi = serializer.validated_data["kpi"]
            employee = SFMService.employee_for_user(user, kpi.tenant_id)
        escalation = SFMService.escalate_kpi(
            serializer.validated_data["kpi"],
            serializer.validated_data["escalated_to_tier"],
            employee,
            serializer.validated_data["reason"],
        )
        serializer.instance = escalation
        return escalation

    @staticmethod
    @transaction.atomic
    def update_escalation(serializer, user):
        escalation = SFMEscalation.objects.select_for_update().get(pk=serializer.instance.pk)
        next_status = serializer.validated_data.get("status", escalation.status)
        if next_status == SFMEscalation.Status.RESOLVED and not escalation.resolved_at:
            employee = SFMService.employee_for_user(user, escalation.tenant_id)
            serializer.validated_data.setdefault("resolved_by", employee)
            serializer.validated_data.setdefault("resolved_at", timezone.now())
        return serializer.save()

    @staticmethod
    @transaction.atomic
    def delete_escalation(instance, user=None):
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
    def dashboard_metrics(tenant):
        today = timezone.localdate()
        sessions = SFMSession.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
        )
        kpis = SFMKPI.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
            session__is_active=True,
            session__is_deleted=False,
        )
        escalations = SFMEscalation.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
        )

        linked_actions = kpis.filter(linked_action__isnull=False)
        linked_action_count = linked_actions.count()
        closed_action_count = linked_actions.filter(linked_action__status="done").count()
        action_closure_rate = Decimal("0.00")
        if linked_action_count:
            action_closure_rate = (
                Decimal(closed_action_count) / Decimal(linked_action_count) * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "sessions_today": sessions.filter(date=today).count(),
            "open_red_kpis": kpis.filter(color_status=SFMKPI.ColorStatus.RED).count(),
            "red_kpis_by_category": list(
                kpis.filter(color_status=SFMKPI.ColorStatus.RED)
                .values("category")
                .annotate(count=Count("id"))
                .order_by("category")
            ),
            "sqcdp_status_summary": list(
                kpis.values("category", "color_status")
                .annotate(count=Count("id"))
                .order_by("category", "color_status")
            ),
            "trend_over_last_30_days": list(
                kpis.filter(session__date__gte=today - timedelta(days=30))
                .annotate(period=TruncDate("session__date"))
                .values("period")
                .annotate(
                    green=Count("id", filter=Q(color_status=SFMKPI.ColorStatus.GREEN)),
                    orange=Count("id", filter=Q(color_status=SFMKPI.ColorStatus.ORANGE)),
                    red=Count("id", filter=Q(color_status=SFMKPI.ColorStatus.RED)),
                )
                .order_by("period")
            ),
            "escalations_open": escalations.filter(status=SFMEscalation.Status.OPEN).count(),
            "action_closure_rate": action_closure_rate,
        }
