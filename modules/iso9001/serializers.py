# modules/iso9001/serializers.py
from rest_framework import serializers
from .models import (
    ISO9001Clause, ComplianceAssessment, NonConformity, CorrectiveAction, ISODocument,
    ISO9001EvaluationSession, ISO9001Question, ISO9001Response
)

class ISO9001ClauseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001Clause
        fields = [
            "id", "clause_number", "title", "description", "parent",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class ComplianceAssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceAssessment
        fields = [
            "id", "clause", "assessor", "score", "status", "evidence",
            "date", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "date", "created_at", "updated_at"]

class NonConformitySerializer(serializers.ModelSerializer):
    class Meta:
        model = NonConformity
        fields = [
            "id", "clause", "description", "severity", "detected_by",
            "detected_at", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "detected_at", "created_at", "updated_at"]

class CorrectiveActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorrectiveAction
        fields = [
            "id", "non_conformity", "description", "owner", "deadline",
            "status", "verified_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_deadline(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

class ISODocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISODocument
        fields = [
            "id", "title", "clause", "file_path", "version", "valid_from",
            "valid_until", "uploaded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY BRIDGE — Serializers
# ═══════════════════════════════════════════════════════════════════════

class ISO9001EvaluationSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001EvaluationSession
        fields = [
            "id", "title", "evaluator", "status", "global_score",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "global_score", "created_at", "updated_at"]

class ISO9001QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001Question
        fields = ["id", "clause", "question_text", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class ISO9001ResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ISO9001Response
        fields = [
            "id", "session", "question", "response_status",
            "evidence_notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
