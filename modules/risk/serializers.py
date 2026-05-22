# modules/risk/serializers.py
from rest_framework import serializers
from .models import RiskCategory, Risk, RiskAssessment, RiskMitigationAction, RiskHistory

class RiskCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskCategory
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]


class RiskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Risk
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at", "risk_score"]

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
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at", "updated_score", "date"]


class RiskMitigationActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskMitigationAction
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def validate_deadline(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value


class RiskHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskHistory
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]
