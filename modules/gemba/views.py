# modules/gemba/views.py
"""
Gemba Walk Module — ViewSets
All views use BelongsToTenant + ModuleIsActive(module_name="gemba").
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import (
    GembaZone, GembaTeam, GembaCategory,
    Checkpoint, Tour, TourParticipant, ExecutionPoint,
    Anomaly, FaceToFace, FiveSAudit,
)
from .serializers import (
    GembaZoneSerializer, GembaTeamSerializer, GembaCategorySerializer,
    CheckpointSerializer,
    TourListSerializer, TourDetailSerializer, TourCreateSerializer,
    TourUpdateSerializer, TourParticipantSerializer,
    ExecutionPointSerializer, ExecutionPointCreateSerializer,
    AnomalyListSerializer, AnomalyDetailSerializer, AnomalyCreateSerializer,
    FaceToFaceSerializer, FiveSAuditSerializer, CalendarEventSerializer,
)


def _request_employee(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee or employee.tenant_id != request.tenant.id:
        raise PermissionDenied("Aucun Employee valide n'est lie a cet utilisateur.")
    return employee


class _GembaBaseViewSet(viewsets.ModelViewSet):
    """Mixin DRY — tenant isolation + module gating for all Gemba views."""
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name        = "gemba"

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.tenant,
            created_by=self.request.user,
        )


# ─── Reference Data ─────────────────────────────────────────────────

class GembaZoneViewSet(_GembaBaseViewSet):
    serializer_class = GembaZoneSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter]
    search_fields    = ["name", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return GembaZone.objects.filter(tenant=self.request.tenant)


class GembaTeamViewSet(_GembaBaseViewSet):
    serializer_class = GembaTeamSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter]
    search_fields    = ["name"]
    filterset_fields = ["zone", "is_active"]

    def get_queryset(self):
        return GembaTeam.objects.filter(tenant=self.request.tenant).select_related("zone", "leader")


class GembaCategoryViewSet(_GembaBaseViewSet):
    serializer_class = GembaCategorySerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter]
    search_fields    = ["name"]
    filterset_fields = ["type", "is_active"]

    def get_queryset(self):
        return GembaCategory.objects.filter(tenant=self.request.tenant)


# ─── Checkpoints ─────────────────────────────────────────────────────

class CheckpointViewSet(_GembaBaseViewSet):
    serializer_class = CheckpointSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["category", "is_critical", "is_active"]
    search_fields    = ["name", "description"]
    ordering_fields  = ["order", "name"]

    def get_queryset(self):
        return Checkpoint.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).select_related("category")

    @action(detail=False, methods=["get"])
    def by_zone(self, request):
        zone_id = request.query_params.get("zone_id")
        if not zone_id:
            return Response({"error": "zone_id est requis"}, status=status.HTTP_400_BAD_REQUEST)
        qs = self.get_queryset().filter(zones__id=zone_id).order_by("category", "order")
        return Response(CheckpointSerializer(qs, many=True).data)


# ─── Tours (Gemba Walks) ────────────────────────────────────────────

class TourViewSet(_GembaBaseViewSet):
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["zone", "team", "status", "objective", "date"]
    search_fields    = ["title", "description"]
    ordering_fields  = ["date", "created_at", "status"]
    ordering         = ["-date"]

    def get_queryset(self):
        return Tour.objects.filter(
            tenant=self.request.tenant
        ).select_related("zone", "team", "created_by")

    def get_serializer_class(self):
        if self.action == "list":
            return TourListSerializer
        if self.action == "create":
            return TourCreateSerializer
        if self.action in ("update", "partial_update"):
            return TourUpdateSerializer
        return TourDetailSerializer

    @action(detail=False, methods=["get"])
    def calendar(self, request):
        qs = self.get_queryset()
        start = request.query_params.get("start")
        end   = request.query_params.get("end")
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        return Response(CalendarEventSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        tour = self.get_object()
        if tour.status != "planned":
            return Response({"error": "Cette tournée ne peut pas être démarrée."}, status=400)
        tour.status       = "in_progress"
        tour.actual_start = timezone.now()
        tour.save(update_fields=["status", "actual_start", "updated_at"])
        TourParticipant.objects.filter(tour=tour, user=_request_employee(request)).update(
            attended=True, joined_at=timezone.now()
        )
        return Response(TourDetailSerializer(tour).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        tour = self.get_object()
        if tour.status != "in_progress":
            return Response({"error": "Cette tournée ne peut pas être complétée."}, status=400)
        tour.status     = "completed"
        tour.actual_end = timezone.now()
        tour.notes      = request.data.get("notes", "")
        tour.save(update_fields=["status", "actual_end", "notes", "updated_at"])
        return Response(TourDetailSerializer(tour).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        tour = self.get_object()
        if tour.status == "completed":
            return Response({"error": "Une tournée complétée ne peut pas être annulée."}, status=400)
        tour.status = "cancelled"
        tour.save(update_fields=["status", "updated_at"])
        return Response(TourDetailSerializer(tour).data)

    @action(detail=True, methods=["get", "post"])
    def participants(self, request, pk=None):
        tour = self.get_object()
        if request.method == "GET":
            qs = TourParticipant.objects.filter(tour=tour).select_related("user")
            return Response(TourParticipantSerializer(qs, many=True).data)
        data = {**request.data, "tour": tour.id}
        serializer = TourParticipantSerializer(data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant=request.tenant, created_by=request.user)
        return Response(serializer.data, status=201)

    @action(detail=True, methods=["delete"], url_path=r"participants/(?P<user_id>[^/.]+)")
    def remove_participant(self, request, pk=None, user_id=None):
        tour = self.get_object()
        TourParticipant.objects.filter(tour=tour, user_id=user_id).delete()
        return Response(status=204)


# ─── Execution Points ───────────────────────────────────────────────

class ExecutionPointViewSet(_GembaBaseViewSet):
    filter_backends  = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["tour", "checkpoint", "status", "executed_by"]
    ordering_fields  = ["executed_at", "created_at"]

    def get_queryset(self):
        return ExecutionPoint.objects.filter(
            tenant=self.request.tenant
        ).select_related("tour", "checkpoint", "executed_by")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ExecutionPointCreateSerializer
        return ExecutionPointSerializer

    @action(detail=False, methods=["get"])
    def by_tour(self, request):
        tour_id = request.query_params.get("tour_id")
        if not tour_id:
            return Response({"error": "tour_id est requis"}, status=400)
        qs = self.get_queryset().filter(tour_id=tour_id).order_by("checkpoint__order")
        return Response(ExecutionPointSerializer(qs, many=True).data)

    @action(detail=False, methods=["post"])
    def sync(self, request):
        data_list = request.data.get("executions", [])
        results = []
        for item in data_list:
            ser = ExecutionPointCreateSerializer(data=item, context={"request": request})
            if ser.is_valid():
                results.append(ser.save())
        return Response({"synced": len(results), "total": len(data_list)})


# ─── Anomalies ───────────────────────────────────────────────────────

class AnomalyViewSet(_GembaBaseViewSet):
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["category", "severity", "status", "assigned_to"]
    search_fields    = ["title", "description"]
    ordering_fields  = ["created_at", "due_date", "severity", "status"]
    ordering         = ["-created_at"]

    def get_queryset(self):
        return Anomaly.objects.filter(
            tenant=self.request.tenant
        ).select_related("execution_point", "category", "assigned_to", "created_by")

    def get_serializer_class(self):
        if self.action == "list":
            return AnomalyListSerializer
        if self.action == "create":
            return AnomalyCreateSerializer
        return AnomalyDetailSerializer

    @action(detail=False, methods=["get"])
    def my_anomalies(self, request):
        qs = self.get_queryset().filter(assigned_to=_request_employee(request))
        return Response(AnomalyListSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def overdue(self, request):
        qs = self.get_queryset().filter(
            due_date__lt=timezone.now().date(),
            status__in=["todo", "in_progress"],
        )
        return Response(AnomalyListSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def statistics(self, request):
        qs = self.get_queryset()
        total = qs.count()
        by_status   = dict(qs.values_list("status").annotate(c=Count("id")))
        by_severity = dict(qs.values_list("severity").annotate(c=Count("id")))
        by_category = list(
            qs.exclude(category__isnull=True)
            .values("category__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        overdue = qs.filter(
            due_date__lt=timezone.now().date(),
            status__in=["todo", "in_progress"],
        ).count()
        return Response({
            "total": total, "by_status": by_status,
            "by_severity": by_severity, "by_category": by_category,
            "overdue": overdue,
        })

    @action(detail=True, methods=["post"])
    def start_action(self, request, pk=None):
        anomaly = self.get_object()
        if anomaly.status != "todo":
            return Response({"error": "Cette anomalie ne peut pas être démarrée."}, status=400)
        anomaly.status = "in_progress"
        if not anomaly.assigned_to:
            anomaly.assigned_to = _request_employee(request)
        anomaly.save(update_fields=["status", "assigned_to", "updated_at"])
        return Response(AnomalyDetailSerializer(anomaly).data)

    @action(detail=True, methods=["post"])
    def submit_for_validation(self, request, pk=None):
        anomaly = self.get_object()
        resolution = request.data.get("resolution")
        if not resolution:
            return Response({"error": "Une résolution est requise."}, status=400)
        anomaly.status      = "pending_validation"
        anomaly.resolution  = resolution
        anomaly.resolved_by = _request_employee(request)
        anomaly.resolved_at = timezone.now()
        if "resolution_photo" in request.FILES:
            anomaly.resolution_photo = request.FILES["resolution_photo"]
        anomaly.save()
        return Response(AnomalyDetailSerializer(anomaly).data)

    @action(detail=True, methods=["post"])
    def validate_anomaly(self, request, pk=None):
        anomaly = self.get_object()
        if anomaly.status != "pending_validation":
            return Response({"error": "Validation impossible."}, status=400)
        anomaly.status       = "closed"
        anomaly.validated_by = _request_employee(request)
        anomaly.validated_at = timezone.now()
        anomaly.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
        return Response(AnomalyDetailSerializer(anomaly).data)

    @action(detail=True, methods=["post"])
    def reject_anomaly(self, request, pk=None):
        anomaly = self.get_object()
        if anomaly.status != "pending_validation":
            return Response({"error": "Rejet impossible."}, status=400)
        anomaly.status = "in_progress"
        anomaly.save(update_fields=["status", "updated_at"])
        return Response(AnomalyDetailSerializer(anomaly).data)


# ─── Face-to-Face ────────────────────────────────────────────────────

class FaceToFaceViewSet(_GembaBaseViewSet):
    serializer_class = FaceToFaceSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["tour", "operator", "mood", "action_required"]
    search_fields    = ["subject", "feedback"]

    def get_queryset(self):
        return FaceToFace.objects.filter(
            tenant=self.request.tenant
        ).select_related("tour", "operator", "manager")


# ─── 5S Audits ───────────────────────────────────────────────────────

class FiveSAuditViewSet(_GembaBaseViewSet):
    serializer_class = FiveSAuditSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ["tour", "auditor"]

    def get_queryset(self):
        return FiveSAudit.objects.filter(
            tenant=self.request.tenant
        ).select_related("tour", "auditor")

    @action(detail=False, methods=["get"])
    def by_zone(self, request):
        zone_id = request.query_params.get("zone_id")
        if not zone_id:
            return Response({"error": "zone_id est requis"}, status=400)
        qs = self.get_queryset().filter(tour__zone_id=zone_id).order_by("-created_at")
        return Response(FiveSAuditSerializer(qs, many=True).data)
