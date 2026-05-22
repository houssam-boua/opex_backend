from rest_framework import serializers

from .models import SFMEscalation, SFMKPI, SFMSession
from .services import SFMService


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


def _validate_employee_tenant(employee, tenant, message="Employee does not belong to this tenant."):
    if employee and tenant and employee.tenant_id != tenant.id:
        raise serializers.ValidationError(message)


class SFMSessionSerializer(serializers.ModelSerializer):
    facilitated_by_name = serializers.CharField(source="facilitated_by.full_name", read_only=True)
    participant_names = serializers.SerializerMethodField()

    class Meta:
        model = SFMSession
        fields = [
            "id",
            "date",
            "line",
            "tier_level",
            "facilitated_by",
            "facilitated_by_name",
            "participants",
            "participant_names",
            "status",
            "notes",
            "meeting_duration_min",
            "completed_at",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["completed_at"]

    def get_participant_names(self, obj):
        return [employee.full_name for employee in obj.participants.all()]

    def validate_line(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Line is required.")
        return value.strip()

    def validate_meeting_duration_min(self, value):
        if value <= 0 or value > 240:
            raise serializers.ValidationError("meeting_duration_min must be between 1 and 240.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        facilitated_by = attrs.get("facilitated_by", getattr(self.instance, "facilitated_by", None))
        participants = attrs.get("participants")
        _validate_employee_tenant(
            facilitated_by,
            tenant,
            "Facilitator does not belong to this tenant.",
        )
        if participants is not None:
            for participant in participants:
                _validate_employee_tenant(
                    participant,
                    tenant,
                    "Participant does not belong to this tenant.",
                )
        return attrs


class SFMKPISerializer(serializers.ModelSerializer):
    session_label = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)

    class Meta:
        model = SFMKPI
        fields = [
            "id",
            "session",
            "session_label",
            "category",
            "kpi_name",
            "objective_description",
            "target_period",
            "target",
            "actual",
            "unit",
            "trend_logic",
            "color_status",
            "orange_threshold_pct",
            "comment",
            "owner",
            "owner_name",
            "requires_action",
            "linked_action",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + [
            "color_status",
            "requires_action",
            "linked_action",
        ]

    def get_session_label(self, obj):
        return str(obj.session)

    def validate_kpi_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("KPI name is required.")
        return value.strip()

    def validate_target(self, value):
        if value < 0:
            raise serializers.ValidationError("target must be greater than or equal to 0.")
        return value

    def validate_actual(self, value):
        if value < 0:
            raise serializers.ValidationError("actual must be greater than or equal to 0.")
        return value

    def validate_orange_threshold_pct(self, value):
        if value <= 0 or value > 100:
            raise serializers.ValidationError("orange_threshold_pct must be greater than 0 and less than or equal to 100.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        session = attrs.get("session", getattr(self.instance, "session", None))
        owner = attrs.get("owner", getattr(self.instance, "owner", None))

        if session and tenant and session.tenant_id != tenant.id:
            raise serializers.ValidationError("SFM session does not belong to this tenant.")
        _validate_employee_tenant(owner, tenant, "KPI owner does not belong to this tenant.")
        return attrs


class SFMEscalationSerializer(serializers.ModelSerializer):
    kpi_name = serializers.CharField(source="kpi.kpi_name", read_only=True)
    escalated_by_name = serializers.CharField(source="escalated_by.full_name", read_only=True)
    resolved_by_name = serializers.CharField(source="resolved_by.full_name", read_only=True)

    class Meta:
        model = SFMEscalation
        fields = [
            "id",
            "session",
            "kpi",
            "kpi_name",
            "escalated_from_tier",
            "escalated_to_tier",
            "escalated_by",
            "escalated_by_name",
            "reason",
            "status",
            "resolved_by",
            "resolved_by_name",
            "resolved_at",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["escalated_from_tier", "resolved_at"]
        extra_kwargs = {"session": {"required": False}}

    def validate_reason(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Escalation reason is required.")
        return value.strip()

    def validate(self, attrs):
        tenant = _request_tenant(self)
        session = attrs.get("session", getattr(self.instance, "session", None))
        kpi = attrs.get("kpi", getattr(self.instance, "kpi", None))
        escalated_by = attrs.get("escalated_by", getattr(self.instance, "escalated_by", None))
        resolved_by = attrs.get("resolved_by", getattr(self.instance, "resolved_by", None))
        target_tier = attrs.get("escalated_to_tier", getattr(self.instance, "escalated_to_tier", None))

        if kpi and tenant and kpi.tenant_id != tenant.id:
            raise serializers.ValidationError("SFM KPI does not belong to this tenant.")
        if session and tenant and session.tenant_id != tenant.id:
            raise serializers.ValidationError("SFM session does not belong to this tenant.")
        if kpi and session and kpi.session_id != session.id:
            raise serializers.ValidationError("Escalation KPI must belong to the selected session.")
        if kpi and not session:
            attrs["session"] = kpi.session
            session = kpi.session

        _validate_employee_tenant(
            escalated_by,
            tenant,
            "Escalated by employee does not belong to this tenant.",
        )
        _validate_employee_tenant(
            resolved_by,
            tenant,
            "Resolved by employee does not belong to this tenant.",
        )
        if session and target_tier:
            SFMService.validate_target_tier(session.tier_level, target_tier)
        return attrs
