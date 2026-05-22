# modules/risk/serializers.py
from rest_framework import serializers
from .models import RiskCategory, Risk, RiskAssessment, RiskMitigationAction, RiskHistory

class RiskCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskCategory
        fields = ["id", "name", "description", "color_code", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class RiskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Risk
        fields = [
            "id", "title", "description", "category", "severity",
            "likelihood", "impact", "risk_score", "owner", "status",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "risk_score", "created_at", "updated_at"]

    def validate(self, data):
        likelihood = data.get("likelihood")
        impact     = data.get("impact")
        if likelihood is not None and impact is not None:
            if not (1 <= likelihood <= 5) or not (1 <= impact <= 5):
                raise serializers.ValidationError(
                    "La probabilité (likelihood) et l'impact doivent être entre 1 et 5."
                )
        return data


class RiskAssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskAssessment
        fields = ["id", "risk", "assessor", "date", "notes", "updated_score", "created_at", "updated_at"]
        read_only_fields = ["id", "date", "updated_score", "created_at", "updated_at"]


class RiskMitigationActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskMitigationAction
        fields = [
            "id", "risk", "description", "owner", "deadline", "status",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_deadline(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value


class RiskHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskHistory
        fields = [
            "id", "risk", "old_score", "new_score", "changed_by",
            "changed_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "changed_at", "created_at", "updated_at"]
