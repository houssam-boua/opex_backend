# modules/visual_management/serializers.py
from rest_framework import serializers
from .models import ProductionLine, AndonCall, AndonResponse, AndonAlert

class ProductionLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionLine
        fields = ["id", "name", "site", "department", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class AndonResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AndonResponse
        fields = [
            "id", "call", "responder", "response_time_seconds", "notes",
            "action_taken", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class AndonCallSerializer(serializers.ModelSerializer):
    responses = AndonResponseSerializer(many=True, read_only=True)
    
    class Meta:
        model = AndonCall
        fields = [
            "id", "line", "operator", "call_type", "severity", "description",
            "status", "acknowledged_by", "acknowledged_at", "resolved_at",
            "responses", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "responses", "created_at", "updated_at"]

class AndonAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = AndonAlert
        fields = ["id", "call", "message", "is_resolved", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
