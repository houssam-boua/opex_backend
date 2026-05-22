from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Employee
from modules.skills.models import EmployeeSkill
from shared.models import Action, Notification
from .models import (
    RotationAssignment,
    RotationIncident,
    RotationPlan,
    RotationRule,
    RotationSlot,
    RotationViolation,
    Workstation,
)


class RotationService:
    RISKY_LEVELS = {Workstation.RiskLevel.HIGH, Workstation.RiskLevel.CRITICAL}

    @staticmethod
    @transaction.atomic
    def validate_plan(plan):
        plan = RotationPlan.objects.select_for_update().get(pk=plan.pk)
        assignments = RotationAssignment.objects.filter(
            tenant=plan.tenant,
            plan=plan,
            is_active=True,
            is_deleted=False,
        ).select_related("employee", "slot", "workstation", "replacement_for")
        rules = {
            rule.rule_type: rule
            for rule in RotationRule.objects.filter(
                tenant=plan.tenant,
                is_active=True,
                is_deleted=False,
                is_enabled=True,
            )
        }
        current_keys = set()

        RotationService._detect_duplicate_assignments(plan, assignments, current_keys)
        RotationService._detect_required_skill_gaps(plan, assignments, rules, current_keys)
        RotationService._detect_high_risk_repetition(plan, assignments, rules, current_keys)
        RotationService._detect_consecutive_station(plan, assignments, rules, current_keys)
        RotationService._detect_invalid_replacements(plan, assignments, current_keys)
        RotationService._resolve_stale_violations(plan, current_keys)

        blocking = RotationViolation.objects.filter(
            tenant=plan.tenant,
            plan=plan,
            severity=RotationViolation.Severity.BLOCKING,
            resolved=False,
            is_active=True,
            is_deleted=False,
        ).count()
        warning = RotationViolation.objects.filter(
            tenant=plan.tenant,
            plan=plan,
            severity=RotationViolation.Severity.WARNING,
            resolved=False,
            is_active=True,
            is_deleted=False,
        ).count()
        info = RotationViolation.objects.filter(
            tenant=plan.tenant,
            plan=plan,
            severity=RotationViolation.Severity.INFO,
            resolved=False,
            is_active=True,
            is_deleted=False,
        ).count()
        return {
            "plan": str(plan.id),
            "blocking": blocking,
            "warning": warning,
            "info": info,
            "total_open": blocking + warning + info,
        }

    @staticmethod
    def _detect_duplicate_assignments(plan, assignments, current_keys):
        employee_dupes = (
            assignments.values("slot_id", "employee_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )
        for item in employee_dupes:
            message = "Employee is assigned more than once in the same slot."
            RotationService._upsert_violation(
                plan,
                None,
                None,
                RotationViolation.Severity.BLOCKING,
                message,
                current_keys,
            )

        workstation_dupes = (
            assignments.values("slot_id", "workstation_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )
        for item in workstation_dupes:
            message = "Workstation is double-booked in the same slot."
            RotationService._upsert_violation(
                plan,
                None,
                None,
                RotationViolation.Severity.BLOCKING,
                message,
                current_keys,
            )

    @staticmethod
    def _detect_required_skill_gaps(plan, assignments, rules, current_keys):
        rule = rules.get(RotationRule.RuleType.REQUIRED_SKILL)
        default_severity = RotationViolation.Severity.BLOCKING
        severity = getattr(rule, "severity", default_severity) if rule else default_severity
        for assignment in assignments:
            skill = assignment.workstation.required_skill
            if not skill:
                continue
            employee_skill = EmployeeSkill.objects.filter(
                tenant=plan.tenant,
                employee=assignment.employee,
                skill=skill,
                is_active=True,
                is_deleted=False,
            ).first()
            if not employee_skill or employee_skill.level < assignment.workstation.required_skill_level:
                level = employee_skill.level if employee_skill else 0
                message = (
                    f"Operator lacks required skill for {assignment.workstation.name}: "
                    f"has {level}, needs {assignment.workstation.required_skill_level}."
                )
                RotationService._upsert_violation(
                    plan,
                    assignment,
                    rule,
                    severity,
                    message,
                    current_keys,
                )

    @staticmethod
    def _detect_high_risk_repetition(plan, assignments, rules, current_keys):
        rule = rules.get(RotationRule.RuleType.AVOID_HIGH_RISK_REPETITION)
        if not rule:
            return
        risky = assignments.filter(workstation__risk_level__in=RotationService.RISKY_LEVELS)
        repeated = risky.values("employee_id").annotate(count=Count("id")).filter(count__gt=1)
        repeated_employee_ids = {item["employee_id"] for item in repeated}
        for assignment in risky.filter(employee_id__in=repeated_employee_ids):
            message = f"High-risk repetition detected for {assignment.employee.full_name}."
            RotationService._upsert_violation(
                plan,
                assignment,
                rule,
                rule.severity,
                message,
                current_keys,
            )

    @staticmethod
    def _detect_consecutive_station(plan, assignments, rules, current_keys):
        rule = rules.get(RotationRule.RuleType.MAX_CONSECUTIVE_SAME_STATION)
        if not rule:
            return
        max_count = int(rule.value_json.get("max_count", 3) or 3)
        if max_count <= 0:
            return
        previous_dates = [plan.date - timedelta(days=i) for i in range(1, max_count + 1)]
        for assignment in assignments:
            previous_count = RotationAssignment.objects.filter(
                tenant=plan.tenant,
                employee=assignment.employee,
                workstation=assignment.workstation,
                plan__date__in=previous_dates,
                is_active=True,
                is_deleted=False,
                plan__is_active=True,
                plan__is_deleted=False,
            ).count()
            if previous_count >= max_count:
                message = (
                    f"{assignment.employee.full_name} exceeds consecutive station limit "
                    f"on {assignment.workstation.name}."
                )
                RotationService._upsert_violation(
                    plan,
                    assignment,
                    rule,
                    rule.severity,
                    message,
                    current_keys,
                )

    @staticmethod
    def _detect_invalid_replacements(plan, assignments, current_keys):
        for assignment in assignments:
            replacement_for = assignment.replacement_for
            if not replacement_for:
                continue
            if replacement_for.tenant_id != plan.tenant_id or replacement_for.plan_id != plan.id:
                message = "Replacement assignment must belong to the same rotation plan."
                RotationService._upsert_violation(
                    plan,
                    assignment,
                    None,
                    RotationViolation.Severity.BLOCKING,
                    message,
                    current_keys,
                )
            if replacement_for.employee_id == assignment.employee_id:
                message = "Replacement employee cannot replace their own assignment."
                RotationService._upsert_violation(
                    plan,
                    assignment,
                    None,
                    RotationViolation.Severity.WARNING,
                    message,
                    current_keys,
                )

    @staticmethod
    def _upsert_violation(plan, assignment, rule, severity, message, current_keys):
        key = (
            str(assignment.id) if assignment else "",
            str(rule.id) if rule else "",
            severity,
            message,
        )
        current_keys.add(key)
        violation, created = RotationViolation.objects.get_or_create(
            tenant=plan.tenant,
            plan=plan,
            assignment=assignment,
            rule=rule,
            severity=severity,
            message=message,
            resolved=False,
            is_deleted=False,
            defaults={"created_by": plan.created_by},
        )
        if severity == RotationViolation.Severity.BLOCKING:
            action = RotationService._sync_violation_action(violation)
            if violation.linked_action_id != action.id:
                violation.linked_action = action
                violation.save(update_fields=["linked_action", "updated_at"])
            if created:
                RotationService._notify_blocking_violation(violation)
        return violation

    @staticmethod
    def _resolve_stale_violations(plan, current_keys):
        open_violations = RotationViolation.objects.filter(
            tenant=plan.tenant,
            plan=plan,
            resolved=False,
            is_active=True,
            is_deleted=False,
        )
        for violation in open_violations:
            key = (
                str(violation.assignment_id) if violation.assignment_id else "",
                str(violation.rule_id) if violation.rule_id else "",
                violation.severity,
                violation.message,
            )
            if key not in current_keys:
                violation.resolved = True
                violation.resolved_at = timezone.now()
                violation.save(update_fields=["resolved", "resolved_at", "updated_at"])
                if violation.linked_action:
                    violation.linked_action.status = "done"
                    violation.linked_action.closed_at = timezone.now()
                    violation.linked_action.save(update_fields=["status", "closed_at", "updated_at"])

    @staticmethod
    def _sync_violation_action(violation):
        priority = {
            RotationViolation.Severity.BLOCKING: "high",
            RotationViolation.Severity.WARNING: "medium",
            RotationViolation.Severity.INFO: "low",
        }[violation.severity]
        title = f"Rotation violation: {violation.message[:180]}"
        description = "\n".join([
            f"Plan: {violation.plan.name}",
            f"Date: {violation.plan.date}",
            f"Shift: {violation.plan.shift}",
            f"Severity: {violation.severity}",
            f"Message: {violation.message}",
        ])
        if violation.linked_action:
            action = violation.linked_action
            action.title = title
            action.description = description
            action.priority = priority
            action.module_source = "rotation"
            action.action_type = "preventive"
            action.reference_id = violation.id
            action.save(update_fields=[
                "title",
                "description",
                "priority",
                "module_source",
                "action_type",
                "reference_id",
                "updated_at",
            ])
            return action
        return Action.objects.create(
            tenant=violation.tenant,
            created_by=violation.created_by,
            title=title,
            description=description,
            priority=priority,
            status="open",
            assigned_to=violation.assignment.employee if violation.assignment else violation.plan.created_by_employee,
            module_source="rotation",
            action_type="preventive",
            reference_id=violation.id,
        )

    @staticmethod
    def _notify_employee(employee, title, message, tenant, created_by=None, related_object_id=None, notification_type="rotation"):
        user = getattr(employee, "user_account", None)
        if not user:
            return None
        return Notification.objects.create(
            tenant=tenant,
            created_by=created_by,
            recipient=user,
            title=title,
            message=message,
            type="warning" if "violation" in notification_type else "info",
            notification_type=notification_type,
            related_object_id=related_object_id,
        )

    @staticmethod
    def _notify_blocking_violation(violation):
        recipients = []
        if violation.assignment:
            recipients.append(violation.assignment.employee)
        if violation.plan.created_by_employee:
            recipients.append(violation.plan.created_by_employee)
        seen = set()
        for employee in recipients:
            if employee and employee.id not in seen:
                seen.add(employee.id)
                RotationService._notify_employee(
                    employee,
                    "Blocking rotation violation",
                    violation.message,
                    violation.tenant,
                    violation.created_by,
                    violation.id,
                    "rotation_blocking_violation",
                )

    @staticmethod
    @transaction.atomic
    def publish_plan(plan, approved_by):
        plan = RotationPlan.objects.select_for_update().get(pk=plan.pk)
        RotationService.validate_plan(plan)
        if RotationViolation.objects.filter(
            tenant=plan.tenant,
            plan=plan,
            severity=RotationViolation.Severity.BLOCKING,
            resolved=False,
            is_active=True,
            is_deleted=False,
        ).exists():
            raise ValidationError("Cannot publish a plan with unresolved blocking violations.")
        if approved_by and approved_by.tenant_id != plan.tenant_id:
            raise ValidationError("Approver does not belong to this tenant.")
        plan.status = RotationPlan.Status.PUBLISHED
        plan.approved_by = approved_by
        plan.approved_at = timezone.now()
        plan.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        RotationService._notify_plan_published(plan)
        return plan

    @staticmethod
    def _notify_plan_published(plan):
        assignments = RotationAssignment.objects.filter(
            tenant=plan.tenant,
            plan=plan,
            is_active=True,
            is_deleted=False,
        ).select_related("employee")
        seen = set()
        for assignment in assignments:
            employee = assignment.employee
            if employee.id in seen:
                continue
            seen.add(employee.id)
            RotationService._notify_employee(
                employee,
                "Rotation plan published",
                f"You are assigned on {plan.name} for {plan.date} ({plan.shift}).",
                plan.tenant,
                plan.created_by,
                plan.id,
                "rotation_plan_published",
            )

    @staticmethod
    @transaction.atomic
    def complete_plan(plan):
        plan = RotationPlan.objects.select_for_update().get(pk=plan.pk)
        if plan.status != RotationPlan.Status.PUBLISHED:
            raise ValidationError("Only published rotation plans can be completed.")
        plan.status = RotationPlan.Status.COMPLETED
        plan.save(update_fields=["status", "updated_at"])
        return plan

    @staticmethod
    @transaction.atomic
    def resolve_violation(violation, resolved_by):
        violation = RotationViolation.objects.select_for_update().get(pk=violation.pk)
        if resolved_by and resolved_by.tenant_id != violation.tenant_id:
            raise ValidationError("Resolver does not belong to this tenant.")
        violation.resolved = True
        violation.resolved_by = resolved_by
        violation.resolved_at = timezone.now()
        violation.save(update_fields=["resolved", "resolved_by", "resolved_at", "updated_at"])
        if violation.linked_action:
            violation.linked_action.status = "done"
            violation.linked_action.closed_at = timezone.now()
            violation.linked_action.save(update_fields=["status", "closed_at", "updated_at"])
        if violation.assignment:
            RotationService._notify_employee(
                violation.assignment.employee,
                "Rotation violation resolved",
                violation.message,
                violation.tenant,
                getattr(resolved_by, "user_account", None),
                violation.id,
                "rotation_violation_resolved",
            )
        return violation

    @staticmethod
    @transaction.atomic
    def create_plan(serializer, **save_kwargs):
        return serializer.save(**save_kwargs)

    @staticmethod
    @transaction.atomic
    def update_plan(serializer):
        RotationService.assert_plan_editable(serializer.instance)
        requested_status = serializer.validated_data.get("status")
        if requested_status and requested_status != serializer.instance.status:
            raise ValidationError("Use publish, complete, or cancel workflows to change rotation plan status.")
        return serializer.save()

    @staticmethod
    @transaction.atomic
    def delete_plan(instance, user=None):
        RotationService.assert_plan_editable(instance)
        instance.soft_delete(user=user)
        return instance

    @staticmethod
    def assert_plan_editable(plan):
        if plan.status in [RotationPlan.Status.COMPLETED, RotationPlan.Status.CANCELLED]:
            raise ValidationError("Completed or cancelled rotation plans cannot be edited.")
        if plan.status == RotationPlan.Status.PUBLISHED:
            raise ValidationError("Published rotation plans cannot be edited directly.")

    @staticmethod
    @transaction.atomic
    def save_slot(serializer, **save_kwargs):
        plan = serializer.validated_data.get("plan", getattr(serializer.instance, "plan", None))
        RotationService.assert_plan_editable(plan)
        return serializer.save(**save_kwargs)

    @staticmethod
    @transaction.atomic
    def delete_slot(instance, user=None):
        RotationService.assert_plan_editable(instance.plan)
        instance.soft_delete(user=user)
        RotationService.validate_plan(instance.plan)
        return instance

    @staticmethod
    @transaction.atomic
    def save_assignment(serializer, **save_kwargs):
        previous_plan = serializer.instance.plan if serializer.instance else None
        plan = serializer.validated_data.get("plan", previous_plan)
        RotationService.assert_plan_editable(plan)
        instance = serializer.save(**save_kwargs)
        RotationService.validate_plan(instance.plan)
        if previous_plan and previous_plan.pk != instance.plan_id:
            RotationService.validate_plan(previous_plan)
        RotationService._notify_assignment(instance)
        return instance

    @staticmethod
    def _notify_assignment(assignment):
        RotationService._notify_employee(
            assignment.employee,
            "Rotation assignment",
            f"You are assigned to {assignment.workstation.name} on {assignment.plan.date} ({assignment.plan.shift}).",
            assignment.tenant,
            assignment.created_by,
            assignment.id,
            "rotation_assignment",
        )

    @staticmethod
    @transaction.atomic
    def delete_assignment(instance, user=None):
        plan = instance.plan
        RotationService.assert_plan_editable(plan)
        instance.soft_delete(user=user)
        RotationService.validate_plan(plan)
        return instance

    @staticmethod
    @transaction.atomic
    def save_incident(serializer, **save_kwargs):
        incident = serializer.save(**save_kwargs)
        if incident.severity == RotationIncident.Severity.CRITICAL and not incident.linked_action:
            incident.linked_action = Action.objects.create(
                tenant=incident.tenant,
                created_by=incident.created_by,
                title=f"Rotation incident: {incident.title}",
                description=incident.description,
                priority="high",
                status="open",
                assigned_to=incident.reported_by,
                module_source="rotation",
                action_type="preventive",
                reference_id=incident.id,
            )
            incident.save(update_fields=["linked_action", "updated_at"])
        return incident

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
    def calculate_rotation_analytics(tenant, date_range=None):
        today = timezone.localdate()
        plans = RotationPlan.objects.filter(tenant=tenant, is_active=True, is_deleted=False)
        assignments = RotationAssignment.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
            plan__is_active=True,
            plan__is_deleted=False,
        )
        violations = RotationViolation.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
            plan__is_active=True,
            plan__is_deleted=False,
        )
        if date_range:
            start, end = date_range
            plans = plans.filter(date__range=[start, end])
            assignments = assignments.filter(plan__date__range=[start, end])
            violations = violations.filter(plan__date__range=[start, end])

        total_slots = RotationSlot.objects.filter(
            tenant=tenant,
            is_active=True,
            is_deleted=False,
            plan__is_active=True,
            plan__is_deleted=False,
        ).count()
        covered_slots = assignments.values("slot_id").distinct().count()
        workstation_coverage = 0
        if total_slots:
            workstation_coverage = round((covered_slots / total_slots) * 100, 2)

        return {
            "plans_today": plans.filter(date=today).count(),
            "published_plans": plans.filter(status=RotationPlan.Status.PUBLISHED).count(),
            "assignments_count": assignments.count(),
            "violations_by_severity": list(
                violations.filter(resolved=False)
                .values("severity")
                .annotate(count=Count("id"))
                .order_by("severity")
            ),
            "open_blocking_violations": violations.filter(
                severity=RotationViolation.Severity.BLOCKING,
                resolved=False,
            ).count(),
            "high_risk_assignments": assignments.filter(
                workstation__risk_level__in=RotationService.RISKY_LEVELS,
            ).count(),
            "skill_gap_count": violations.filter(
                resolved=False,
                message__icontains="required skill",
            ).count(),
            "most_loaded_employees": list(
                assignments.values("employee_id", "employee__first_name", "employee__last_name")
                .annotate(assignments_count=Count("id"))
                .order_by("-assignments_count")[:10]
            ),
            "workstation_coverage": workstation_coverage,
        }
