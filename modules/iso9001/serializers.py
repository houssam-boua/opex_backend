# modules/iso9001/serializers.py
from rest_framework import serializers
from .models import (
    ISO9001Clause, ComplianceAssessment, NonConformity, CorrectiveAction, ISODocument,
    ISO9001EvaluationSession, ISO9001Question, ISO9001Response
)

class ISO9001ClauseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001Clause
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class ComplianceAssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceAssessment
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class NonConformitySerializer(serializers.ModelSerializer):
    class Meta:
        model = NonConformity
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class CorrectiveActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorrectiveAction
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def validate_deadline(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

class ISODocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISODocument
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY BRIDGE — Serializers
# ═══════════════════════════════════════════════════════════════════════

class ISO9001EvaluationSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001EvaluationSession
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at", "global_score"]

class ISO9001QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001Question
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class ISO9001ResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001Response
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]
