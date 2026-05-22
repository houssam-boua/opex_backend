# modules/audits/views.py
"""
Audits Module — ViewSets
All views: BelongsToTenant + ModuleIsActive(module_name="audits")
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import AuditType, AuditPlan, Audit, AuditChecklistItem, Finding
from .serializers import (
    AuditTypeSerializer, AuditPlanSerializer,
    AuditListSerializer, AuditDetailSerializer,
    AuditCreateSerializer, AuditUpdateSerializer,
    AuditChecklistItemSerializer,
    FindingListSerializer, FindingDetailSerializer, FindingCreateSerializer,
)


def _request_employee(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee or employee.tenant_id != request.tenant.id:
        raise PermissionDenied("Aucun Employee valide n'est lie a cet utilisateur.")
    return employee


class _AuditsBaseViewSet(viewsets.ModelViewSet):
    """Mixin — tenant isolation + module gating for all audit views."""
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name        = "audits"

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.tenant,
            created_by=self.request.user,
        )


# ─── Reference Data ─────────────────────────────────────────────────

class AuditTypeViewSet(_AuditsBaseViewSet):
    serializer_class = AuditTypeSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter]
    search_fields    = ["name"]
    filterset_fields = ["kind", "is_active"]

    def get_queryset(self):
        return AuditType.objects.filter(tenant=self.request.tenant)


# ─── Audit Plans ─────────────────────────────────────────────────────

class AuditPlanViewSet(_AuditsBaseViewSet):
    serializer_class = AuditPlanSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["audit_type", "frequency", "year", "is_active"]
    search_fields    = ["title"]
    ordering_fields  = ["year", "title", "created_at"]

    def get_queryset(self):
        return AuditPlan.objects.filter(
            tenant=self.request.tenant
        ).select_related("audit_type", "responsible")


# ─── Audits ──────────────────────────────────────────────────────────

class AuditViewSet(_AuditsBaseViewSet):
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["audit_type", "status", "priority", "lead_auditor", "plan"]
    search_fields    = ["title", "reference", "description", "zone"]
    ordering_fields  = ["planned_date", "actual_date", "status", "created_at"]
    ordering         = ["-planned_date"]

    def get_queryset(self):
        return Audit.objects.filter(
            tenant=self.request.tenant
        ).select_related("audit_type", "lead_auditor", "auditee", "plan", "created_by")

    def get_serializer_class(self):
        if self.action == "list":
            return AuditListSerializer
        if self.action == "create":
            return AuditCreateSerializer
        if self.action in ("update", "partial_update"):
            return AuditUpdateSerializer
        return AuditDetailSerializer

    @action(detail=True, methods=["post"])
    def start_audit(self, request, pk=None):
        audit = self.get_object()
        if audit.status != "planned":
            return Response({"error": "Cet audit ne peut pas être démarré."}, status=400)
        audit.status      = "in_progress"
        audit.actual_date = timezone.now().date()
        audit.save(update_fields=["status", "actual_date", "updated_at"])
        return Response(AuditDetailSerializer(audit).data)

    @action(detail=True, methods=["post"])
    def complete_audit(self, request, pk=None):
        audit = self.get_object()
        if audit.status != "in_progress":
            return Response({"error": "Cet audit ne peut pas être terminé."}, status=400)
        audit.status       = "completed"
        audit.score        = request.data.get("score", audit.score)
        audit.conclusion   = request.data.get("conclusion", "")
        audit.completed_at = timezone.now()
        audit.save(update_fields=["status", "score", "conclusion", "completed_at", "updated_at"])
        return Response(AuditDetailSerializer(audit).data)

    @action(detail=True, methods=["post"])
    def close_audit(self, request, pk=None):
        audit = self.get_object()
        if audit.status != "completed":
            return Response({"error": "Cet audit ne peut pas être clôturé."}, status=400)
        open_findings = audit.findings.exclude(status="closed").count()
        if open_findings > 0:
            return Response(
                {"error": f"{open_findings} constat(s) encore ouvert(s). Clôturez-les d'abord."},
                status=400,
            )
        audit.status    = "closed"
        audit.closed_at = timezone.now()
        audit.save(update_fields=["status", "closed_at", "updated_at"])
        return Response(AuditDetailSerializer(audit).data)

    @action(detail=False, methods=["get"])
    def statistics(self, request):
        qs = self.get_queryset()
        total = qs.count()
        by_status = dict(qs.values_list("status").annotate(c=Count("id")))
        by_type   = list(
            qs.values("audit_type__name").annotate(count=Count("id")).order_by("-count")[:10]
        )
        findings_total = Finding.objects.filter(
            tenant=request.tenant
        ).count()
        findings_open = Finding.objects.filter(
            tenant=request.tenant
        ).exclude(status="closed").count()
        return Response({
            "total": total, "by_status": by_status, "by_type": by_type,
            "findings_total": findings_total, "findings_open": findings_open,
        })


# ─── Checklist Items ─────────────────────────────────────────────────

class AuditChecklistItemViewSet(_AuditsBaseViewSet):
    serializer_class = AuditChecklistItemSerializer
    filter_backends  = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["audit", "rating", "category"]
    ordering_fields  = ["order"]

    def get_queryset(self):
        return AuditChecklistItem.objects.filter(
            tenant=self.request.tenant
        ).select_related("audit")


# ─── Findings ────────────────────────────────────────────────────────

class FindingViewSet(_AuditsBaseViewSet):
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["audit", "severity", "status", "assigned_to"]
    search_fields    = ["title", "description", "clause_reference"]
    ordering_fields  = ["created_at", "due_date", "severity"]
    ordering         = ["-created_at"]

    def get_queryset(self):
        return Finding.objects.filter(
            tenant=self.request.tenant
        ).select_related("audit", "assigned_to", "verified_by", "created_by")

    def get_serializer_class(self):
        if self.action == "list":
            return FindingListSerializer
        if self.action == "create":
            return FindingCreateSerializer
        return FindingDetailSerializer

    @action(detail=False, methods=["get"])
    def my_findings(self, request):
        qs = self.get_queryset().filter(assigned_to=_request_employee(request))
        return Response(FindingListSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def overdue(self, request):
        qs = self.get_queryset().filter(
            due_date__lt=timezone.now().date()
        ).exclude(status="closed")
        return Response(FindingListSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        finding = self.get_object()
        resolution = request.data.get("resolution")
        if not resolution:
            return Response({"error": "Une résolution est requise."}, status=400)
        finding.status      = "pending_review"
        finding.resolution  = resolution
        finding.resolved_at = timezone.now()
        finding.save(update_fields=["status", "resolution", "resolved_at", "updated_at"])
        return Response(FindingDetailSerializer(finding).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        finding = self.get_object()
        if finding.status != "pending_review":
            return Response({"error": "Vérification impossible."}, status=400)
        finding.status      = "closed"
        finding.verified_by = _request_employee(request)
        finding.verified_at = timezone.now()
        finding.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
        return Response(FindingDetailSerializer(finding).data)
