from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import PokaYokeCheck, PokaYokeDefect, PokaYokeDevice, PokaYokeImprovement
from .serializers import (
    PokaYokeCheckSerializer,
    PokaYokeDefectSerializer,
    PokaYokeDeviceSerializer,
    PokaYokeImprovementSerializer,
)
from .services import PokaYokeService


class PokaYokeDeviceViewSet(viewsets.ModelViewSet):
    serializer_class = PokaYokeDeviceSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "poka_yoke"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "device_type", "criticality", "department", "machine", "owner"]
    search_fields = ["name", "code", "description", "failure_mode", "prevention_method", "workstation_name", "process_name"]
    ordering_fields = ["name", "status", "criticality", "installed_date", "next_verification_due", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        return PokaYokeDevice.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("department", "machine", "owner", "created_by")

    def perform_create(self, serializer):
        PokaYokeService.create_device(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        PokaYokeService.update_device(serializer)

    def perform_destroy(self, instance):
        PokaYokeService.soft_delete(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        device = self.get_object()
        data = request.data.copy()
        data["device"] = str(device.id)
        data.setdefault("checked_at", timezone.now())
        if not data.get("checked_by"):
            try:
                data["checked_by"] = str(PokaYokeService.employee_for_user(request.user, request.tenant.id).id)
            except Exception:
                pass
        serializer = PokaYokeCheckSerializer(data=data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        check = PokaYokeService.save_check(
            serializer,
            tenant=request.tenant,
            created_by=request.user,
        )
        return Response(PokaYokeCheckSerializer(check, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        device = self.get_object()
        checks = PokaYokeCheck.objects.filter(
            tenant=request.tenant,
            device=device,
            is_active=True,
            is_deleted=False,
        )
        defects = PokaYokeDefect.objects.filter(
            tenant=request.tenant,
            device=device,
            is_active=True,
            is_deleted=False,
        )
        improvements = PokaYokeImprovement.objects.filter(
            tenant=request.tenant,
            device=device,
            is_active=True,
            is_deleted=False,
        )
        return Response({
            "checks": PokaYokeCheckSerializer(checks, many=True, context=self.get_serializer_context()).data,
            "defects": PokaYokeDefectSerializer(defects, many=True, context=self.get_serializer_context()).data,
            "improvements": PokaYokeImprovementSerializer(improvements, many=True, context=self.get_serializer_context()).data,
        })


class PokaYokeCheckViewSet(viewsets.ModelViewSet):
    serializer_class = PokaYokeCheckSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "poka_yoke"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["device", "checked_by", "result", "requires_action"]
    search_fields = ["observation", "measured_value", "expected_value", "device__name"]
    ordering_fields = ["checked_at", "result", "created_at"]
    ordering = ["-checked_at"]

    def get_queryset(self):
        return PokaYokeCheck.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("device", "checked_by", "linked_action", "created_by")

    def perform_create(self, serializer):
        PokaYokeService.save_check(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        PokaYokeService.save_check(serializer)

    def perform_destroy(self, instance):
        PokaYokeService.soft_delete(instance, user=self.request.user)


class PokaYokeDefectViewSet(viewsets.ModelViewSet):
    serializer_class = PokaYokeDefectSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "poka_yoke"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["device", "severity", "defect_source", "status", "detected_by"]
    search_fields = ["title", "description", "notes", "device__name"]
    ordering_fields = ["detected_at", "severity", "status", "created_at"]
    ordering = ["-detected_at"]

    def get_queryset(self):
        return PokaYokeDefect.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("device", "detected_by", "verified_by", "linked_action", "created_by")

    def perform_create(self, serializer):
        if not serializer.validated_data.get("detected_by"):
            try:
                serializer.validated_data["detected_by"] = PokaYokeService.employee_for_user(self.request.user, self.request.tenant.id)
            except Exception:
                pass
        PokaYokeService.save_defect(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        PokaYokeService.save_defect(serializer)

    def perform_destroy(self, instance):
        PokaYokeService.soft_delete(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def verify_defect(self, request, pk=None):
        employee = PokaYokeService.employee_for_user(request.user, request.tenant.id)
        defect = PokaYokeService.verify_defect(self.get_object(), employee)
        return Response(self.get_serializer(defect).data)


class PokaYokeImprovementViewSet(viewsets.ModelViewSet):
    serializer_class = PokaYokeImprovementSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "poka_yoke"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["device", "defect", "priority", "status", "owner", "proposed_by"]
    search_fields = ["title", "description", "device__name", "defect__title"]
    ordering_fields = ["due_date", "priority", "status", "created_at"]
    ordering = ["due_date", "-created_at"]

    def get_queryset(self):
        return PokaYokeImprovement.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("device", "defect", "proposed_by", "owner", "linked_action", "created_by")

    def perform_create(self, serializer):
        if not serializer.validated_data.get("proposed_by"):
            try:
                serializer.validated_data["proposed_by"] = PokaYokeService.employee_for_user(self.request.user, self.request.tenant.id)
            except Exception:
                pass
        PokaYokeService.save_improvement(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        PokaYokeService.save_improvement(serializer)

    def perform_destroy(self, instance):
        PokaYokeService.soft_delete(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def sync_action(self, request, pk=None):
        improvement = PokaYokeService.sync_improvement_action(self.get_object())
        return Response(self.get_serializer(improvement).data)


class PokaYokeDashboardView(APIView):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "poka_yoke"

    def get(self, request):
        return Response(PokaYokeService.dashboard_metrics(request.tenant))
