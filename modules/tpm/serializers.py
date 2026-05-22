# modules/tpm/serializers.py
from rest_framework import serializers
from .models import (
    Machine, ProductionReport, Breakdown, MaintenanceTask,
    Intervention, ChecklistExecution, Kaizen
)

class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class ProductionReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionReport
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class BreakdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = Breakdown
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class MaintenanceTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceTask
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def validate_deadline(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

class InterventionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Intervention
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class ChecklistExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistExecution
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class KaizenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Kaizen
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]
