from rest_framework import serializers

from .models import (
    RotationAssignment,
    RotationIncident,
    RotationPlan,
    RotationRule,
    RotationSlot,
    RotationViolation,
    Workstation,
)


BASE_READ_ONLY_FIELDS = [
    "id",
    "tenant",
    "created_by",
    "created_at",
    "updated_at",
    "is_deleted",
    "deleted_at",
]


def _request_tenant(serializer):
    request = serializer.context.get("request")
    return getattr(request, "tenant", None)


def _validate_tenant(obj, tenant, message):
    if obj and tenant and obj.tenant_id != tenant.id:
        raise serializers.ValidationError(message)


def _assert_plan_editable(plan):
    if not plan:
        return
    if plan.status in [RotationPlan.Status.COMPLETED, RotationPlan.Status.CANCELLED]:
        raise serializers.ValidationError("Completed or cancelled rotation plans cannot be edited.")
    if plan.status == RotationPlan.Status.PUBLISHED:
        raise serializers.ValidationError("Published rotation plans cannot be edited directly.")


class RotationPlanSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    created_by_employee_name = serializers.CharField(source="created_by_employee.full_name", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.full_name", read_only=True)

    class Meta:
        model = RotationPlan
        fields = [
            "id",
            "name",
            "date",
            "department",
            "department_name",
            "line",
            "shift",
            "status",
            "created_by_employee",
            "created_by_employee_name",
            "approved_by",
            "approved_by_name",
            "approved_at",
            "notes",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["approved_by", "approved_at"]

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Plan name is required.")
        return value.strip()

    def validate_line(self, value):
        return (value or "").strip()

    def validate(self, attrs):
        tenant = _request_tenant(self)
        department = attrs.get("department", getattr(self.instance, "department", None))
        created_by_employee = attrs.get(
            "created_by_employee",
            getattr(self.instance, "created_by_employee", None),
        )
        _validate_tenant(department, tenant, "Department does not belong to this tenant.")
        _validate_tenant(
            created_by_employee,
            tenant,
            "Plan creator employee does not belong to this tenant.",
        )
        line = attrs.get("line", getattr(self.instance, "line", ""))
        if not department and not line:
            raise serializers.ValidationError("Line is required when no department is provided.")
        if self.instance:
            _assert_plan_editable(self.instance)
        return attrs


class WorkstationSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    required_skill_name = serializers.CharField(source="required_skill.name", read_only=True)

    class Meta:
        model = Workstation
        fields = [
            "id",
            "name",
            "code",
            "department",
            "department_name",
            "line",
            "description",
            "risk_level",
            "required_skill",
            "required_skill_name",
            "required_skill_level",
            "is_critical",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Workstation name is required.")
        return value.strip()

    def validate_required_skill_level(self, value):
        if value < 1 or value > 4:
            raise serializers.ValidationError("required_skill_level must be between 1 and 4.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        _validate_tenant(
            attrs.get("department", getattr(self.instance, "department", None)),
            tenant,
            "Department does not belong to this tenant.",
        )
        _validate_tenant(
            attrs.get("required_skill", getattr(self.instance, "required_skill", None)),
            tenant,
            "Skill does not belong to this tenant.",
        )
        return attrs


class RotationSlotSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = RotationSlot
        fields = [
            "id",
            "plan",
            "plan_name",
            "start_time",
            "end_time",
            "order",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS

    def validate_order(self, value):
        if value < 0:
            raise serializers.ValidationError("order must be greater than or equal to 0.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        plan = attrs.get("plan", getattr(self.instance, "plan", None))
        _validate_tenant(plan, tenant, "Rotation plan does not belong to this tenant.")
        _assert_plan_editable(plan)
        start_time = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end_time = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError("start_time must be before end_time.")
        return attrs


class RotationAssignmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    workstation_name = serializers.CharField(source="workstation.name", read_only=True)
    slot_order = serializers.IntegerField(source="slot.order", read_only=True)

    class Meta:
        model = RotationAssignment
        fields = [
            "id",
            "plan",
            "slot",
            "slot_order",
            "employee",
            "employee_name",
            "workstation",
            "workstation_name",
            "status",
            "replacement_for",
            "comment",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS

    def validate(self, attrs):
        tenant = _request_tenant(self)
        plan = attrs.get("plan", getattr(self.instance, "plan", None))
        slot = attrs.get("slot", getattr(self.instance, "slot", None))
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        workstation = attrs.get("workstation", getattr(self.instance, "workstation", None))
        replacement_for = attrs.get("replacement_for", getattr(self.instance, "replacement_for", None))

        _validate_tenant(plan, tenant, "Rotation plan does not belong to this tenant.")
        _validate_tenant(slot, tenant, "Rotation slot does not belong to this tenant.")
        _validate_tenant(employee, tenant, "Employee does not belong to this tenant.")
        _validate_tenant(workstation, tenant, "Workstation does not belong to this tenant.")
        _validate_tenant(replacement_for, tenant, "Replacement assignment does not belong to this tenant.")
        _assert_plan_editable(plan)

        if employee and not employee.is_active:
            raise serializers.ValidationError("Employee must be active.")
        if slot and plan and slot.plan_id != plan.id:
            raise serializers.ValidationError("Assignment slot must belong to the same plan.")
        if replacement_for and plan and replacement_for.plan_id != plan.id:
            raise serializers.ValidationError("replacement_for must belong to the same plan.")
        return attrs


class RotationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RotationRule
        fields = [
            "id",
            "name",
            "description",
            "rule_type",
            "value_json",
            "severity",
            "is_enabled",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Rule name is required.")
        return value.strip()


class RotationViolationSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    employee_name = serializers.CharField(source="assignment.employee.full_name", read_only=True)
    workstation_name = serializers.CharField(source="assignment.workstation.name", read_only=True)
    resolved_by_name = serializers.CharField(source="resolved_by.full_name", read_only=True)

    class Meta:
        model = RotationViolation
        fields = [
            "id",
            "plan",
            "plan_name",
            "assignment",
            "employee_name",
            "workstation_name",
            "rule",
            "severity",
            "message",
            "resolved",
            "resolved_by",
            "resolved_by_name",
            "resolved_at",
            "linked_action",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + [
            "resolved_by",
            "resolved_at",
            "linked_action",
        ]

    def validate(self, attrs):
        tenant = _request_tenant(self)
        plan = attrs.get("plan", getattr(self.instance, "plan", None))
        assignment = attrs.get("assignment", getattr(self.instance, "assignment", None))
        rule = attrs.get("rule", getattr(self.instance, "rule", None))
        _validate_tenant(plan, tenant, "Rotation plan does not belong to this tenant.")
        _validate_tenant(assignment, tenant, "Rotation assignment does not belong to this tenant.")
        _validate_tenant(rule, tenant, "Rotation rule does not belong to this tenant.")
        if assignment and plan and assignment.plan_id != plan.id:
            raise serializers.ValidationError("Violation assignment must belong to the same plan.")
        return attrs


class RotationIncidentSerializer(serializers.ModelSerializer):
    reported_by_name = serializers.CharField(source="reported_by.full_name", read_only=True)

    class Meta:
        model = RotationIncident
        fields = [
            "id",
            "title",
            "description",
            "plan",
            "assignment",
            "reported_by",
            "reported_by_name",
            "severity",
            "occurred_at",
            "resolved",
            "resolved_at",
            "linked_action",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["linked_action"]

    def validate_title(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Incident title is required.")
        return value.strip()

    def validate(self, attrs):
        tenant = _request_tenant(self)
        plan = attrs.get("plan", getattr(self.instance, "plan", None))
        assignment = attrs.get("assignment", getattr(self.instance, "assignment", None))
        reported_by = attrs.get("reported_by", getattr(self.instance, "reported_by", None))
        _validate_tenant(plan, tenant, "Rotation plan does not belong to this tenant.")
        _validate_tenant(assignment, tenant, "Rotation assignment does not belong to this tenant.")
        _validate_tenant(reported_by, tenant, "Reporter does not belong to this tenant.")
        if assignment and plan and assignment.plan_id != plan.id:
            raise serializers.ValidationError("Incident assignment must belong to the same plan.")
        return attrs
