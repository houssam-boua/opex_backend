# modules/risk/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Avg, Count
from django.utils import timezone
from datetime import timedelta
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import RiskCategory, Risk, RiskAssessment, RiskMitigationAction
from .serializers import (
    RiskCategorySerializer, RiskSerializer, 
    RiskAssessmentSerializer, RiskMitigationActionSerializer
)
from .services import RiskService


class RiskBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "risk"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        
    def perform_destroy(self, instance):
        # Override destroy to use soft delete
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()


class RiskCategoryViewSet(RiskBaseViewSet):
    serializer_class = RiskCategorySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]

    def get_queryset(self):
        return RiskCategory.objects.filter(tenant=self.request.tenant, is_active=True)


class RiskViewSet(RiskBaseViewSet):
    serializer_class = RiskSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["category", "severity", "status", "owner"]
    search_fields = ["title", "description"]
    ordering_fields = ["risk_score", "created_at"]
    ordering = ["-risk_score"]

    def get_queryset(self):
        return Risk.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        # We rely on the service to compute the initial score
        risk = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        # Assuming initial assessment is done by creator
        employee = getattr(self.request.user, "employee_profile", None)
        if employee:
            RiskService.assess_risk(
                risk=risk,
                likelihood=risk.likelihood,
                impact=risk.impact,
                assessor=employee,
                notes="Initial creation"
            )

    @action(detail=False, methods=["get"])
    def analytics(self, request):
        qs = self.get_queryset()
        
        risks_by_severity = list(qs.values("severity").annotate(count=Count("id")).order_by("severity"))
        
        avg_score_per_category = list(qs.values("category__name").annotate(
            avg_score=Avg("risk_score")
        ).order_by("-avg_score"))
        
        # High risk trend (last 6 months)
        six_months_ago = timezone.now() - timedelta(days=180)
        from django.db.models.functions import TruncMonth
        high_risk_qs = qs.filter(severity__in=[Risk.Severity.HIGH, Risk.Severity.CRITICAL], created_at__gte=six_months_ago)
        high_risk_trend = list(high_risk_qs.annotate(month=TruncMonth("created_at")).values("month").annotate(
            count=Count("id")
        ).order_by("month"))
        
        return Response({
            "risks_by_severity": risks_by_severity,
            "avg_score_per_category": avg_score_per_category,
            "high_risk_trend": high_risk_trend
        })


class RiskAssessmentViewSet(RiskBaseViewSet):
    serializer_class = RiskAssessmentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["risk", "assessor"]

    def get_queryset(self):
        return RiskAssessment.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        risk = serializer.validated_data["risk"]
        assessor = serializer.validated_data["assessor"]
        likelihood = self.request.data.get("likelihood", risk.likelihood)
        impact = self.request.data.get("impact", risk.impact)
        notes = serializer.validated_data.get("notes", "")

        # MUST use service layer
        RiskService.assess_risk(
            risk=risk,
            likelihood=int(likelihood),
            impact=int(impact),
            assessor=assessor,
            notes=notes
        )


class RiskMitigationActionViewSet(RiskBaseViewSet):
    serializer_class = RiskMitigationActionSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["risk", "status", "owner"]

    def get_queryset(self):
        return RiskMitigationAction.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        # Pass through service
        risk = serializer.validated_data["risk"]
        description = serializer.validated_data["description"]
        deadline = serializer.validated_data["deadline"]
        owner = serializer.validated_data.get("owner")
        
        RiskService.add_mitigation_action(
            risk=risk,
            description=description,
            deadline=deadline,
            owner=owner,
            creator=self.request.user
        )

    def perform_update(self, serializer):
        action = serializer.save()
        # Must re-sync on update
        action.sync_to_shared_action()
