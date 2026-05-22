# modules/iso9001/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Avg
from django.db.models.functions import TruncMonth

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import (
    ISO9001Clause, ComplianceAssessment, NonConformity, CorrectiveAction, ISODocument,
    ISO9001EvaluationSession, ISO9001Question, ISO9001Response
)
from .serializers import (
    ISO9001ClauseSerializer, ComplianceAssessmentSerializer, NonConformitySerializer,
    CorrectiveActionSerializer, ISODocumentSerializer,
    ISO9001EvaluationSessionSerializer, ISO9001QuestionSerializer, ISO9001ResponseSerializer
)
from .services import ISO9001Service

class ISOBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "iso9001"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        
    def perform_destroy(self, instance):
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()


class ISO9001ClauseViewSet(ISOBaseViewSet):
    serializer_class = ISO9001ClauseSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["parent"]
    search_fields = ["clause_number", "title"]
    ordering_fields = ["clause_number"]
    ordering = ["clause_number"]

    def get_queryset(self):
        return ISO9001Clause.objects.filter(tenant=self.request.tenant, is_active=True)


class ComplianceAssessmentViewSet(ISOBaseViewSet):
    serializer_class = ComplianceAssessmentSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["clause", "status", "assessor"]
    ordering_fields = ["date"]

    def get_queryset(self):
        return ComplianceAssessment.objects.filter(tenant=self.request.tenant, is_active=True)

    @action(detail=False, methods=["get"])
    def analytics(self, request):
        """
        Analytics Endpoint
        GET /api/v1/iso9001/assessments/analytics/
        """
        tenant = request.tenant
        
        # Calculate scores
        scores = ISO9001Service.calculate_compliance(tenant)
        
        # open_non_conformities_count
        open_nc_count = NonConformity.objects.filter(
            tenant=tenant, 
            status__in=[NonConformity.Status.OPEN, NonConformity.Status.IN_REVIEW],
            is_active=True
        ).count()
        
        # trend_last_6_months
        six_months_ago = timezone.now() - timedelta(days=180)
        trend = list(ComplianceAssessment.objects.filter(tenant=tenant, is_active=True, created_at__gte=six_months_ago).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            avg_score=Avg('score')
        ).order_by('month'))
        
        return Response({
            "overall_compliance_score": scores["overall_compliance_score"],
            "compliance_by_clause": scores["compliance_by_clause"],
            "open_non_conformities_count": open_nc_count,
            "trend_last_6_months": trend
        })


class NonConformityViewSet(ISOBaseViewSet):
    serializer_class = NonConformitySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["clause", "severity", "status", "detected_by"]
    search_fields = ["description"]
    ordering_fields = ["detected_at", "severity"]

    def get_queryset(self):
        return NonConformity.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        nc = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        # Decoupled CAPA Trigger via Signals
        ISO9001Service.trigger_capa_if_needed(nc)


class CorrectiveActionViewSet(ISOBaseViewSet):
    serializer_class = CorrectiveActionSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["non_conformity", "status", "owner"]
    ordering_fields = ["deadline"]

    def get_queryset(self):
        return CorrectiveAction.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        ca = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        ca.sync_to_shared_action()

    def perform_update(self, serializer):
        ca = serializer.save()
        ca.sync_to_shared_action()


class ISODocumentViewSet(ISOBaseViewSet):
    serializer_class = ISODocumentSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["clause", "uploaded_by"]
    search_fields = ["title", "version"]
    ordering_fields = ["valid_from", "valid_until"]

    def get_queryset(self):
        return ISODocument.objects.filter(tenant=self.request.tenant, is_active=True)


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY BRIDGE — ViewSets
# ═══════════════════════════════════════════════════════════════════════

class ISO9001EvaluationSessionViewSet(ISOBaseViewSet):
    serializer_class = ISO9001EvaluationSessionSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "evaluator"]
    search_fields = ["title"]
    ordering_fields = ["created_at", "global_score"]

    def get_queryset(self):
        return ISO9001EvaluationSession.objects.filter(tenant=self.request.tenant, is_active=True)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """
        POST /api/v1/iso9001/sessions/{id}/complete/
        Triggers the Session Score Engine in services.py.
        """
        session = self.get_object()
        completed_session = ISO9001Service.complete_session(session)
        return Response(self.get_serializer(completed_session).data)


class ISO9001QuestionViewSet(ISOBaseViewSet):
    serializer_class = ISO9001QuestionSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["clause"]
    search_fields = ["question_text"]
    ordering_fields = ["clause__clause_number"]

    def get_queryset(self):
        return ISO9001Question.objects.filter(tenant=self.request.tenant, is_active=True)


class ISO9001ResponseViewSet(ISOBaseViewSet):
    serializer_class = ISO9001ResponseSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["session", "question", "response_status"]

    def get_queryset(self):
        return ISO9001Response.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        response = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        # NC Bridge: auto-generate NonConformity for non-compliant responses
        ISO9001Service.process_response_nc_bridge(response)

    def perform_update(self, serializer):
        response = serializer.save()
        # Re-evaluate NC bridge on update (e.g., status changed to non_compliant)
        ISO9001Service.process_response_nc_bridge(response)
