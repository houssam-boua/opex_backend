# modules/skills/serializers.py
from rest_framework import serializers
from .models import SkillCategory, Skill, EmployeeSkill, TrainingSession, Certification

class SkillCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillCategory
        fields = ["id", "name", "description", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "category", "name", "description", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class EmployeeSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeSkill
        fields = ["id", "employee", "skill", "level", "target_level", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class TrainingSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingSession
        fields = ["id", "title", "skill", "trainer", "date", "attendees", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class CertificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certification
        fields = ["id", "employee", "name", "issued_date", "expiry_date", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
