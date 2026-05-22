# modules/lean_flow/views.py
"""
Lean Flow ViewSets -- Kanban / CONWIP / DDMRP manufacturing flow control.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import (
    FlowBoard, FlowColumn, FlowCard,
    KanbanFlowConfig, KanbanCard,
    ConwipLine, ConwipLineStation, ConwipTicket,
    DDMRPBuffer, DDMRPRecommendation,
)
from .serializers import (
    FlowBoardSerializer, FlowColumnSerializer,
    FlowCardSerializer, FlowCardMoveSerializer,
    KanbanFlowConfigSerializer, KanbanCardSerializer, KanbanScanSerializer,
    ConwipLineSerializer, ConwipLineStationSerializer,
    ConwipTicketSerializer, ConwipTicketActionSerializer,
    DDMRPBufferSerializer, DDMRPRecommendationSerializer,
)


class LeanFlowBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "lean_flow"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_destroy(self, instance):
        if hasattr(instance, "soft_delete"):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()


# ── Layer 1: Visual Board ──

class FlowBoardViewSet(LeanFlowBaseViewSet):
    serializer_class = FlowBoardSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["board_type"]
    search_fields    = ["name"]
    ordering_fields  = ["name", "created_at"]

    def get_queryset(self):
        return FlowBoard.objects.filter(tenant=self.request.tenant, is_active=True)


class FlowColumnViewSet(viewsets.ModelViewSet):
    serializer_class   = FlowColumnSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name        = "lean_flow"
    filter_backends    = [DjangoFilterBackend, OrderingFilter]
    filterset_fields   = ["board", "is_done_column"]
    ordering_fields    = ["position"]

    def get_queryset(self):
        return FlowColumn.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def perform_destroy(self, instance):
        instance.delete()


class FlowCardViewSet(LeanFlowBaseViewSet):
    serializer_class = FlowCardSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["board", "column", "priority", "assigned_to"]
    search_fields    = ["title", "description"]
    ordering_fields  = ["position", "due_date", "priority", "created_at"]

    def get_queryset(self):
        return FlowCard.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).select_related("column", "assigned_to")

    def perform_create(self, serializer):
        card = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        card.sync_to_shared_action()

    def perform_update(self, serializer):
        card = serializer.save()
        card.sync_to_shared_action()

    @action(detail=True, methods=["patch"], url_path="move")
    def move(self, request, pk=None):
        card = self.get_object()
        ser = FlowCardMoveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            target_col = FlowColumn.objects.get(
                id=ser.validated_data["column"], board=card.board, tenant=request.tenant)
        except FlowColumn.DoesNotExist:
            return Response({"detail": "Target column not found."}, status=status.HTTP_400_BAD_REQUEST)
        if target_col.wip_limit > 0:
            count = FlowCard.objects.filter(column=target_col, is_active=True).exclude(id=card.id).count()
            if count >= target_col.wip_limit:
                return Response({"detail": "Column WIP limit reached."}, status=status.HTTP_409_CONFLICT)
        card.column = target_col
        card.position = ser.validated_data["position"]
        card.save(update_fields=["column", "position", "updated_at"])
        card.sync_to_shared_action()
        return Response(FlowCardSerializer(card).data)


# ── Layer 2: Kanban ──

class KanbanFlowConfigViewSet(LeanFlowBaseViewSet):
    serializer_class = KanbanFlowConfigSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["board"]
    search_fields    = ["reference", "supplier_station", "consumer_station"]

    def get_queryset(self):
        return KanbanFlowConfig.objects.filter(tenant=self.request.tenant, is_active=True)

    @action(detail=True, methods=["post"], url_path="generate-cards")
    def generate_cards(self, request, pk=None):
        """Create cards up to optimal_card_count."""
        flow = self.get_object()
        existing = flow.cards.filter(is_active=True).count()
        to_create = flow.optimal_card_count - existing
        if to_create <= 0:
            return Response({"detail": "Optimal count already met.", "existing": existing})
        created = []
        for i in range(to_create):
            idx = existing + i + 1
            card = KanbanCard.objects.create(
                flow=flow, code=f"K-{flow.reference}-{idx:04d}",
                quantity=flow.container_capacity,
                tenant=flow.tenant, created_by=request.user,
            )
            created.append(card)
        return Response(KanbanCardSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


class KanbanCardViewSet(LeanFlowBaseViewSet):
    serializer_class = KanbanCardSerializer
    filter_backends  = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["flow", "status"]
    ordering_fields  = ["last_scanned_at"]

    def get_queryset(self):
        return KanbanCard.objects.filter(tenant=self.request.tenant, is_active=True)

    @action(detail=False, methods=["post"], url_path="scan")
    def scan(self, request):
        """Scan a card by code. Toggles FULL<->EMPTY."""
        ser = KanbanScanSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            card = KanbanCard.objects.get(code=ser.validated_data["code"], tenant=request.tenant)
        except KanbanCard.DoesNotExist:
            return Response({"detail": "Card not found."}, status=status.HTTP_404_NOT_FOUND)
        emp = getattr(request.user, "employee_profile", None)
        old = card.status
        new = card.scan(employee=emp)
        card.sync_to_shared_action()
        return Response({
            "card": KanbanCardSerializer(card).data,
            "previous_status": old, "new_status": new,
        })

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        qs = KanbanCard.objects.filter(tenant=request.tenant, is_active=True)
        total = qs.count()
        full = qs.filter(status="full").count()
        empty = qs.filter(status="empty").count()
        return Response({
            "total": total, "full": full, "empty": empty,
            "fill_rate": round(full / total * 100, 2) if total else 0,
        })


# ── Layer 3: CONWIP ──

class ConwipLineViewSet(LeanFlowBaseViewSet):
    serializer_class = ConwipLineSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["board"]
    search_fields    = ["name"]

    def get_queryset(self):
        return ConwipLine.objects.filter(tenant=self.request.tenant, is_active=True)


class ConwipLineStationViewSet(viewsets.ModelViewSet):
    serializer_class   = ConwipLineStationSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name        = "lean_flow"
    filter_backends    = [DjangoFilterBackend, OrderingFilter]
    filterset_fields   = ["line", "is_bottleneck"]
    ordering_fields    = ["position"]

    def get_queryset(self):
        return ConwipLineStation.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def perform_destroy(self, instance):
        instance.delete()


class ConwipTicketViewSet(LeanFlowBaseViewSet):
    serializer_class = ConwipTicketSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ["line", "status"]

    def get_queryset(self):
        return ConwipTicket.objects.filter(tenant=self.request.tenant, is_active=True)

    @action(detail=True, methods=["post"], url_path="assign")
    def assign_ticket(self, request, pk=None):
        ticket = self.get_object()
        ser = ConwipTicketActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            station = ConwipLineStation.objects.get(
                id=ser.validated_data["station_id"], line=ticket.line, tenant=request.tenant)
        except ConwipLineStation.DoesNotExist:
            return Response({"detail": "Station not found."}, status=status.HTTP_400_BAD_REQUEST)
        if ticket.line.is_saturated():
            return Response({"detail": "Line WIP limit reached."}, status=status.HTTP_409_CONFLICT)
        ticket.assign(station)
        return Response(ConwipTicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        ticket = self.get_object()
        ticket.start()
        return Response(ConwipTicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        ticket = self.get_object()
        ser = ConwipTicketActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            station = ConwipLineStation.objects.get(
                id=ser.validated_data["station_id"], line=ticket.line, tenant=request.tenant)
        except ConwipLineStation.DoesNotExist:
            return Response({"detail": "Station not found."}, status=status.HTTP_400_BAD_REQUEST)
        ticket.advance(station)
        return Response(ConwipTicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        ticket = self.get_object()
        ticket.release()
        return Response(ConwipTicketSerializer(ticket).data)


# ── Layer 4: DDMRP ──

class DDMRPBufferViewSet(LeanFlowBaseViewSet):
    serializer_class = DDMRPBufferSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["board", "current_status"]
    search_fields    = ["reference"]
    ordering_fields  = ["reference", "current_stock"]

    def get_queryset(self):
        return DDMRPBuffer.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        buf = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        buf.recalculate_status()

    def perform_update(self, serializer):
        buf = serializer.save()
        buf.recalculate_status()

    @action(detail=True, methods=["post"], url_path="recalculate")
    def recalculate(self, request, pk=None):
        buf = self.get_object()
        buf.recalculate_status()
        return Response(DDMRPBufferSerializer(buf).data)


class DDMRPRecommendationViewSet(LeanFlowBaseViewSet):
    serializer_class = DDMRPRecommendationSerializer
    filter_backends  = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["buffer", "recommendation_type", "status"]
    ordering_fields  = ["priority", "created_at"]

    def get_queryset(self):
        return DDMRPRecommendation.objects.filter(tenant=self.request.tenant, is_active=True)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        reco = self.get_object()
        emp = getattr(request.user, "employee_profile", None)
        if not emp:
            return Response({"detail": "Employee profile required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            reco.execute(emp)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        reco.sync_to_shared_action()
        return Response(DDMRPRecommendationSerializer(reco).data)
