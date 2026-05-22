# modules/visual_management/serializers.py
from rest_framework import serializers
from .models import ProductionLine, AndonCall, AndonResponse, AndonAlert

class ProductionLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionLine
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class AndonResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AndonResponse
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class AndonCallSerializer(serializers.ModelSerializer):
    responses = AndonResponseSerializer(many=True, read_only=True)
    
    class Meta:
        model = AndonCall
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class AndonAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = AndonAlert
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]
