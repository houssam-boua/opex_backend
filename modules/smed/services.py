from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import SMEDSession, SMEDStep


class SMEDService:
    ALLOWED_STATUS_TRANSITIONS = {
        SMEDSession.Status.OBSERVATION: {SMEDSession.Status.ANALYSIS},
        SMEDSession.Status.ANALYSIS: {SMEDSession.Status.OPTIMISED},
        SMEDSession.Status.OPTIMISED: set(),
    }
    MANAGEMENT_ROLES = {"super_admin", "tenant_admin", "plant_manager", "quality_mgr", "supervisor"}

    @staticmethod
    @transaction.atomic
    def recalculate_session_metrics(session):
        session = SMEDSession.objects.select_for_update().get(pk=session.pk)
        SMEDService.assert_session_editable(session, "recalculate")

        steps = SMEDStep.objects.filter(
            session=session,
            tenant=session.tenant,
            is_active=True,
            is_deleted=False,
        )

        totals = steps.aggregate(
            total_before=Sum("duration_before_sec"),
            total_after=Sum("duration_after_sec"),
            internal_before=Sum(
                "duration_before_sec",
                filter=models.Q(step_type=SMEDStep.StepType.INTERNAL),
            ),
            internal_after=Sum(
                "duration_after_sec",
                filter=models.Q(step_type=SMEDStep.StepType.INTERNAL),
            ),
            external_before=Sum(
                "duration_before_sec",
                filter=models.Q(step_type=SMEDStep.StepType.EXTERNAL),
            ),
            external_after=Sum(
                "duration_after_sec",
                filter=models.Q(step_type=SMEDStep.StepType.EXTERNAL),
            ),
        )

        total_before = totals["total_before"] or 0
        total_after = totals["total_after"] or 0
        internal_before = totals["internal_before"] or 0
        internal_after = totals["internal_after"] or 0
        external_before = totals["external_before"] or 0
        external_after = totals["external_after"] or 0

        session.total_time_before = total_before
        session.total_time_after = total_after
        session.internal_time_before = internal_before
        session.internal_time_after = internal_after
        session.external_time_before = external_before
        session.external_time_after = external_after
        session.improvement_pct = SMEDService._percentage_gain(total_before, total_after)
        session.externalisation_gain_pct = SMEDService._percentage_gain(internal_before, internal_after)
        session.save(update_fields=[
            "total_time_before",
            "total_time_after",
            "internal_time_before",
            "internal_time_after",
            "external_time_before",
            "external_time_after",
            "improvement_pct",
            "externalisation_gain_pct",
            "updated_at",
        ])
        return session

    @staticmethod
    def _percentage_gain(before, after):
        if before == 0:
            return Decimal("0.00")
        value = (Decimal(before - after) / Decimal(before)) * Decimal("100")
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def validate_status_transition(current_status, next_status):
        if current_status == next_status:
            return
        allowed = SMEDService.ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
        if next_status not in allowed:
            raise ValidationError(
                f"Invalid SMED status transition: {current_status} -> {next_status}."
            )

    @staticmethod
    def assert_session_editable(session, action="edit"):
        if session.status == SMEDSession.Status.OPTIMISED and session.locked_for_editing:
            raise ValidationError(f"SMED session is approved and locked; cannot {action}.")

    @staticmethod
    @transaction.atomic
    def create_session(serializer, **save_kwargs):
        requested_status = serializer.validated_data.get(
            "status",
            SMEDSession.Status.OBSERVATION,
        )
        if requested_status != SMEDSession.Status.OBSERVATION:
            raise ValidationError("SMED sessions must start in observation status.")
        return serializer.save(**save_kwargs)

    @staticmethod
    @transaction.atomic
    def update_session(serializer):
        session = SMEDSession.objects.select_for_update().get(pk=serializer.instance.pk)
        SMEDService.assert_session_editable(session, "edit")
        next_status = serializer.validated_data.get("status", session.status)
        SMEDService.validate_status_transition(session.status, next_status)
        return serializer.save()

    @staticmethod
    @transaction.atomic
    def delete_session(session, user=None):
        session = SMEDSession.objects.select_for_update().get(pk=session.pk)
        SMEDService.assert_session_editable(session, "delete")
        session.soft_delete(user=user)
        return session

    @staticmethod
    @transaction.atomic
    def save_step(serializer, **save_kwargs):
        existing_session = serializer.instance.session if serializer.instance else None
        target_session = serializer.validated_data.get("session", existing_session)
        if existing_session:
            existing_session = SMEDSession.objects.select_for_update().get(pk=existing_session.pk)
            SMEDService.assert_session_editable(existing_session, "modify steps")
        target_session = SMEDSession.objects.select_for_update().get(pk=target_session.pk)
        SMEDService.assert_session_editable(target_session, "modify steps")

        instance = serializer.save(**save_kwargs)
        if existing_session and existing_session.pk != target_session.pk:
            SMEDService.recalculate_session_metrics(existing_session)
        SMEDService.recalculate_session_metrics(target_session)
        return instance

    @staticmethod
    @transaction.atomic
    def delete_step(instance, user=None):
        session = SMEDSession.objects.select_for_update().get(pk=instance.session_id)
        SMEDService.assert_session_editable(session, "delete steps")
        instance.soft_delete(user=user)
        SMEDService.recalculate_session_metrics(session)
        return instance

    @staticmethod
    @transaction.atomic
    def approve_session(session, user):
        session = SMEDSession.objects.select_for_update().get(pk=session.pk)
        if session.status != SMEDSession.Status.OPTIMISED:
            raise ValidationError("Only optimised SMED sessions can be approved.")
        employee = SMEDService._employee_for_user(user, session.tenant_id)
        session.approved_at = timezone.now()
        session.approved_by = employee
        session.locked_for_editing = True
        session.save(update_fields=["approved_at", "approved_by", "locked_for_editing", "updated_at"])
        return session

    @staticmethod
    @transaction.atomic
    def unlock_session(session, user):
        SMEDService.assert_management_user(user)
        session = SMEDSession.objects.select_for_update().get(pk=session.pk)
        session.locked_for_editing = False
        session.status = SMEDSession.Status.ANALYSIS
        session.approved_at = None
        session.approved_by = None
        session.save(update_fields=[
            "locked_for_editing",
            "status",
            "approved_at",
            "approved_by",
            "updated_at",
        ])
        return session

    @staticmethod
    def assert_management_user(user):
        if not user or not user.is_authenticated or user.role not in SMEDService.MANAGEMENT_ROLES:
            raise PermissionDenied("Only management roles can unlock approved SMED sessions.")

    @staticmethod
    def _employee_for_user(user, tenant_id):
        employee = getattr(user, "employee_profile", None)
        if not employee or employee.tenant_id != tenant_id:
            raise ValidationError("Current user is not linked to an Employee in this tenant.")
        return employee

    @staticmethod
    def dashboard_metrics(tenant):
        sessions = SMEDSession.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
        )
        saved_expr = ExpressionWrapper(
            F("total_time_before") - F("total_time_after"),
            output_field=models.IntegerField(),
        )

        summary = sessions.aggregate(
            average_improvement_pct=Coalesce(
                Avg("improvement_pct"),
                Decimal("0.00"),
                output_field=DecimalField(max_digits=7, decimal_places=2),
            ),
            total_time_saved=Coalesce(Sum(saved_expr), 0),
        )
        best_machine_gains = list(
            sessions.exclude(machine__isnull=True)
            .values("machine_id", "machine__code", "machine__nom")
            .annotate(
                average_improvement_pct=Avg("improvement_pct"),
                total_time_saved=Coalesce(Sum(saved_expr), 0),
                sessions_count=Count("id"),
            )
            .order_by("-average_improvement_pct", "-total_time_saved")[:5]
        )
        most_externalised_setups = list(
            sessions.values("id", "product_before", "product_after", "machine__code", "machine__nom")
            .annotate(
                externalisation_gain_pct_value=F("externalisation_gain_pct"),
                internal_time_before_value=F("internal_time_before"),
                internal_time_after_value=F("internal_time_after"),
            )
            .order_by("-externalisation_gain_pct", "-internal_time_before")[:5]
        )
        setup_trend = list(
            sessions.annotate(period=TruncDate("date_observed"))
            .values("period")
            .annotate(
                average_improvement_pct=Avg("improvement_pct"),
                average_total_time_after=Avg("total_time_after"),
                total_time_saved=Coalesce(Sum(saved_expr), 0),
                sessions_count=Count("id"),
            )
            .order_by("period")
        )
        return {
            "average_improvement_pct": summary["average_improvement_pct"],
            "best_machine_gains": best_machine_gains,
            "most_externalised_setups": most_externalised_setups,
            "setup_trend": setup_trend,
            "total_time_saved": summary["total_time_saved"],
        }
