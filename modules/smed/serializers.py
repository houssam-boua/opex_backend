from rest_framework import serializers
from .models import SMEDSession, SMEDStep


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


def _validate_employee_tenant(employee, tenant):
    if employee and tenant and employee.tenant_id != tenant.id:
        raise serializers.ValidationError("Employee does not belong to this tenant.")


class SMEDSessionSerializer(serializers.ModelSerializer):
    machine_code = serializers.CharField(source="machine.code", read_only=True)
    machine_name = serializers.CharField(source="machine.nom", read_only=True)
    observed_by_name = serializers.CharField(source="observed_by.full_name", read_only=True)
    validated_by_name = serializers.CharField(source="validated_by.full_name", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.full_name", read_only=True)

    class Meta:
        model = SMEDSession
        fields = [
            "id",
            "machine",
            "machine_code",
            "machine_name",
            "product_before",
            "product_after",
            "observed_by",
            "observed_by_name",
            "validated_by",
            "validated_by_name",
            "date_observed",
            "status",
            "notes",
            "total_time_before",
            "total_time_after",
            "internal_time_before",
            "internal_time_after",
            "external_time_before",
            "external_time_after",
            "improvement_pct",
            "externalisation_gain_pct",
            "approved_at",
            "approved_by",
            "approved_by_name",
            "locked_for_editing",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + [
            "total_time_before",
            "total_time_after",
            "internal_time_before",
            "internal_time_after",
            "external_time_before",
            "external_time_after",
            "improvement_pct",
            "externalisation_gain_pct",
            "approved_at",
            "approved_by",
            "locked_for_editing",
        ]

    def validate(self, attrs):
        tenant = _request_tenant(self)
        machine = attrs.get("machine", getattr(self.instance, "machine", None))
        observed_by = attrs.get("observed_by", getattr(self.instance, "observed_by", None))
        validated_by = attrs.get("validated_by", getattr(self.instance, "validated_by", None))

        if machine and tenant and machine.tenant_id != tenant.id:
            raise serializers.ValidationError("Machine does not belong to this tenant.")
        _validate_employee_tenant(observed_by, tenant)
        _validate_employee_tenant(validated_by, tenant)
        return attrs


class SMEDStepSerializer(serializers.ModelSerializer):
    session_label = serializers.SerializerMethodField()
    operator_name = serializers.CharField(source="operator.full_name", read_only=True)

    class Meta:
        model = SMEDStep
        fields = [
            "id",
            "session",
            "session_label",
            "description",
            "step_type",
            "duration_before_sec",
            "duration_after_sec",
            "can_externalise",
            "is_optimised",
            "order",
            "operator",
            "operator_name",
            "notes",
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
        session = attrs.get("session", getattr(self.instance, "session", None))
        operator = attrs.get("operator", getattr(self.instance, "operator", None))

        if session and tenant and session.tenant_id != tenant.id:
            raise serializers.ValidationError("SMED session does not belong to this tenant.")
        _validate_employee_tenant(operator, tenant)

        duration_before = attrs.get(
            "duration_before_sec",
            getattr(self.instance, "duration_before_sec", 0),
        )
        duration_after = attrs.get(
            "duration_after_sec",
            getattr(self.instance, "duration_after_sec", 0),
        )
        if duration_after > duration_before and session and session.status == SMEDSession.Status.OPTIMISED:
            raise serializers.ValidationError("An optimised setup cannot become slower.")
        return attrs

    def get_session_label(self, obj):
        return str(obj.session)

    def validate_duration_before_sec(self, value):
        if value < 0:
            raise serializers.ValidationError("duration_before_sec must be greater than or equal to 0.")
        if value > 86400:
            raise serializers.ValidationError("duration_before_sec cannot exceed 86400 seconds.")
        return value

    def validate_duration_after_sec(self, value):
        if value < 0:
            raise serializers.ValidationError("duration_after_sec must be greater than or equal to 0.")
        if value > 86400:
            raise serializers.ValidationError("duration_after_sec cannot exceed 86400 seconds.")
        return value

    def validate_order(self, value):
        if value < 0:
            raise serializers.ValidationError("order must be greater than or equal to 0.")
        return value
