# modules/capa/serializers.py
"""
CAPA Module Serializers
Matches the exact JSON schema expected by the React frontend's Action type.
"""
from rest_framework import serializers
from accounts.models import Employee
from .models import CapaTicket

class CapaTicketSerializer(serializers.ModelSerializer):
    type          = serializers.CharField(source="capa_type")
    pilotId       = serializers.CharField(source="pilot.id", read_only=True)
    pilotName     = serializers.CharField(source="pilot.full_name", read_only=True, default=None)
    createdById   = serializers.CharField(source="created_by.id", read_only=True)
    createdByName = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    category5M    = serializers.CharField(source="category_5m", required=False, allow_null=True)
    
    # We map these from backend to frontend snake_case -> camelCase
    serviceId     = serializers.CharField(source="service_id", required=False, allow_null=True)
    lineId        = serializers.CharField(source="line_id", required=False, allow_null=True)
    teamId        = serializers.CharField(source="team_id", required=False, allow_null=True)
    postId        = serializers.CharField(source="post_id", required=False, allow_null=True)
    
    rootCause     = serializers.CharField(source="root_cause", required=False, allow_blank=True)
    dueDate       = serializers.DateField(source="due_date", required=False, allow_null=True)
    completedAt   = serializers.DateTimeField(source="completed_at", required=False, allow_null=True)
    validatedAt   = serializers.DateTimeField(source="validated_at", required=False, allow_null=True)
    createdAt     = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt     = serializers.DateTimeField(source="updated_at", read_only=True)
    
    progressPercent   = serializers.IntegerField(source="progress_percent", default=0)
    efficiencyPercent = serializers.IntegerField(source="efficiency_percent", required=False, allow_null=True)
    isEffective       = serializers.BooleanField(source="is_effective", required=False, allow_null=True)

    class Meta:
        model = CapaTicket
        fields = [
            "id", "title", "description", "problem", "rootCause", "type", "status", "urgency",
            "category5M", "pilotId", "pilotName", "createdById", "createdByName",
            "serviceId", "lineId", "teamId", "postId", "dueDate", "createdAt", "updatedAt",
            "completedAt", "validatedAt", "progressPercent", "efficiencyPercent", "isEffective"
        ]

    def validate_dueDate(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

    def create(self, validated_data):
        pilot_id = self.initial_data.get("pilotId")
        validated_data["created_by"] = self.context["request"].user
        validated_data["tenant"]     = self.context["request"].tenant
        if pilot_id:
            if not Employee.objects.filter(id=pilot_id, tenant=self.context["request"].tenant).exists():
                raise serializers.ValidationError({"pilotId": "Employee invalide pour ce tenant."})
            validated_data["pilot_id"] = pilot_id
            
        return super().create(validated_data)

    def update(self, instance, validated_data):
        pilot_id = self.initial_data.get("pilotId")
        if pilot_id:
            if not Employee.objects.filter(id=pilot_id, tenant=self.context["request"].tenant).exists():
                raise serializers.ValidationError({"pilotId": "Employee invalide pour ce tenant."})
            validated_data["pilot_id"] = pilot_id
        return super().update(instance, validated_data)
