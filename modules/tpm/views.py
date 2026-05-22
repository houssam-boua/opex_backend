# modules/tpm/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from core.permissions import BelongsToTenant, ModuleIsActive
from .models import (
    Machine, ProductionReport, Breakdown, MaintenanceTask,
    Intervention, ChecklistExecution, Kaizen
)
from .serializers import (
    MachineSerializer, ProductionReportSerializer, BreakdownSerializer,
    MaintenanceTaskSerializer, InterventionSerializer, 
    ChecklistExecutionSerializer, KaizenSerializer
)
from .services import TPMService


class TPMBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "tpm"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        
    def perform_destroy(self, instance):
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()


class MachineViewSet(TPMBaseViewSet):
    serializer_class = MachineSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["etat", "emplacement"]
    search_fields = ["code", "nom"]
    ordering_fields = ["code"]

    def get_queryset(self):
        return Machine.objects.filter(
            tenant=self.request.tenant
        ).select_related("created_by")


class ProductionReportViewSet(TPMBaseViewSet):
    serializer_class = ProductionReportSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["machine", "operateur", "est_valide"]
    ordering_fields = ["date"]

    @action(detail=True, methods=["get"])
    def kpi(self, request, pk=None):
        """
        Uses services.py to compute KPI safely.
        """
        report = self.get_object()
        # Ensure we safely calculate OEE (Rule: ALL KPI in services.py ONLY)
        temps_perdu = report.temps_ouverture * 60 - (report.qte_produite / max(1, report.machine.cadence_theorique) * 60)
        # Simplified for example
        kpis = TPMService.calculate_kpis(
            temps_ouverture_heures=report.temps_ouverture,
            temps_perdu_minutes=max(0, float(temps_perdu)),
            qte_produite=report.qte_produite,
            cadence_theorique=report.machine.cadence_theorique,
            qte_rebut=report.qte_rebut
        )
        return Response(kpis)


class BreakdownViewSet(TPMBaseViewSet):
    serializer_class = BreakdownSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["machine", "statut", "technicien", "operateur"]
    ordering_fields = ["date_declaration"]

    def perform_create(self, serializer):
        breakdown = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        breakdown.sync_to_shared_action()

    # Workflow Actions (Delegating logic to TPMService)
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        technicien_id = request.data.get("technicien_id")
        from accounts.models import Employee
        technicien = Employee.objects.get(id=technicien_id, tenant=request.tenant)
        breakdown = TPMService.assign_breakdown(self.get_object(), technicien)
        return Response(self.get_serializer(breakdown).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        breakdown = TPMService.start_intervention(self.get_object())
        return Response(self.get_serializer(breakdown).data)

    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        cause_racine = request.data.get("cause_racine", "")
        actions_correctives = request.data.get("actions_correctives", "")
        breakdown = TPMService.finish_intervention(self.get_object(), cause_racine, actions_correctives)
        return Response(self.get_serializer(breakdown).data)

    @action(detail=True, methods=["post"])
    def validate_breakdown(self, request, pk=None):
        employee = getattr(request.user, "employee_profile", None)
        breakdown = TPMService.validate_breakdown(self.get_object(), employee)
        return Response(self.get_serializer(breakdown).data)


class MaintenanceTaskViewSet(TPMBaseViewSet):
    serializer_class = MaintenanceTaskSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["machine", "statut", "type_tache", "technicien"]
    ordering_fields = ["deadline"]

    def perform_create(self, serializer):
        task = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        task.sync_to_shared_action()

    def perform_update(self, serializer):
        task = serializer.save()
        task.sync_to_shared_action()


class InterventionViewSet(TPMBaseViewSet):
    serializer_class = InterventionSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["panne", "status", "technicien"]
    ordering_fields = ["start_time"]

    def get_queryset(self):
        return Intervention.objects.filter(
            tenant=self.request.tenant
        ).select_related("created_by")


class ChecklistViewSet(TPMBaseViewSet):
    # Mapping to ChecklistExecution for the frontend interaction
    serializer_class = ChecklistExecutionSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["intervention", "completed"]

    def get_queryset(self):
        return ChecklistExecution.objects.filter(
            tenant=self.request.tenant
        ).select_related("created_by")


class KaizenViewSet(TPMBaseViewSet):
    serializer_class = KaizenSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["machine", "statut", "priorite", "auteur"]
    ordering_fields = ["created_at"]

    def perform_create(self, serializer):
        kaizen = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        kaizen.sync_to_shared_action()

    def perform_update(self, serializer):
        kaizen = serializer.save()
        kaizen.sync_to_shared_action()
