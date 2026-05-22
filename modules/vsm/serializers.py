# modules/vsm/serializers.py
"""
VSM Serializers -- explicit field lists, strict validation.
"""
from rest_framework import serializers
from .models import VSMMap, VSMElement, VSMVersion


VALID_ELEMENT_TYPES = [
    "supplier", "customer", "process", "inventory",
    "transport", "information_flow", "material_flow", "kaizen_burst",
]


class VSMMapSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(
        source="owner.full_name", read_only=True, default=None
    )

    class Meta:
        model = VSMMap
        fields = [
            "id", "name", "state", "status", "visibility", "description", "tags",
            "diagram_data",
            "total_lead_time", "value_added_time", "takt_time",
            "process_count", "bottleneck_node_id", "metrics_json",
            "owner", "owner_name", "department",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "total_lead_time", "value_added_time", "takt_time",
            "process_count", "bottleneck_node_id", "metrics_json",
            "created_at", "updated_at",
        ]

    def validate_name(self, value):
        if len(value) < 3:
            raise serializers.ValidationError(
                "Map name must be at least 3 characters."
            )
        return value

    def validate_tags(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Tags must be a list.")
        return value


class VSMElementSerializer(serializers.ModelSerializer):
    class Meta:
        model = VSMElement
        fields = [
            "id", "vsm_map", "element_type",
            "position_x", "position_y", "width", "height",
            "properties", "connections", "z_index",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_element_type(self, value):
        if value not in VALID_ELEMENT_TYPES:
            raise serializers.ValidationError(
                f"Invalid element_type. Must be one of: {VALID_ELEMENT_TYPES}"
            )
        return value

    def validate_connections(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Connections must be a list of UUIDs.")
        # H3: Soft guard — strip entries that are not valid UUID strings
        import uuid
        cleaned = []
        for item in value:
            if isinstance(item, str):
                try:
                    uuid.UUID(item)
                    cleaned.append(item)
                except ValueError:
                    pass  # silently strip non-UUID entries
        return cleaned

    def validate_properties(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Properties must be a JSON object.")
        # H4: 64KB payload size guard
        import json
        if len(json.dumps(value).encode("utf-8")) > 65536:
            raise serializers.ValidationError("Properties payload exceeds 64KB limit.")
        return value


class VSMVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VSMVersion
        fields = [
            "id", "vsm_map", "version_num", "label",
            "diagram_data", "metrics_snapshot",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "version_num", "diagram_data", "metrics_snapshot",
            "created_at", "updated_at",
        ]


class SnapshotRequestSerializer(serializers.Serializer):
    """Lightweight serializer for the snapshot action."""
    label = serializers.CharField(max_length=200, required=False, default="")
