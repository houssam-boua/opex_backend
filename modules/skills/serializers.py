# modules/skills/serializers.py
from rest_framework import serializers
from .models import SkillCategory, Skill, EmployeeSkill, TrainingSession, Certification

class SkillCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillCategory
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class EmployeeSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeSkill
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class TrainingSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingSession
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

class CertificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certification
        fields = "__all__"
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]
