# modules/audits/serializers.py
"""
Audits Module — Serializers
"""
from rest_framework import serializers
from .models import AuditType, AuditPlan, Audit, AuditChecklistItem, Finding


def _validate_employee_tenant(employee, tenant):
    if employee and employee.tenant_id != tenant.id:
        raise serializers.ValidationError("L'Employee selectionne n'appartient pas au tenant courant.")


def _validate_employee_collection(employees, tenant):
    for employee in employees:
        _validate_employee_tenant(employee, tenant)


# ─── Reference Data ──────────────────────────────────────────────────

class AuditTypeSerializer(serializers.ModelSerializer):
    kind_display = serializers.SerializerMethodField()

    class Meta:
        model  = AuditType
        fields = ["id", "name", "kind", "kind_display", "description", "color", "is_active"]
        read_only_fields = ["id"]

    def get_kind_display(self, obj):
        return obj.get_kind_display()


# ─── Audit Plan ──────────────────────────────────────────────────────

class AuditPlanSerializer(serializers.ModelSerializer):
    audit_type_name   = serializers.CharField(source="audit_type.name", read_only=True)
    responsible_name  = serializers.SerializerMethodField()
    frequency_display = serializers.SerializerMethodField()

    class Meta:
        model  = AuditPlan
        fields = [
            "id", "title", "audit_type", "audit_type_name", "frequency",
            "frequency_display", "year", "description", "responsible",
            "responsible_name", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_responsible_name(self, obj):
        return obj.responsible.full_name if obj.responsible else None

    def get_frequency_display(self, obj):
        return obj.get_frequency_display()

    def validate_responsible(self, value):
        _validate_employee_tenant(value, self.context["request"].tenant)
        return value


# ─── Checklist Items ─────────────────────────────────────────────────

class AuditChecklistItemSerializer(serializers.ModelSerializer):
    rating_display = serializers.SerializerMethodField()

    class Meta:
        model  = AuditChecklistItem
        fields = [
            "id", "audit", "question", "category", "rating", "rating_display",
            "evidence", "photo", "order",
        ]
        read_only_fields = ["id"]

    def get_rating_display(self, obj):
        return obj.get_rating_display()


# ─── Findings ────────────────────────────────────────────────────────

class FindingListSerializer(serializers.ModelSerializer):
    severity_display  = serializers.SerializerMethodField()
    status_display    = serializers.SerializerMethodField()
    assigned_to_name  = serializers.SerializerMethodField()
    is_overdue        = serializers.ReadOnlyField()

    class Meta:
        model  = Finding
        fields = [
            "id", "audit", "title", "severity", "severity_display",
            "status", "status_display", "assigned_to", "assigned_to_name",
            "due_date", "is_overdue", "clause_reference", "created_at",
        ]

    def get_severity_display(self, obj):  return obj.get_severity_display()
    def get_status_display(self, obj):    return obj.get_status_display()
    def get_assigned_to_name(self, obj):  return obj.assigned_to.full_name if obj.assigned_to else None


class FindingDetailSerializer(serializers.ModelSerializer):
    severity_display  = serializers.SerializerMethodField()
    status_display    = serializers.SerializerMethodField()
    assigned_to_name  = serializers.SerializerMethodField()
    verified_by_name  = serializers.SerializerMethodField()
    created_by_name   = serializers.SerializerMethodField()
    is_overdue        = serializers.ReadOnlyField()

    class Meta:
        model  = Finding
        fields = [
            "id", "audit", "checklist_item", "title", "description",
            "severity", "severity_display", "status", "status_display",
            "clause_reference", "assigned_to", "assigned_to_name",
            "due_date", "is_overdue", "resolution", "resolved_at",
            "verified_by", "verified_by_name", "verified_at",
            "photo", "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_severity_display(self, obj):  return obj.get_severity_display()
    def get_status_display(self, obj):    return obj.get_status_display()
    def get_assigned_to_name(self, obj):  return obj.assigned_to.full_name if obj.assigned_to else None
    def get_verified_by_name(self, obj):  return obj.verified_by.full_name if obj.verified_by else None
    def get_created_by_name(self, obj):   return obj.created_by.full_name if obj.created_by else None


class FindingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Finding
        fields = [
            "audit", "checklist_item", "title", "description", "severity",
            "clause_reference", "assigned_to", "due_date", "photo",
        ]

    def create(self, validated_data):
        _validate_employee_tenant(validated_data.get("assigned_to"), self.context["request"].tenant)
        validated_data["created_by"] = self.context["request"].user
        validated_data["tenant"]     = self.context["request"].tenant
        return Finding.objects.create(**validated_data)


# ─── Audit ───────────────────────────────────────────────────────────

class AuditListSerializer(serializers.ModelSerializer):
    audit_type_name    = serializers.CharField(source="audit_type.name", read_only=True)
    status_display     = serializers.SerializerMethodField()
    priority_display   = serializers.SerializerMethodField()
    lead_auditor_name  = serializers.SerializerMethodField()
    findings_count     = serializers.ReadOnlyField()
    open_findings_count = serializers.ReadOnlyField()

    class Meta:
        model  = Audit
        fields = [
            "id", "reference", "title", "audit_type", "audit_type_name",
            "zone", "status", "status_display", "priority", "priority_display",
            "planned_date", "actual_date", "lead_auditor", "lead_auditor_name",
            "score", "findings_count", "open_findings_count", "created_at",
        ]

    def get_status_display(self, obj):    return obj.get_status_display()
    def get_priority_display(self, obj):  return obj.get_priority_display()
    def get_lead_auditor_name(self, obj): return obj.lead_auditor.full_name if obj.lead_auditor else None


class AuditDetailSerializer(serializers.ModelSerializer):
    audit_type_details = AuditTypeSerializer(source="audit_type", read_only=True)
    status_display     = serializers.SerializerMethodField()
    priority_display   = serializers.SerializerMethodField()
    lead_auditor_name  = serializers.SerializerMethodField()
    checklist_items    = AuditChecklistItemSerializer(many=True, read_only=True)
    findings           = FindingListSerializer(many=True, read_only=True)
    findings_count     = serializers.ReadOnlyField()
    open_findings_count = serializers.ReadOnlyField()
    created_by_name    = serializers.SerializerMethodField()

    class Meta:
        model  = Audit
        fields = [
            "id", "plan", "audit_type", "audit_type_details", "reference", "title",
            "description", "zone", "status", "status_display", "priority", "priority_display",
            "planned_date", "actual_date", "lead_auditor", "lead_auditor_name",
            "co_auditors", "auditee", "score", "conclusion",
            "completed_at", "closed_at",
            "checklist_items", "findings", "findings_count", "open_findings_count",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_status_display(self, obj):    return obj.get_status_display()
    def get_priority_display(self, obj):  return obj.get_priority_display()
    def get_lead_auditor_name(self, obj): return obj.lead_auditor.full_name if obj.lead_auditor else None
    def get_created_by_name(self, obj):   return obj.created_by.full_name if obj.created_by else None


class AuditCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Audit
        fields = [
            "plan", "audit_type", "title", "reference", "description", "zone",
            "priority", "planned_date", "lead_auditor", "co_auditors", "auditee",
        ]

    def create(self, validated_data):
        co_auditors = validated_data.pop("co_auditors", [])
        tenant = self.context["request"].tenant
        _validate_employee_tenant(validated_data.get("lead_auditor"), tenant)
        _validate_employee_tenant(validated_data.get("auditee"), tenant)
        _validate_employee_collection(co_auditors, tenant)
        validated_data["created_by"] = self.context["request"].user
        validated_data["tenant"]     = self.context["request"].tenant
        audit = Audit.objects.create(**validated_data)
        if co_auditors:
            audit.co_auditors.set(co_auditors)
        return audit


class AuditUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Audit
        fields = [
            "title", "reference", "description", "zone", "status", "priority",
            "planned_date", "actual_date", "lead_auditor", "co_auditors", "auditee",
            "score", "conclusion",
        ]

    def validate(self, attrs):
        tenant = self.context["request"].tenant
        _validate_employee_tenant(attrs.get("lead_auditor"), tenant)
        _validate_employee_tenant(attrs.get("auditee"), tenant)
        _validate_employee_collection(attrs.get("co_auditors", []), tenant)
        return attrs
