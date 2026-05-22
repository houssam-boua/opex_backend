from django.utils import timezone
from rest_framework import serializers

from .models import (
    RoutineDeviation,
    RoutineExecution,
    RoutineStep,
    RoutineStepResponse,
    RoutineTemplate,
)


BASE_READ_ONLY_FIELDS = [
    "id",
    "tenant",
    "created_by",
    "created_at",
    "updated_at",
    "is_active",
    "is_deleted",
    "deleted_at",
]


def _request_tenant(serializer):
    request = serializer.context.get("request")
    return getattr(request, "tenant", None)


def _validate_tenant(obj, tenant, message):
    if obj and tenant and obj.tenant_id != tenant.id:
        raise serializers.ValidationError(message)


def _validate_employee(employee, tenant, label):
    _validate_tenant(employee, tenant, f"{label} does not belong to this tenant.")
    if employee and (not employee.is_active or employee.is_deleted or employee.status != "active"):
        raise serializers.ValidationError(f"{label} must be an active employee.")


def _validate_action(action, tenant):
    _validate_tenant(action, tenant, "Linked action does not belong to this tenant.")


class RoutineTemplateSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = RoutineTemplate
        fields = [
            "id",
            "tenant",
            "created_by",
            "created_at",
            "updated_at",
            "is_active",
            "is_deleted",
            "deleted_at",
            "code",
            "title",
            "description",
            "video_url",
            "routine_type",
            "frequency",
            "department",
            "department_name",
            "line",
            "workstation_name",
            "owner",
            "owner_name",
            "is_mandatory",
            "estimated_duration_min",
            "status",
            "version",
            "requires_validation",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Title cannot be empty.")
        return value.strip()

    def validate_code(self, value):
        return value.strip() if value else ""

    def validate_estimated_duration_min(self, value):
        if value <= 0 or value > 480:
            raise serializers.ValidationError("Estimated duration must be between 1 and 480 minutes.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        department = attrs.get("department", getattr(self.instance, "department", None))
        owner = attrs.get("owner", getattr(self.instance, "owner", None))
        _validate_tenant(department, tenant, "Department does not belong to this tenant.")
        _validate_employee(owner, tenant, "Owner")
        line = attrs.get("line", getattr(self.instance, "line", ""))
        if not department and not line.strip():
            raise serializers.ValidationError("Line is required when no department is provided.")
        code = attrs.get("code", getattr(self.instance, "code", "")).strip()
        if code:
            qs = RoutineTemplate.objects.filter(
                tenant=tenant,
                code=code,
                is_active=True,
                is_deleted=False,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"code": "A routine template with this code already exists."})
        return attrs


class RoutineStepSerializer(serializers.ModelSerializer):
    template_title = serializers.CharField(source="template.title", read_only=True)

    class Meta:
        model = RoutineStep
        fields = [
            "id",
            "tenant",
            "created_by",
            "created_at",
            "updated_at",
            "is_active",
            "is_deleted",
            "deleted_at",
            "template",
            "template_title",
            "title",
            "description",
            "step_type",
            "expected_value",
            "min_value",
            "max_value",
            "order",
            "is_required",
            "triggers_action_on_fail",
            "is_ok_demarrage",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Title cannot be empty.")
        return value.strip()

    def validate_order(self, value):
        if value < 0:
            raise serializers.ValidationError("Order must be greater than or equal to 0.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        template = attrs.get("template", getattr(self.instance, "template", None))
        _validate_tenant(template, tenant, "Template does not belong to this tenant.")
        min_value = attrs.get("min_value", getattr(self.instance, "min_value", None))
        max_value = attrs.get("max_value", getattr(self.instance, "max_value", None))
        if min_value is not None and max_value is not None and min_value > max_value:
            raise serializers.ValidationError("min_value cannot be greater than max_value.")
        if template and template.status == RoutineTemplate.Status.ARCHIVED:
            raise serializers.ValidationError("Archived routine templates cannot be edited.")
        return attrs


class RoutineExecutionSerializer(serializers.ModelSerializer):
    template_title = serializers.CharField(source="template.title", read_only=True)
    executed_by_name = serializers.CharField(source="executed_by.full_name", read_only=True)
    validated_by_name = serializers.CharField(source="validated_by.full_name", read_only=True)

    class Meta:
        model = RoutineExecution
        fields = [
            "id",
            "tenant",
            "created_by",
            "created_at",
            "updated_at",
            "is_active",
            "is_deleted",
            "deleted_at",
            "template",
            "template_title",
            "executed_by",
            "executed_by_name",
            "scheduled_for",
            "started_at",
            "submitted_at",
            "completed_at",
            "status",
            "shift",
            "global_result",
            "notes",
            "validated_by",
            "validated_by_name",
            "validated_at",
            "validator_comment",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + [
            "started_at",
            "submitted_at",
            "completed_at",
            "global_result",
            "validated_at",
        ]

    def validate(self, attrs):
        tenant = _request_tenant(self)
        template = attrs.get("template", getattr(self.instance, "template", None))
        executed_by = attrs.get("executed_by", getattr(self.instance, "executed_by", None))
        validated_by = attrs.get("validated_by", getattr(self.instance, "validated_by", None))
        _validate_tenant(template, tenant, "Template does not belong to this tenant.")
        _validate_employee(executed_by, tenant, "Executor")
        _validate_employee(validated_by, tenant, "Validator")
        if template and template.status == RoutineTemplate.Status.ARCHIVED:
            raise serializers.ValidationError("Archived routine templates cannot be executed.")
        if self.instance and self.instance.status in [
            RoutineExecution.Status.COMPLETED,
            RoutineExecution.Status.FAILED,
            RoutineExecution.Status.MISSED,
            RoutineExecution.Status.CANCELLED,
        ]:
            raise serializers.ValidationError("Closed executions cannot be edited.")
        return attrs


class RoutineStepResponseSerializer(serializers.ModelSerializer):
    execution_template = serializers.CharField(source="execution.template.title", read_only=True)
    step_title = serializers.CharField(source="step.title", read_only=True)
    responded_by_name = serializers.CharField(source="responded_by.full_name", read_only=True)

    class Meta:
        model = RoutineStepResponse
        fields = [
            "id",
            "tenant",
            "created_by",
            "created_at",
            "updated_at",
            "is_active",
            "is_deleted",
            "deleted_at",
            "execution",
            "execution_template",
            "step",
            "step_title",
            "result",
            "value_text",
            "value_number",
            "comment",
            "responded_by",
            "responded_by_name",
            "responded_at",
            "linked_action",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["linked_action"]

    def validate(self, attrs):
        tenant = _request_tenant(self)
        execution = attrs.get("execution", getattr(self.instance, "execution", None))
        step = attrs.get("step", getattr(self.instance, "step", None))
        responded_by = attrs.get("responded_by", getattr(self.instance, "responded_by", None))
        linked_action = attrs.get("linked_action", getattr(self.instance, "linked_action", None))
        result = attrs.get("result", getattr(self.instance, "result", None))
        value_number = attrs.get("value_number", getattr(self.instance, "value_number", None))
        value_text = attrs.get("value_text", getattr(self.instance, "value_text", ""))
        comment = attrs.get("comment", getattr(self.instance, "comment", ""))
        _validate_tenant(execution, tenant, "Execution does not belong to this tenant.")
        _validate_tenant(step, tenant, "Step does not belong to this tenant.")
        _validate_employee(responded_by, tenant, "Responder")
        _validate_action(linked_action, tenant)
        if execution and execution.status in [
            RoutineExecution.Status.COMPLETED,
            RoutineExecution.Status.FAILED,
            RoutineExecution.Status.MISSED,
            RoutineExecution.Status.CANCELLED,
        ]:
            raise serializers.ValidationError("Responses cannot be edited after execution is closed.")
        if execution and step and step.template_id != execution.template_id:
            raise serializers.ValidationError("Step must belong to the same template as the execution.")
        if step:
            if step.is_required and result == RoutineStepResponse.Result.NOT_APPLICABLE:
                raise serializers.ValidationError("Required steps cannot be marked not applicable.")
            if step.is_required and result == RoutineStepResponse.Result.FAIL and not comment.strip():
                raise serializers.ValidationError("Failed required steps require a comment.")
            if step.step_type == RoutineStep.StepType.NUMERIC:
                if value_number is None and result != RoutineStepResponse.Result.NOT_APPLICABLE:
                    raise serializers.ValidationError("Numeric steps require value_number.")
                if value_number is not None:
                    if step.min_value is not None and value_number < step.min_value and result == RoutineStepResponse.Result.PASS:
                        raise serializers.ValidationError("Numeric value is below the allowed minimum.")
                    if step.max_value is not None and value_number > step.max_value and result == RoutineStepResponse.Result.PASS:
                        raise serializers.ValidationError("Numeric value is above the allowed maximum.")
            if step.step_type in [
                RoutineStep.StepType.TEXT,
                RoutineStep.StepType.PHOTO_REQUIRED,
                RoutineStep.StepType.SIGNATURE,
            ] and result == RoutineStepResponse.Result.PASS and not value_text.strip():
                raise serializers.ValidationError("This step requires value_text evidence.")
        return attrs


class RoutineDeviationSerializer(serializers.ModelSerializer):
    execution_template = serializers.CharField(source="execution.template.title", read_only=True)
    detected_by_name = serializers.CharField(source="detected_by.full_name", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    verified_by_name = serializers.CharField(source="verified_by.full_name", read_only=True)

    class Meta:
        model = RoutineDeviation
        fields = [
            "id",
            "tenant",
            "created_by",
            "created_at",
            "updated_at",
            "is_active",
            "is_deleted",
            "deleted_at",
            "execution",
            "execution_template",
            "response",
            "title",
            "description",
            "severity",
            "status",
            "detected_by",
            "detected_by_name",
            "owner",
            "owner_name",
            "due_date",
            "linked_action",
            "verified_by",
            "verified_by_name",
            "verified_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["linked_action", "verified_by", "verified_at"]

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Title cannot be empty.")
        return value.strip()

    def validate_description(self, value):
        if not value.strip():
            raise serializers.ValidationError("Description cannot be empty.")
        return value.strip()

    def validate(self, attrs):
        tenant = _request_tenant(self)
        execution = attrs.get("execution", getattr(self.instance, "execution", None))
        response = attrs.get("response", getattr(self.instance, "response", None))
        detected_by = attrs.get("detected_by", getattr(self.instance, "detected_by", None))
        owner = attrs.get("owner", getattr(self.instance, "owner", None))
        linked_action = attrs.get("linked_action", getattr(self.instance, "linked_action", None))
        due_date = attrs.get("due_date", getattr(self.instance, "due_date", None))
        _validate_tenant(execution, tenant, "Execution does not belong to this tenant.")
        _validate_tenant(response, tenant, "Response does not belong to this tenant.")
        _validate_employee(detected_by, tenant, "Detector")
        _validate_employee(owner, tenant, "Owner")
        _validate_action(linked_action, tenant)
        if response and execution and response.execution_id != execution.id:
            raise serializers.ValidationError("Response must belong to the same execution.")
        if due_date and due_date < timezone.localdate() and not self.instance:
            raise serializers.ValidationError("Due date cannot be in the past.")
        return attrs
