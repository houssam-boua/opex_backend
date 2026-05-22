from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import (
    RoutineDeviation,
    RoutineExecution,
    RoutineStep,
    RoutineStepResponse,
    RoutineTemplate,
)
from .serializers import (
    RoutineDeviationSerializer,
    RoutineExecutionSerializer,
    RoutineStepResponseSerializer,
    RoutineStepSerializer,
    RoutineTemplateSerializer,
)
from .services import RoutineService


class RoutineTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = RoutineTemplateSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "routines"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "routine_type", "frequency", "department", "owner", "is_mandatory"]
    search_fields = ["code", "title", "description", "line", "workstation_name"]
    ordering_fields = ["title", "code", "frequency", "status", "created_at", "updated_at"]
    ordering = ["title"]

    def get_queryset(self):
        return RoutineTemplate.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("department", "owner", "created_by")

    def perform_create(self, serializer):
        RoutineService.create_template(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        RoutineService.update_template(serializer)

    def perform_destroy(self, instance):
        RoutineService.soft_delete(instance, user=self.request.user)


class RoutineStepViewSet(viewsets.ModelViewSet):
    serializer_class = RoutineStepSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "routines"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["template", "step_type", "is_required", "is_ok_demarrage"]
    search_fields = ["title", "description", "expected_value", "template__title"]
    ordering_fields = ["template", "order", "step_type", "created_at"]
    ordering = ["template", "order"]

    def get_queryset(self):
        return RoutineStep.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("template", "created_by")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        RoutineService.soft_delete(instance, user=self.request.user)


class RoutineExecutionViewSet(viewsets.ModelViewSet):
    serializer_class = RoutineExecutionSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "routines"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["template", "executed_by", "status", "shift", "global_result"]
    search_fields = ["template__title", "template__code", "notes", "validator_comment"]
    ordering_fields = ["scheduled_for", "started_at", "completed_at", "status", "created_at"]
    ordering = ["-scheduled_for"]

    def get_queryset(self):
        return RoutineExecution.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("template", "executed_by", "validated_by", "created_by")

    def perform_create(self, serializer):
        RoutineService.create_execution(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        RoutineService.soft_delete(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        employee = RoutineService.employee_for_user(request.user, request.tenant.id)
        execution = RoutineService.start_execution(self.get_object(), employee)
        return Response(self.get_serializer(execution).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        execution = RoutineService.complete_execution(self.get_object())
        return Response(self.get_serializer(execution).data)


class RoutineStepResponseViewSet(viewsets.ModelViewSet):
    serializer_class = RoutineStepResponseSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "routines"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["execution", "step", "result", "responded_by"]
    search_fields = ["step__title", "comment", "value_text"]
    ordering_fields = ["responded_at", "result", "created_at"]
    ordering = ["step__order"]

    def get_queryset(self):
        return RoutineStepResponse.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("execution", "execution__template", "step", "responded_by", "linked_action", "created_by")

    def perform_create(self, serializer):
        save_kwargs = {"tenant": self.request.tenant, "created_by": self.request.user}
        if not serializer.validated_data.get("responded_by"):
            try:
                save_kwargs["responded_by"] = RoutineService.employee_for_user(self.request.user, self.request.tenant.id)
            except Exception:
                pass
        RoutineService.save_response(serializer, **save_kwargs)

    def perform_update(self, serializer):
        RoutineService.save_response(serializer)

    def perform_destroy(self, instance):
        RoutineService.soft_delete(instance, user=self.request.user)


class RoutineDeviationViewSet(viewsets.ModelViewSet):
    serializer_class = RoutineDeviationSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "routines"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["execution", "response", "severity", "status", "owner", "detected_by"]
    search_fields = ["title", "description", "execution__template__title"]
    ordering_fields = ["severity", "status", "due_date", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return RoutineDeviation.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("execution", "execution__template", "response", "detected_by", "owner", "verified_by", "linked_action", "created_by")

    def perform_create(self, serializer):
        save_kwargs = {"tenant": self.request.tenant, "created_by": self.request.user}
        if not serializer.validated_data.get("detected_by"):
            try:
                save_kwargs["detected_by"] = RoutineService.employee_for_user(self.request.user, self.request.tenant.id)
            except Exception:
                pass
        RoutineService.save_deviation(serializer, **save_kwargs)

    def perform_update(self, serializer):
        RoutineService.save_deviation(serializer)

    def perform_destroy(self, instance):
        RoutineService.soft_delete(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        employee = RoutineService.employee_for_user(request.user, request.tenant.id)
        deviation = RoutineService.verify_deviation(self.get_object(), employee)
        return Response(self.get_serializer(deviation).data)


class RoutineDashboardView(APIView):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "routines"

    def get(self, request):
        return Response(RoutineService.dashboard_metrics(request.tenant))
