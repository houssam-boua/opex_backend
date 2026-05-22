from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import (
    RotationAssignment,
    RotationIncident,
    RotationPlan,
    RotationRule,
    RotationSlot,
    RotationViolation,
    Workstation,
)
from .serializers import (
    RotationAssignmentSerializer,
    RotationIncidentSerializer,
    RotationPlanSerializer,
    RotationRuleSerializer,
    RotationSlotSerializer,
    RotationViolationSerializer,
    WorkstationSerializer,
)
from .services import RotationService


class RotationPlanViewSet(viewsets.ModelViewSet):
    serializer_class = RotationPlanSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["date", "department", "line", "shift", "status", "created_by_employee"]
    search_fields = ["name", "line", "notes"]
    ordering_fields = ["date", "shift", "status", "created_at"]
    ordering = ["-date", "shift"]

    def get_queryset(self):
        return RotationPlan.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("department", "created_by_employee", "approved_by", "created_by")

    def perform_create(self, serializer):
        employee = None
        try:
            employee = RotationService.employee_for_user(self.request.user, self.request.tenant.id)
        except Exception:
            employee = None
        RotationService.create_plan(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
            created_by_employee=serializer.validated_data.get("created_by_employee") or employee,
        )

    def perform_update(self, serializer):
        RotationService.update_plan(serializer)

    def perform_destroy(self, instance):
        RotationService.delete_plan(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def validate_plan(self, request, pk=None):
        return Response(RotationService.validate_plan(self.get_object()))

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        employee = RotationService.employee_for_user(request.user, request.tenant.id)
        plan = RotationService.publish_plan(self.get_object(), employee)
        return Response(self.get_serializer(plan).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        plan = RotationService.complete_plan(self.get_object())
        return Response(self.get_serializer(plan).data)


class WorkstationViewSet(viewsets.ModelViewSet):
    serializer_class = WorkstationSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["department", "line", "risk_level", "is_critical", "required_skill"]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["name", "code", "risk_level", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        return Workstation.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("department", "required_skill", "created_by")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        RotationService.soft_delete(instance, user=self.request.user)


class RotationSlotViewSet(viewsets.ModelViewSet):
    serializer_class = RotationSlotSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["plan", "start_time", "end_time"]
    search_fields = ["plan__name"]
    ordering_fields = ["plan", "order", "start_time", "created_at"]
    ordering = ["plan", "order"]

    def get_queryset(self):
        return RotationSlot.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("plan", "created_by")

    def perform_create(self, serializer):
        RotationService.save_slot(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        RotationService.save_slot(serializer)

    def perform_destroy(self, instance):
        RotationService.delete_slot(instance, user=self.request.user)


class RotationAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = RotationAssignmentSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["plan", "slot", "employee", "workstation", "status"]
    search_fields = ["employee__first_name", "employee__last_name", "workstation__name", "comment"]
    ordering_fields = ["plan", "slot", "employee", "workstation", "status", "created_at"]
    ordering = ["plan", "slot__order", "workstation__name"]

    def get_queryset(self):
        return RotationAssignment.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("plan", "slot", "employee", "workstation", "replacement_for", "created_by")

    def perform_create(self, serializer):
        RotationService.save_assignment(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        RotationService.save_assignment(serializer)

    def perform_destroy(self, instance):
        RotationService.delete_assignment(instance, user=self.request.user)


class RotationRuleViewSet(viewsets.ModelViewSet):
    serializer_class = RotationRuleSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["rule_type", "severity", "is_enabled"]
    search_fields = ["name", "description"]
    ordering_fields = ["rule_type", "severity", "created_at"]
    ordering = ["rule_type", "name"]

    def get_queryset(self):
        return RotationRule.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("created_by")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        RotationService.soft_delete(instance, user=self.request.user)


class RotationViolationViewSet(viewsets.ModelViewSet):
    serializer_class = RotationViolationSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["plan", "assignment", "rule", "severity", "resolved"]
    search_fields = ["message", "assignment__employee__first_name", "assignment__employee__last_name"]
    ordering_fields = ["severity", "resolved", "created_at", "resolved_at"]
    ordering = ["resolved", "-created_at"]

    def get_queryset(self):
        return RotationViolation.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("plan", "assignment", "assignment__employee", "assignment__workstation", "rule", "resolved_by", "linked_action", "created_by")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        RotationService.soft_delete(instance, user=self.request.user)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        employee = RotationService.employee_for_user(request.user, request.tenant.id)
        violation = RotationService.resolve_violation(self.get_object(), employee)
        return Response(self.get_serializer(violation).data)


class RotationIncidentViewSet(viewsets.ModelViewSet):
    serializer_class = RotationIncidentSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["plan", "assignment", "reported_by", "severity", "resolved"]
    search_fields = ["title", "description"]
    ordering_fields = ["occurred_at", "severity", "resolved", "created_at"]
    ordering = ["-occurred_at"]

    def get_queryset(self):
        return RotationIncident.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("plan", "assignment", "reported_by", "linked_action", "created_by")

    def perform_create(self, serializer):
        reported_by = serializer.validated_data.get("reported_by")
        if not reported_by:
            reported_by = RotationService.employee_for_user(self.request.user, self.request.tenant.id)
        RotationService.save_incident(
            serializer,
            tenant=self.request.tenant,
            created_by=self.request.user,
            reported_by=reported_by,
        )

    def perform_update(self, serializer):
        RotationService.save_incident(serializer)

    def perform_destroy(self, instance):
        RotationService.soft_delete(instance, user=self.request.user)


class RotationDashboardView(APIView):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "rotation"

    def get(self, request):
        return Response(RotationService.calculate_rotation_analytics(request.tenant))
