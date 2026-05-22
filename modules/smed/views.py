from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from core.permissions import BelongsToTenant, ModuleIsActive
from .models import SMEDSession, SMEDStep
from .serializers import SMEDSessionSerializer, SMEDStepSerializer
from .services import SMEDService


class SMEDSessionViewSet(viewsets.ModelViewSet):
    serializer_class = SMEDSessionSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "smed"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["machine", "status", "observed_by", "validated_by", "date_observed"]
    search_fields = ["product_before", "product_after", "notes"]
    ordering_fields = ["date_observed", "created_at", "total_time_before", "improvement_pct"]
    ordering = ["-date_observed", "-created_at"]

    def get_queryset(self):
        return SMEDSession.objects.filter(
            tenant=self.request.tenant,
            is_deleted=False,
        ).select_related("machine", "observed_by", "validated_by", "created_by")

    def perform_create(self, serializer):
        SMEDService.create_session(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_destroy(self, instance):
        SMEDService.delete_session(instance, user=self.request.user)

    def perform_update(self, serializer):
        SMEDService.update_session(serializer)

    @action(detail=True, methods=["post"])
    def recalculate(self, request, pk=None):
        session = SMEDService.recalculate_session_metrics(self.get_object())
        serializer = self.get_serializer(session)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        session = SMEDService.approve_session(self.get_object(), request.user)
        serializer = self.get_serializer(session)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        session = SMEDService.unlock_session(self.get_object(), request.user)
        serializer = self.get_serializer(session)
        return Response(serializer.data)


class SMEDStepViewSet(viewsets.ModelViewSet):
    serializer_class = SMEDStepSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "smed"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["session", "step_type", "can_externalise", "is_optimised", "operator"]
    search_fields = ["description", "notes"]
    ordering_fields = ["order", "duration_before_sec", "duration_after_sec", "created_at"]
    ordering = ["session", "order"]

    def get_queryset(self):
        return SMEDStep.objects.filter(
            tenant=self.request.tenant,
            is_deleted=False,
        ).select_related("session", "operator", "created_by")

    def perform_create(self, serializer):
        SMEDService.save_step(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        SMEDService.save_step(serializer)

    def perform_destroy(self, instance):
        SMEDService.delete_step(instance, user=self.request.user)


class SMEDDashboardView(APIView):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "smed"

    def get(self, request):
        return Response(SMEDService.dashboard_metrics(request.tenant))
