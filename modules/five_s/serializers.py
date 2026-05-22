# modules/five_s/serializers.py
from rest_framework import serializers
from .models import AuditQuestion, AuditSession5S, AuditResponse, Anomaly5S

class AuditQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditQuestion
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class AuditResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditResponse
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class Anomaly5SSerializer(serializers.ModelSerializer):
    class Meta:
        model = Anomaly5S
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def validate_due_date(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

class AuditSession5SSerializer(serializers.ModelSerializer):
    responses = AuditResponseSerializer(many=True, read_only=True)
    anomalies = Anomaly5SSerializer(many=True, read_only=True)
    
    class Meta:
        model = AuditSession5S
        fields = "__all__"
        read_only_fields = [
            "tenant", "created_by", "created_at", "updated_at",
            "score_seiri", "score_seiton", "score_seiso", 
            "score_seiketsu", "score_shitsuke", "total_score"
        ]
