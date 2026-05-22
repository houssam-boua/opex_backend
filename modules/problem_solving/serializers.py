# modules/problem_solving/serializers.py
from rest_framework import serializers
from .models import Problem8D, RootCause8D, Action8D, QRQC, QRQCAction


def _validate_employee_tenant(employee, tenant):
    if employee and employee.tenant_id != tenant.id:
        raise serializers.ValidationError("L'Employee selectionne n'appartient pas au tenant courant.")


def _validate_employee_collection(employees, tenant):
    for employee in employees:
        _validate_employee_tenant(employee, tenant)

class Action8DSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action8D
        fields = [
            "id", "problem", "root_cause", "description", "action_type",
            "assigned_to", "due_date", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_due_date(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

    def validate_assigned_to(self, value):
        _validate_employee_tenant(value, self.context["request"].tenant)
        return value

class RootCause8DSerializer(serializers.ModelSerializer):
    actions = Action8DSerializer(many=True, read_only=True)
    class Meta:
        model = RootCause8D
        fields = [
            "id", "problem", "description", "details", "category",
            "analysis_method", "other_method", "is_root", "why_number",
            "actions", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "actions", "created_at", "updated_at"]

class Problem8DSerializer(serializers.ModelSerializer):
    root_causes = RootCause8DSerializer(many=True, read_only=True)
    actions = Action8DSerializer(many=True, read_only=True)
    class Meta:
        model = Problem8D
        fields = [
            "id", "title", "description", "status", "current_step", "level",
            "leader", "members", "workstation", "operator_id",
            "detection_method", "impacted_quantity", "importance", "plant",
            "workshop_name", "line_name", "d2_who", "d2_what", "d2_where",
            "d2_when", "d2_how", "d2_how_many", "d2_why",
            "d2_validated_by", "containment_actions", "process_continue",
            "observations", "risk_personnel", "risk_equipment",
            "non_conformity_type", "immediate_actions_validated_by",
            "rca_validated_by", "final_report_validated_by", "closed_at",
            "root_causes", "actions", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "root_causes", "actions", "created_at", "updated_at"]

    def validate(self, attrs):
        tenant = self.context["request"].tenant
        for field in (
            "leader", "d2_validated_by", "immediate_actions_validated_by",
            "rca_validated_by", "final_report_validated_by",
        ):
            _validate_employee_tenant(attrs.get(field), tenant)
        _validate_employee_collection(attrs.get("members", []), tenant)
        return attrs

class QRQCActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QRQCAction
        fields = [
            "id", "qrqc", "description", "assigned_to", "due_date", "status",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_due_date(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

    def validate_assigned_to(self, value):
        _validate_employee_tenant(value, self.context["request"].tenant)
        return value

class QRQCSerializer(serializers.ModelSerializer):
    actions = QRQCActionSerializer(many=True, read_only=True)
    class Meta:
        model = QRQC
        fields = [
            "id", "title", "problem", "poste", "urgency", "status", "cause",
            "actions", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "actions", "created_at", "updated_at"]
