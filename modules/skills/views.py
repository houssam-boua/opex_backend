# modules/skills/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Prefetch

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import SkillCategory, Skill, EmployeeSkill, TrainingSession, Certification
from .serializers import (
    SkillCategorySerializer, SkillSerializer, EmployeeSkillSerializer,
    TrainingSessionSerializer, CertificationSerializer
)

class SkillsBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "skills"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        
    def perform_destroy(self, instance):
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()


class SkillCategoryViewSet(SkillsBaseViewSet):
    serializer_class = SkillCategorySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]

    def get_queryset(self):
        return SkillCategory.objects.filter(tenant=self.request.tenant, is_active=True)


class SkillViewSet(SkillsBaseViewSet):
    serializer_class = SkillSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["category"]
    search_fields = ["name", "description"]
    ordering_fields = ["name"]

    def get_queryset(self):
        return Skill.objects.filter(tenant=self.request.tenant, is_active=True)

    @action(detail=False, methods=["get"])
    def matrix(self, request):
        """
        The Polyvalence Matrix Engine Endpoint.
        CRITICAL PERFORMANCE RULE applied: Using select_related and prefetch_related
        to eliminate N+1 queries. We query Employees and prefetch their EmployeeSkill relations.
        """
        from accounts.models import Employee
        
        # 1. Fetch skills to form the columns
        skills = list(Skill.objects.filter(tenant=request.tenant, is_active=True).order_by("category__name", "name").values("id", "name", "category__name"))
        
        # 2. Prefetch employee skills to prevent N+1 queries
        employee_skills_prefetch = Prefetch(
            "skills",
            queryset=EmployeeSkill.objects.filter(tenant=request.tenant, is_active=True).select_related("skill")
        )
        
        # 3. Query employees with the prefetch applied
        employees = Employee.objects.filter(
            tenant=request.tenant, 
            is_active=True
        ).prefetch_related(employee_skills_prefetch)
        
        # 4. Build the matrix in memory with O(N) traversal
        matrix = []
        for emp in employees:
            emp_data = {
                "employee_id": emp.id,
                "name": emp.full_name,
                "skills": {}
            }
            # Since skills are prefetched, this loop generates NO database queries
            for emp_skill in emp.skills.all():
                emp_data["skills"][str(emp_skill.skill.id)] = {
                    "level": emp_skill.level,
                    "target_level": emp_skill.target_level
                }
            matrix.append(emp_data)
            
        return Response({
            "columns": skills,
            "rows": matrix
        })


class EmployeeSkillViewSet(SkillsBaseViewSet):
    serializer_class = EmployeeSkillSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["employee", "skill", "level"]
    
    def get_queryset(self):
        return EmployeeSkill.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        emp_skill = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        emp_skill.sync_to_shared_action()

    def perform_update(self, serializer):
        emp_skill = serializer.save()
        emp_skill.sync_to_shared_action()


class TrainingSessionViewSet(SkillsBaseViewSet):
    serializer_class = TrainingSessionSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["skill", "trainer"]
    search_fields = ["title"]
    ordering_fields = ["date"]

    def get_queryset(self):
        return TrainingSession.objects.filter(tenant=self.request.tenant, is_active=True)


class CertificationViewSet(SkillsBaseViewSet):
    serializer_class = CertificationSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["employee"]
    search_fields = ["name"]
    ordering_fields = ["expiry_date"]

    def get_queryset(self):
        return Certification.objects.filter(tenant=self.request.tenant, is_active=True)
