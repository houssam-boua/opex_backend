from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import SFMEscalation, SFMKPI, SFMSession
from .serializers import SFMEscalationSerializer, SFMKPISerializer, SFMSessionSerializer
from .services import SFMService


class SFMSessionViewSet(viewsets.ModelViewSet):
    serializer_class = SFMSessionSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "sfm"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["date", "line", "tier_level", "status", "facilitated_by"]
    search_fields = ["line", "notes"]
    ordering_fields = ["date", "line", "tier_level", "meeting_duration_min", "created_at"]
    ordering = ["-date", "line", "tier_level"]

    def get_queryset(self):
        return SFMSession.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("facilitated_by", "created_by").prefetch_related("participants")

    def perform_create(self, serializer):
        SFMService.create_session(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        SFMService.update_session(serializer)

    def perform_destroy(self, instance):
        SFMService.delete_session(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def evaluate_session(self, request, pk=None):
        session = SFMService.evaluate_session(self.get_object())
        return Response(self.get_serializer(session).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        session = SFMService.complete_session(self.get_object())
        return Response(self.get_serializer(session).data)


class SFMKPIViewSet(viewsets.ModelViewSet):
    serializer_class = SFMKPISerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "sfm"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["session", "category", "color_status", "owner", "requires_action"]
    search_fields = ["kpi_name", "objective_description", "comment"]
    ordering_fields = ["category", "kpi_name", "target", "actual", "created_at"]
    ordering = ["session", "category", "kpi_name"]

    def get_queryset(self):
        return SFMKPI.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("session", "owner", "linked_action", "created_by")

    def perform_create(self, serializer):
        SFMService.save_kpi(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        SFMService.save_kpi(serializer)

    def perform_destroy(self, instance):
        SFMService.delete_kpi(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def evaluate(self, request, pk=None):
        kpi = SFMService.evaluate_kpi(self.get_object())
        SFMService.evaluate_session(kpi.session)
        return Response(self.get_serializer(kpi).data)

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        kpi = self.get_object()
        employee = getattr(request, "employee", None) or SFMService.employee_for_user(
            request.user,
            self.request.tenant.id,
        )
        escalation = SFMService.escalate_kpi(
            kpi,
            request.data.get("target_tier"),
            employee,
            request.data.get("reason", ""),
        )
        serializer = SFMEscalationSerializer(escalation, context=self.get_serializer_context())
        return Response(serializer.data)


class SFMEscalationViewSet(viewsets.ModelViewSet):
    serializer_class = SFMEscalationSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "sfm"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["session", "kpi", "status", "escalated_to_tier", "escalated_by"]
    search_fields = ["reason", "kpi__kpi_name"]
    ordering_fields = ["created_at", "resolved_at", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return SFMEscalation.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("session", "kpi", "escalated_by", "resolved_by", "created_by")

    def perform_create(self, serializer):
        SFMService.create_escalation_from_serializer(serializer, self.request.user)

    def perform_update(self, serializer):
        SFMService.update_escalation(serializer, self.request.user)

    def perform_destroy(self, instance):
        SFMService.delete_escalation(instance, user=self.request.user)


class SFMDashboardView(APIView):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "sfm"

    def get(self, request):
        return Response(SFMService.dashboard_metrics(request.tenant))
