from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Count, ExpressionWrapper, F, fields
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Employee
from core.models import Tenant
from shared.models import Action, Notification
from .models import (
    RoutineDeviation,
    RoutineExecution,
    RoutineStep,
    RoutineStepResponse,
    RoutineTemplate,
)


class RoutineService:
    TERMINAL_EXECUTION_STATUSES = {
        RoutineExecution.Status.COMPLETED,
        RoutineExecution.Status.FAILED,
        RoutineExecution.Status.MISSED,
        RoutineExecution.Status.CANCELLED,
    }

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
    @transaction.atomic
    def start_execution(execution, employee):
        execution = RoutineExecution.objects.select_for_update().select_related("template").get(pk=execution.pk)
        if execution.status != RoutineExecution.Status.SCHEDULED:
            raise ValidationError("Only scheduled executions can be started.")
        if employee and employee.tenant_id != execution.tenant_id:
            raise ValidationError("Executor does not belong to this tenant.")
        execution.status = RoutineExecution.Status.IN_PROGRESS
        execution.started_at = timezone.now()
        execution.executed_by = employee
        execution.save(update_fields=["status", "started_at", "executed_by", "updated_at"])
        return execution

    @staticmethod
    @transaction.atomic
    def submit_step_response(response):
        response = RoutineStepResponse.objects.select_for_update().select_related(
            "execution",
            "execution__template",
            "step",
        ).get(pk=response.pk)
        if response.execution.status in RoutineService.TERMINAL_EXECUTION_STATUSES:
            raise ValidationError("Responses cannot be changed after execution is closed.")
        RoutineService._validate_response_value(response)
        if not response.responded_at:
            response.responded_at = timezone.now()
            response.save(update_fields=["responded_at", "updated_at"])
        if response.step.is_required and response.result == RoutineStepResponse.Result.FAIL:
            deviation = RoutineService._create_or_update_response_deviation(response)
            action = RoutineService.sync_deviation_action(deviation)
            response.linked_action = action
            response.save(update_fields=["linked_action", "updated_at"])
        elif response.linked_action and response.result == RoutineStepResponse.Result.PASS:
            RoutineService._close_action(response.linked_action)
        return response

    @staticmethod
    @transaction.atomic
    def complete_execution(execution):
        execution = RoutineExecution.objects.select_for_update().select_related("template").get(pk=execution.pk)
        if execution.status != RoutineExecution.Status.IN_PROGRESS:
            raise ValidationError("Only in-progress executions can be completed.")
        required_steps = RoutineStep.objects.filter(
            tenant=execution.tenant,
            template=execution.template,
            is_required=True,
            is_active=True,
            is_deleted=False,
        )
        response_by_step = {
            response.step_id: response
            for response in RoutineStepResponse.objects.filter(
                tenant=execution.tenant,
                execution=execution,
                is_active=True,
                is_deleted=False,
            )
        }
        missing = []
        skipped_required = []
        failed = False
        for step in required_steps:
            response = response_by_step.get(step.id)
            if not response:
                missing.append(step.title)
                continue
            if response.result == RoutineStepResponse.Result.NOT_APPLICABLE:
                skipped_required.append(step.title)
            if response.result == RoutineStepResponse.Result.FAIL:
                failed = True
        if missing:
            raise ValidationError({"required_steps": f"Missing required responses: {', '.join(missing)}"})
        if skipped_required:
            raise ValidationError({"required_steps": f"Required steps cannot be skipped: {', '.join(skipped_required)}"})
        optional_unanswered = RoutineStep.objects.filter(
            tenant=execution.tenant,
            template=execution.template,
            is_required=False,
            is_active=True,
            is_deleted=False,
        ).exclude(id__in=response_by_step.keys()).exists()
        execution.completed_at = timezone.now()
        execution.submitted_at = execution.submitted_at or execution.completed_at
        if failed:
            execution.status = RoutineExecution.Status.FAILED
            execution.global_result = RoutineExecution.GlobalResult.FAIL
        elif optional_unanswered:
            execution.status = RoutineExecution.Status.COMPLETED
            execution.global_result = RoutineExecution.GlobalResult.PARTIAL
        else:
            execution.status = RoutineExecution.Status.COMPLETED
            execution.global_result = RoutineExecution.GlobalResult.PASS
        execution.save(update_fields=[
            "status",
            "global_result",
            "submitted_at",
            "completed_at",
            "updated_at",
        ])
        return execution

    @staticmethod
    @transaction.atomic
    def mark_missed_executions(tenant=None):
        now = timezone.now()
        tenants = [tenant] if tenant else Tenant.objects.filter(status__in=["active", "trial"])
        results = []
        for current_tenant in tenants:
            executions = RoutineExecution.objects.select_for_update().filter(
                tenant=current_tenant,
                template__is_mandatory=True,
                scheduled_for__lt=now,
                status=RoutineExecution.Status.SCHEDULED,
                is_active=True,
                is_deleted=False,
                template__is_active=True,
                template__is_deleted=False,
            ).select_related("template")
            for execution in executions:
                execution.status = RoutineExecution.Status.MISSED
                execution.global_result = RoutineExecution.GlobalResult.FAIL
                execution.save(update_fields=["status", "global_result", "updated_at"])
                action = RoutineService._upsert_action(
                    tenant=execution.tenant,
                    created_by=execution.created_by,
                    reference_id=execution.id,
                    action_type="missed_routine",
                    title=f"Missed mandatory routine: {execution.template.title}",
                    description=(
                        f"Scheduled for: {execution.scheduled_for}\n"
                        f"Line: {execution.template.line}\n"
                        f"Routine type: {execution.template.routine_type}"
                    ),
                    priority="high",
                    assigned_to=execution.executed_by or execution.template.owner,
                )
                RoutineService._notify_employee(
                    execution.executed_by or execution.template.owner,
                    "Mandatory routine missed",
                    execution.template.title,
                    execution.tenant,
                    execution.created_by,
                    execution.id,
                    "routine_missed",
                    "warning",
                )
                results.append({"execution_id": str(execution.id), "action_id": str(action.id)})
        return results

    @staticmethod
    @transaction.atomic
    def verify_deviation(deviation, verified_by):
        deviation = RoutineDeviation.objects.select_for_update().get(pk=deviation.pk)
        if deviation.status not in [
            RoutineDeviation.Status.RESOLVED,
            RoutineDeviation.Status.ACTION_REQUIRED,
            RoutineDeviation.Status.OPEN,
        ]:
            raise ValidationError("Only open, action-required, or resolved deviations can be verified.")
        if verified_by and verified_by.tenant_id != deviation.tenant_id:
            raise ValidationError("Verifier does not belong to this tenant.")
        deviation.status = RoutineDeviation.Status.VERIFIED
        deviation.verified_by = verified_by
        deviation.verified_at = timezone.now()
        deviation.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
        if deviation.linked_action:
            RoutineService._close_action(deviation.linked_action)
        RoutineService._notify_employee(
            deviation.owner,
            "Routine deviation verified",
            deviation.title,
            deviation.tenant,
            deviation.created_by,
            deviation.id,
            "routine_deviation_verified",
            "success",
        )
        return deviation

    @staticmethod
    def dashboard_metrics(tenant):
        now = timezone.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        executions = RoutineExecution.objects.filter(tenant=tenant, is_active=True, is_deleted=False)
        deviations = RoutineDeviation.objects.filter(tenant=tenant, is_active=True, is_deleted=False)
        completed_statuses = [RoutineExecution.Status.COMPLETED, RoutineExecution.Status.FAILED]
        total_due = executions.filter(scheduled_for__gte=start, scheduled_for__lt=end).count()
        completed_today = executions.filter(
            completed_at__gte=start,
            completed_at__lt=end,
            status__in=completed_statuses,
        ).count()
        completion_rate = round((completed_today / total_due) * 100, 2) if total_due else 0
        duration_expr = ExpressionWrapper(
            F("completed_at") - F("started_at"),
            output_field=fields.DurationField(),
        )
        avg_duration = executions.filter(
            started_at__isnull=False,
            completed_at__isnull=False,
            status__in=completed_statuses,
        ).annotate(duration=duration_expr).aggregate(avg=Avg("duration"))["avg"]
        average_execution_time = round(avg_duration.total_seconds() / 60, 2) if avg_duration else 0
        return {
            "scheduled_today": total_due,
            "completed_today": completed_today,
            "missed_routines": executions.filter(status=RoutineExecution.Status.MISSED).count(),
            "failed_executions": executions.filter(status=RoutineExecution.Status.FAILED).count(),
            "open_deviations": deviations.exclude(status__in=[
                RoutineDeviation.Status.VERIFIED,
                RoutineDeviation.Status.CLOSED,
            ]).count(),
            "deviations_by_severity": list(
                deviations.values("severity").annotate(count=Count("id")).order_by("severity")
            ),
            "completion_rate": completion_rate,
            "average_execution_time": average_execution_time,
        }

    @staticmethod
    @transaction.atomic
    def sync_deviation_action(deviation):
        deviation = RoutineDeviation.objects.select_for_update().select_related(
            "execution",
            "execution__template",
        ).get(pk=deviation.pk)
        if deviation.severity in [RoutineDeviation.Severity.MAJOR, RoutineDeviation.Severity.CRITICAL]:
            deviation.status = RoutineDeviation.Status.ACTION_REQUIRED
        action = RoutineService._upsert_action(
            tenant=deviation.tenant,
            created_by=deviation.created_by,
            reference_id=deviation.id,
            action_type="deviation",
            title=f"Routine deviation: {deviation.title}",
            description=(
                f"Routine: {deviation.execution.template.title}\n"
                f"Scheduled for: {deviation.execution.scheduled_for}\n"
                f"Severity: {deviation.severity}\n"
                f"Description: {deviation.description}"
            ),
            priority=RoutineService._severity_to_priority(deviation.severity),
            assigned_to=deviation.owner or deviation.execution.template.owner,
            existing=deviation.linked_action,
        )
        deviation.linked_action = action
        deviation.save(update_fields=["status", "linked_action", "updated_at"])
        if deviation.severity == RoutineDeviation.Severity.CRITICAL:
            RoutineService._notify_employee_once_today(
                deviation.owner or deviation.execution.template.owner,
                "Critical routine deviation",
                deviation.title,
                deviation.tenant,
                deviation.created_by,
                deviation.id,
                "routine_critical_deviation",
                "error",
            )
        return action

    @staticmethod
    @transaction.atomic
    def create_template(serializer, **save_kwargs):
        code = serializer.validated_data.get("code", "").strip()
        if not code:
            serializer.validated_data["code"] = RoutineService.generate_code(
                save_kwargs["tenant"],
                serializer.validated_data.get("routine_type", RoutineTemplate.RoutineType.OTHER),
            )
        return serializer.save(**save_kwargs)

    @staticmethod
    @transaction.atomic
    def update_template(serializer):
        return serializer.save()

    @staticmethod
    def generate_code(tenant, routine_type):
        prefix_map = {
            RoutineTemplate.RoutineType.DAILY_STARTUP: "STR",
            RoutineTemplate.RoutineType.OK_DEMARRAGE: "OKD",
            RoutineTemplate.RoutineType.SAFETY_WALK: "SFT",
            RoutineTemplate.RoutineType.QUALITY_CHECK: "RQT",
            RoutineTemplate.RoutineType.MAINTENANCE_CHECK: "RMT",
            RoutineTemplate.RoutineType.SUPERVISOR_ROUTINE: "SUP",
            RoutineTemplate.RoutineType.OTHER: "RTN",
        }
        prefix = prefix_map.get(routine_type, "RTN")
        existing_codes = RoutineTemplate.objects.filter(
            tenant=tenant,
            code__startswith=prefix,
            is_active=True,
            is_deleted=False,
        ).values_list("code", flat=True)
        max_num = 0
        for code in existing_codes:
            suffix = code.replace(prefix, "", 1)
            try:
                max_num = max(max_num, int(suffix))
            except ValueError:
                continue
        next_num = max_num + 1
        new_code = f"{prefix}{next_num:04d}"
        while RoutineTemplate.objects.filter(
            tenant=tenant,
            code=new_code,
            is_active=True,
            is_deleted=False,
        ).exists():
            next_num += 1
            new_code = f"{prefix}{next_num:04d}"
        return new_code

    @staticmethod
    @transaction.atomic
    def create_execution(serializer, **save_kwargs):
        execution = serializer.save(**save_kwargs)
        assignee = execution.executed_by or execution.template.owner
        RoutineService._notify_employee(
            assignee,
            "Routine execution assigned",
            execution.template.title,
            execution.tenant,
            execution.created_by,
            execution.id,
            "routine_execution_assigned",
            "info",
        )
        return execution

    @staticmethod
    @transaction.atomic
    def save_response(serializer, **save_kwargs):
        response = serializer.save(**save_kwargs)
        return RoutineService.submit_step_response(response)

    @staticmethod
    @transaction.atomic
    def save_deviation(serializer, **save_kwargs):
        deviation = serializer.save(**save_kwargs)
        if deviation.severity in [RoutineDeviation.Severity.MAJOR, RoutineDeviation.Severity.CRITICAL]:
            RoutineService.sync_deviation_action(deviation)
        return deviation

    @staticmethod
    @transaction.atomic
    def soft_delete(instance, user=None):
        instance.soft_delete(user=user)
        return instance

    @staticmethod
    def _validate_response_value(response):
        step = response.step
        if response.responded_by and response.responded_by.tenant_id != response.tenant_id:
            raise ValidationError("Responder does not belong to this tenant.")
        if step.template_id != response.execution.template_id:
            raise ValidationError("Step does not belong to the execution template.")
        if step.step_type == RoutineStep.StepType.NUMERIC:
            if response.value_number is None and response.result != RoutineStepResponse.Result.NOT_APPLICABLE:
                raise ValidationError("Numeric steps require value_number.")
            if response.value_number is not None:
                if step.min_value is not None and response.value_number < step.min_value:
                    if response.result == RoutineStepResponse.Result.PASS:
                        raise ValidationError("Numeric value is below the allowed minimum.")
                if step.max_value is not None and response.value_number > step.max_value:
                    if response.result == RoutineStepResponse.Result.PASS:
                        raise ValidationError("Numeric value is above the allowed maximum.")
        if step.step_type in [
            RoutineStep.StepType.TEXT,
            RoutineStep.StepType.PHOTO_REQUIRED,
            RoutineStep.StepType.SIGNATURE,
        ] and response.result == RoutineStepResponse.Result.PASS and not response.value_text.strip():
            raise ValidationError("This step requires value_text evidence.")
        if step.is_required and response.result == RoutineStepResponse.Result.NOT_APPLICABLE:
            raise ValidationError("Required steps cannot be marked not applicable.")
        if step.is_required and response.result == RoutineStepResponse.Result.FAIL and not response.comment.strip():
            raise ValidationError("Failed required steps require a comment.")

    @staticmethod
    def _create_or_update_response_deviation(response):
        severity = RoutineDeviation.Severity.MAJOR
        if response.execution.template.routine_type in [
            RoutineTemplate.RoutineType.OK_DEMARRAGE,
            RoutineTemplate.RoutineType.SAFETY_WALK,
        ]:
            severity = RoutineDeviation.Severity.CRITICAL
        deviation = RoutineDeviation.objects.filter(
            tenant=response.tenant,
            response=response,
            status__in=[RoutineDeviation.Status.OPEN, RoutineDeviation.Status.ACTION_REQUIRED],
            is_active=True,
            is_deleted=False,
        ).first()
        if not deviation:
            deviation = RoutineDeviation.objects.create(
                tenant=response.tenant,
                created_by=response.created_by,
                execution=response.execution,
                response=response,
                title=f"Failed routine step: {response.step.title}",
                description=response.comment or response.step.description or response.step.title,
                severity=severity,
                status=RoutineDeviation.Status.ACTION_REQUIRED,
                detected_by=response.responded_by,
                owner=response.execution.template.owner or response.responded_by,
            )
        else:
            deviation.description = response.comment or deviation.description
            deviation.severity = severity
            deviation.detected_by = response.responded_by or deviation.detected_by
            deviation.owner = deviation.owner or response.execution.template.owner or response.responded_by
            deviation.save(update_fields=["description", "severity", "detected_by", "owner", "updated_at"])
        return deviation

    @staticmethod
    def _upsert_action(tenant, created_by, reference_id, action_type, title, description, priority, assigned_to=None, existing=None):
        action = existing or Action.objects.filter(
            tenant=tenant,
            module_source="routines",
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
            action.module_source = "routines"
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
            module_source="routines",
            reference_id=reference_id,
            action_type=action_type,
        )

    @staticmethod
    def _close_action(action):
        action.status = "done"
        action.closed_at = timezone.now()
        action.save(update_fields=["status", "closed_at", "updated_at"])

    @staticmethod
    def _notify_employee(employee, title, message, tenant, created_by=None, related_object_id=None, notification_type="routines", type_value="info"):
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
    def _notify_employee_once_today(employee, title, message, tenant, created_by=None, related_object_id=None, notification_type="routines", type_value="info"):
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
        return RoutineService._notify_employee(
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
    def _severity_to_priority(severity):
        return {
            RoutineDeviation.Severity.CRITICAL: "critical",
            RoutineDeviation.Severity.MAJOR: "high",
            RoutineDeviation.Severity.MINOR: "medium",
        }.get(severity, "medium")
