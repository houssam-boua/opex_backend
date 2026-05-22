# modules/lean_flow/serializers.py
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers
from .models import (
    FlowBoard, FlowColumn, FlowCard,
    KanbanFlowConfig, KanbanCard,
    ConwipLine, ConwipLineStation, ConwipTicket,
    DDMRPBuffer, DDMRPRecommendation,
)


# -- Layer 1: Visual Board --

class FlowBoardSerializer(serializers.ModelSerializer):
    class Meta:
        model = FlowBoard
        fields = ["id", "name", "board_type", "description", "wip_limit",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("Board name must be at least 2 characters.")
        return value


class FlowColumnSerializer(serializers.ModelSerializer):
    class Meta:
        model = FlowColumn
        fields = ["id", "board", "name", "position", "wip_limit", "is_done_column"]
        read_only_fields = ["id"]

    def validate_position(self, value):
        if value < 0:
            raise serializers.ValidationError("Position cannot be negative.")
        return value


class FlowCardSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", read_only=True, default=None)

    class Meta:
        model = FlowCard
        fields = ["id", "board", "column", "title", "description", "priority",
                  "assigned_to", "assigned_to_name", "due_date", "position",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_due_date(self, value):
        if value and value < timezone.now().date():
            raise serializers.ValidationError("Due date cannot be in the past.")
        return value


class FlowCardMoveSerializer(serializers.Serializer):
    column = serializers.UUIDField(required=True)
    position = serializers.IntegerField(required=True, min_value=0)


# -- Layer 2: Kanban --

class KanbanFlowConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = KanbanFlowConfig
        fields = ["id", "board", "reference", "supplier_station", "consumer_station",
                  "demand_avg", "lead_time_days", "container_capacity",
                  "optimal_card_count", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "optimal_card_count", "created_at", "updated_at"]

    def validate_container_capacity(self, value):
        if value < 1:
            raise serializers.ValidationError("Container capacity must be at least 1.")
        return value


class KanbanCardSerializer(serializers.ModelSerializer):
    scanned_by_name = serializers.CharField(source="scanned_by.full_name", read_only=True, default=None)

    class Meta:
        model = KanbanCard
        fields = ["id", "flow", "code", "status", "quantity",
                  "last_scanned_at", "scanned_by", "scanned_by_name",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "code", "last_scanned_at", "created_at", "updated_at"]


class KanbanScanSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50, required=True)


# -- Layer 3: CONWIP --

class ConwipLineSerializer(serializers.ModelSerializer):
    current_wip = serializers.SerializerMethodField()
    is_saturated = serializers.SerializerMethodField()

    class Meta:
        model = ConwipLine
        fields = ["id", "board", "name", "wip_critical",
                  "current_wip", "is_saturated",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "current_wip", "is_saturated", "created_at", "updated_at"]

    def get_current_wip(self, obj):
        return obj.get_current_wip()

    def get_is_saturated(self, obj):
        return obj.is_saturated()


class ConwipLineStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConwipLineStation
        fields = ["id", "line", "name", "position", "is_bottleneck"]
        read_only_fields = ["id"]


class ConwipTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConwipTicket
        fields = ["id", "line", "number", "status", "current_station",
                  "assigned_at", "released_at",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "assigned_at", "released_at", "created_at", "updated_at"]


class ConwipTicketActionSerializer(serializers.Serializer):
    """For assign/advance actions."""
    station_id = serializers.UUIDField(required=True)


# -- Layer 4: DDMRP --

class DDMRPBufferSerializer(serializers.ModelSerializer):
    optimal_replenishment_qty = serializers.SerializerMethodField()

    class Meta:
        model = DDMRPBuffer
        fields = ["id", "board", "reference", "adu", "lead_time_days",
                  "lt_factor", "variability_factor", "moq",
                  "red_zone", "yellow_zone", "green_zone",
                  "current_stock", "current_status",
                  "optimal_replenishment_qty", "last_calculated_at",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "red_zone", "yellow_zone", "green_zone",
                           "current_status", "optimal_replenishment_qty",
                           "last_calculated_at", "created_at", "updated_at"]

    def get_optimal_replenishment_qty(self, obj):
        return str(obj.get_optimal_replenishment_qty())

    def validate(self, data):
        lt_f = data.get("lt_factor", Decimal("0.50"))
        var_f = data.get("variability_factor", Decimal("0.50"))
        if lt_f < 0 or lt_f > 1:
            raise serializers.ValidationError("lt_factor must be between 0 and 1.")
        if var_f < 0 or var_f > 1:
            raise serializers.ValidationError("variability_factor must be between 0 and 1.")
        return data


class DDMRPRecommendationSerializer(serializers.ModelSerializer):
    executed_by_name = serializers.CharField(source="executed_by.full_name", read_only=True, default=None)

    class Meta:
        model = DDMRPRecommendation
        fields = ["id", "buffer", "recommendation_type", "quantity", "priority",
                  "status", "justification", "executed_at",
                  "executed_by", "executed_by_name",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "executed_at", "created_at", "updated_at"]

    def validate_priority(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Priority must be 1-5.")
        return value
