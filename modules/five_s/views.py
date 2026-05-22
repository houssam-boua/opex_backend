# modules/five_s/views.py
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Avg
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from core.permissions import BelongsToTenant, ModuleIsActive
from .models import AuditQuestion, AuditSession5S, AuditResponse, Anomaly5S
from .serializers import (
    AuditQuestionSerializer, AuditSession5SSerializer, 
    AuditResponseSerializer, Anomaly5SSerializer
)

class FiveSBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "5s"

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.tenant,
            created_by=self.request.user
        )

    def perform_destroy(self, instance):
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()

class AuditQuestionViewSet(FiveSBaseViewSet):
    serializer_class = AuditQuestionSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["category"]
    ordering_fields = ["order"]

    def get_queryset(self):
        return AuditQuestion.objects.filter(tenant=self.request.tenant)

class AuditSession5SViewSet(FiveSBaseViewSet):
    serializer_class = AuditSession5SSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["zone_id", "status", "auditor"]
    ordering_fields = ["created_at", "total_score"]

    def get_queryset(self):
        return AuditSession5S.objects.filter(tenant=self.request.tenant).prefetch_related("responses", "anomalies")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        session = self.get_object()
        session.status = AuditSession5S.Status.COMPLETED
        session.calculate_scores()
        return Response(self.get_serializer(session).data)

    @action(detail=False, methods=["get"])
    def analytics(self, request):
        """
        Management Analytics Layer:
        - Average score per Zone
        - Average score per 'S' category
        - Historical trend over time
        """
        qs = self.get_queryset().filter(status=AuditSession5S.Status.COMPLETED)
        
        # Average per Zone
        zone_stats = qs.values("zone_id").annotate(
            avg_total=Avg("total_score")
        ).order_by("-avg_total")

        # Average per S Category across plant
        plant_stats = qs.aggregate(
            avg_seiri=Avg("score_seiri"),
            avg_seiton=Avg("score_seiton"),
            avg_seiso=Avg("score_seiso"),
            avg_seiketsu=Avg("score_seiketsu"),
            avg_shitsuke=Avg("score_shitsuke"),
            avg_total=Avg("total_score")
        )

        # Historical trend (monthly)
        # For SQLite/Postgres compatibility we use simple truncation or just date extraction
        from django.db.models.functions import TruncMonth
        trend = qs.annotate(month=TruncMonth("created_at")).values("month").annotate(
            avg_score=Avg("total_score")
        ).order_by("month")

        return Response({
            "zone_averages": list(zone_stats),
            "plant_averages": plant_stats,
            "historical_trend": list(trend)
        })

class AuditResponseViewSet(FiveSBaseViewSet):
    serializer_class = AuditResponseSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["session", "question"]

    def get_queryset(self):
        return AuditResponse.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        response = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        response.session.calculate_scores()

    def perform_update(self, serializer):
        response = serializer.save()
        response.session.calculate_scores()

class Anomaly5SViewSet(FiveSBaseViewSet):
    serializer_class = Anomaly5SSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["session", "priority", "status", "assigned_to"]

    def get_queryset(self):
        return Anomaly5S.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        anomaly = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        anomaly.sync_to_shared_action()

    def perform_update(self, serializer):
        anomaly = serializer.save()
        anomaly.sync_to_shared_action()
