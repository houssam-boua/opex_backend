from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers

from .models import PokaYokeCheck, PokaYokeDefect, PokaYokeDevice, PokaYokeImprovement
from .services import PokaYokeService


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


class PokaYokeDeviceSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)

    class Meta:
        model = PokaYokeDevice
        fields = [
            "id",
            "name",
            "code",
            "description",
            "device_type",
            "status",
            "department",
            "department_name",
            "machine",
            "workstation_name",
            "process_name",
            "owner",
            "owner_name",
            "criticality",
            "failure_mode",
            "prevention_method",
            "detection_method",
            "automatic_detection",
            "standard_reference",
            "installed_date",
            "verification_interval_days",
            "last_verified_at",
            "next_verification_due",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["last_verified_at"]

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Device name is required.")
        return value.strip()

    def validate_code(self, value):
        return (value or "").strip()

    def validate_verification_interval_days(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("verification_interval_days must be greater than 0.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        department = attrs.get("department", getattr(self.instance, "department", None))
        machine = attrs.get("machine", getattr(self.instance, "machine", None))
        owner = attrs.get("owner", getattr(self.instance, "owner", None))
        code = attrs.get("code", getattr(self.instance, "code", ""))
        requested_status = attrs.get("status")

        _validate_tenant(department, tenant, "Department does not belong to this tenant.")
        _validate_tenant(machine, tenant, "Machine does not belong to this tenant.")
        _validate_tenant(owner, tenant, "Owner does not belong to this tenant.")

        if self.instance and requested_status:
            PokaYokeService.validate_transition(
                self.instance.status,
                requested_status,
                PokaYokeService.DEVICE_TRANSITIONS,
                "device",
            )

        if code and tenant:
            qs = PokaYokeDevice.objects.filter(
                tenant=tenant,
                code=code,
                is_active=True,
                is_deleted=False,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("Active device code already exists for this tenant.")
        return attrs


class PokaYokeCheckSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True)
    checked_by_name = serializers.CharField(source="checked_by.full_name", read_only=True)

    class Meta:
        model = PokaYokeCheck
        fields = [
            "id",
            "device",
            "device_name",
            "checked_by",
            "checked_by_name",
            "checked_at",
            "result",
            "observation",
            "measured_value",
            "expected_value",
            "requires_action",
            "linked_action",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["requires_action", "linked_action"]

    def validate_measured_value(self, value):
        if value and len(value) > 150:
            raise serializers.ValidationError("measured_value cannot exceed 150 characters.")
        return value

    def validate_expected_value(self, value):
        if value and len(value) > 150:
            raise serializers.ValidationError("expected_value cannot exceed 150 characters.")
        return value

    def validate_checked_at(self, value):
        if value > timezone.now() + timedelta(days=1):
            raise serializers.ValidationError("checked_at cannot be too far in the future.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        _validate_tenant(
            attrs.get("device", getattr(self.instance, "device", None)),
            tenant,
            "Poka-Yoke device does not belong to this tenant.",
        )
        _validate_tenant(
            attrs.get("checked_by", getattr(self.instance, "checked_by", None)),
            tenant,
            "Checked by employee does not belong to this tenant.",
        )
        return attrs


class PokaYokeDefectSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True)
    detected_by_name = serializers.CharField(source="detected_by.full_name", read_only=True)
    verified_by_name = serializers.CharField(source="verified_by.full_name", read_only=True)

    class Meta:
        model = PokaYokeDefect
        fields = [
            "id",
            "device",
            "device_name",
            "title",
            "description",
            "detected_by",
            "detected_by_name",
            "detected_at",
            "severity",
            "defect_source",
            "status",
            "linked_action",
            "verified_by",
            "verified_by_name",
            "verified_at",
            "notes",
            "is_active",
            "is_deleted",
            "deleted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = BASE_READ_ONLY_FIELDS + ["linked_action", "verified_by", "verified_at"]

    def validate_title(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Defect title is required.")
        return value.strip()

    def validate_detected_at(self, value):
        if value > timezone.now() + timedelta(days=1):
            raise serializers.ValidationError("detected_at cannot be too far in the future.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        device = attrs.get("device", getattr(self.instance, "device", None))
        detected_by = attrs.get("detected_by", getattr(self.instance, "detected_by", None))
        requested_status = attrs.get("status")
        _validate_tenant(device, tenant, "Poka-Yoke device does not belong to this tenant.")
        _validate_tenant(detected_by, tenant, "Detected by employee does not belong to this tenant.")
        if self.instance and requested_status:
            PokaYokeService.validate_transition(
                self.instance.status,
                requested_status,
                PokaYokeService.DEFECT_TRANSITIONS,
                "defect",
            )
        return attrs


class PokaYokeImprovementSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True)
    defect_title = serializers.CharField(source="defect.title", read_only=True)
    proposed_by_name = serializers.CharField(source="proposed_by.full_name", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)

    class Meta:
        model = PokaYokeImprovement
        fields = [
            "id",
            "device",
            "device_name",
            "defect",
            "defect_title",
            "title",
            "description",
            "proposed_by",
            "proposed_by_name",
            "owner",
            "owner_name",
            "priority",
            "status",
            "due_date",
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
            raise serializers.ValidationError("Improvement title is required.")
        return value.strip()

    def validate_due_date(self, value):
        if value and not self.instance and value < timezone.localdate() - timedelta(days=30):
            raise serializers.ValidationError("due_date cannot be in the far past.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        device = attrs.get("device", getattr(self.instance, "device", None))
        defect = attrs.get("defect", getattr(self.instance, "defect", None))
        proposed_by = attrs.get("proposed_by", getattr(self.instance, "proposed_by", None))
        owner = attrs.get("owner", getattr(self.instance, "owner", None))
        requested_status = attrs.get("status")
        _validate_tenant(device, tenant, "Poka-Yoke device does not belong to this tenant.")
        _validate_tenant(defect, tenant, "Poka-Yoke defect does not belong to this tenant.")
        _validate_tenant(proposed_by, tenant, "Proposed by employee does not belong to this tenant.")
        _validate_tenant(owner, tenant, "Owner does not belong to this tenant.")
        if device and defect and defect.device_id and defect.device_id != device.id:
            raise serializers.ValidationError("Improvement device must match the defect device.")
        if self.instance and requested_status:
            PokaYokeService.validate_transition(
                self.instance.status,
                requested_status,
                PokaYokeService.IMPROVEMENT_TRANSITIONS,
                "improvement",
            )
        return attrs
