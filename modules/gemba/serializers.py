# modules/gemba/serializers.py
"""
Gemba Walk Module — Serializers
Operational actor references use Employee.full_name.
"""
from rest_framework import serializers
from django.utils import timezone
from accounts.models import Employee
from .models import (
    GembaZone, GembaTeam, GembaCategory,
    Checkpoint, Tour, TourParticipant, ExecutionPoint,
    Anomaly, FaceToFace, FiveSAudit,
)


def _request_employee(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee or employee.tenant_id != request.tenant.id:
        raise serializers.ValidationError("Aucun Employee valide n'est lie a cet utilisateur.")
    return employee


def _validate_employee_tenant(employee, tenant):
    if employee and employee.tenant_id != tenant.id:
        raise serializers.ValidationError("L'Employee selectionne n'appartient pas au tenant courant.")


# ─── Reference Data ──────────────────────────────────────────────────

class GembaZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model  = GembaZone
        fields = ["id", "name", "code", "description", "parent", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class GembaTeamSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source="zone.name", read_only=True)

    class Meta:
        model  = GembaTeam
        fields = ["id", "name", "zone", "zone_name", "leader", "members", "is_active"]
        read_only_fields = ["id"]


class GembaCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model  = GembaCategory
        fields = ["id", "name", "type", "color", "icon", "is_active"]
        read_only_fields = ["id"]


# ─── Checkpoints ─────────────────────────────────────────────────────

class CheckpointSerializer(serializers.ModelSerializer):
    category_details = GembaCategorySerializer(source="category", read_only=True)
    zone_ids = serializers.SerializerMethodField()

    class Meta:
        model  = Checkpoint
        fields = [
            "id", "name", "description", "category", "category_details",
            "zones", "zone_ids", "standard_photo", "standard_description",
            "order", "is_critical", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_zone_ids(self, obj):
        return list(obj.zones.values_list("id", flat=True))

    def create(self, validated_data):
        zones = validated_data.pop("zones", [])
        validated_data["created_by"] = self.context["request"].user
        validated_data["tenant"]     = self.context["request"].tenant
        checkpoint = Checkpoint.objects.create(**validated_data)
        checkpoint.zones.set(zones)
        return checkpoint


# ─── Tour Participants ───────────────────────────────────────────────

class TourParticipantSerializer(serializers.ModelSerializer):
    user_name    = serializers.CharField(source="user.full_name", read_only=True)
    role_display = serializers.SerializerMethodField()

    class Meta:
        model  = TourParticipant
        fields = ["id", "tour", "user", "user_name", "role", "role_display",
                  "attended", "joined_at", "left_at"]
        read_only_fields = ["id"]

    def get_role_display(self, obj):
        return obj.get_role_display()

    def validate_user(self, value):
        if not value:
            raise serializers.ValidationError("Employee requis pour un participant.")
        _validate_employee_tenant(value, self.context["request"].tenant)
        return value


# ─── Tours (Gemba Walks) ────────────────────────────────────────────

class TourListSerializer(serializers.ModelSerializer):
    zone_name         = serializers.CharField(source="zone.name", read_only=True)
    team_name         = serializers.CharField(source="team.name", read_only=True, default=None)
    status_display    = serializers.SerializerMethodField()
    objective_display = serializers.SerializerMethodField()
    participant_count = serializers.SerializerMethodField()
    created_by_name   = serializers.CharField(source="created_by.full_name", read_only=True)

    class Meta:
        model  = Tour
        fields = [
            "id", "title", "date", "start_time", "end_time", "zone", "zone_name",
            "team", "team_name", "objective", "objective_display", "status",
            "status_display", "participant_count", "created_by", "created_by_name",
            "created_at",
        ]

    def get_status_display(self, obj):
        return obj.get_status_display()

    def get_objective_display(self, obj):
        return obj.get_objective_display()

    def get_participant_count(self, obj):
        return obj.participant_set.count()


class TourDetailSerializer(serializers.ModelSerializer):
    zone_details         = GembaZoneSerializer(source="zone", read_only=True)
    participants_details = TourParticipantSerializer(source="participant_set", many=True, read_only=True)
    status_display       = serializers.SerializerMethodField()
    objective_display    = serializers.SerializerMethodField()
    created_by_name      = serializers.CharField(source="created_by.full_name", read_only=True)
    execution_stats      = serializers.SerializerMethodField()

    class Meta:
        model  = Tour
        fields = [
            "id", "title", "date", "start_time", "end_time", "zone", "zone_details",
            "team", "objective", "objective_display", "description", "status",
            "status_display", "created_by", "created_by_name", "participants_details",
            "actual_start", "actual_end", "duration_minutes", "notes",
            "execution_stats", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_status_display(self, obj):
        return obj.get_status_display()

    def get_objective_display(self, obj):
        return obj.get_objective_display()

    def get_execution_stats(self, obj):
        executions = obj.execution_points.all()
        total = executions.count()
        if total == 0:
            return {"total": 0, "ok": 0, "nok": 0, "na": 0, "completion_rate": 0}
        ok  = executions.filter(status="ok").count()
        nok = executions.filter(status="nok").count()
        na  = executions.filter(status="na").count()
        return {
            "total": total, "ok": ok, "nok": nok, "na": na,
            "completion_rate": round((ok + nok + na) / total * 100, 1),
        }


class TourCreateSerializer(serializers.ModelSerializer):
    participant_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False
    )

    class Meta:
        model  = Tour
        fields = [
            "title", "date", "start_time", "end_time", "zone", "team",
            "objective", "description", "participant_ids",
        ]

    def create(self, validated_data):
        participant_ids = validated_data.pop("participant_ids", [])
        validated_data["created_by"] = self.context["request"].user
        validated_data["tenant"]     = self.context["request"].tenant
        if participant_ids:
            tenant = self.context["request"].tenant
            valid_ids = set(
                str(pk) for pk in Employee.objects.filter(
                    tenant=tenant, id__in=participant_ids
                ).values_list("id", flat=True)
            )
            requested_ids = {str(pk) for pk in participant_ids}
            if valid_ids != requested_ids:
                raise serializers.ValidationError("Tous les participants doivent appartenir au tenant courant.")
        tour = Tour.objects.create(**validated_data)
        for uid in participant_ids:
            TourParticipant.objects.create(
                tour=tour, user_id=uid,
                tenant=self.context["request"].tenant,
                created_by=self.context["request"].user,
            )
        return tour


class TourUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Tour
        fields = [
            "title", "date", "start_time", "end_time", "zone", "team",
            "objective", "description", "status", "notes",
        ]


# ─── Execution Points ───────────────────────────────────────────────

class ExecutionPointSerializer(serializers.ModelSerializer):
    checkpoint_name  = serializers.CharField(source="checkpoint.name", read_only=True)
    category_name    = serializers.CharField(source="checkpoint.category.name", read_only=True)
    status_display   = serializers.SerializerMethodField()
    executed_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = ExecutionPoint
        fields = [
            "id", "tour", "checkpoint", "checkpoint_name", "category_name",
            "status", "status_display", "photo", "comment", "voice_note",
            "gps_latitude", "gps_longitude", "executed_by", "executed_by_name",
            "executed_at", "synced_at", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_status_display(self, obj):
        return obj.get_status_display()

    def get_executed_by_name(self, obj):
        return obj.executed_by.full_name if obj.executed_by else None


class ExecutionPointCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ExecutionPoint
        fields = [
            "tour", "checkpoint", "status", "photo", "comment",
            "voice_note", "gps_latitude", "gps_longitude",
        ]

    def create(self, validated_data):
        validated_data["executed_by"] = _request_employee(self.context["request"])
        validated_data["executed_at"] = timezone.now()
        validated_data["synced_at"]   = timezone.now()
        validated_data["tenant"]      = self.context["request"].tenant
        execution, _ = ExecutionPoint.objects.update_or_create(
            tour=validated_data["tour"],
            checkpoint=validated_data["checkpoint"],
            defaults=validated_data,
        )
        return execution


# ─── Anomalies ───────────────────────────────────────────────────────

class AnomalyListSerializer(serializers.ModelSerializer):
    severity_display  = serializers.SerializerMethodField()
    status_display    = serializers.SerializerMethodField()
    assigned_to_name  = serializers.SerializerMethodField()
    zone_name         = serializers.SerializerMethodField()
    category_name     = serializers.SerializerMethodField()
    is_overdue        = serializers.ReadOnlyField()

    class Meta:
        model  = Anomaly
        fields = [
            "id", "title", "description", "category", "category_name",
            "severity", "severity_display", "status", "status_display",
            "assigned_to", "assigned_to_name", "due_date", "is_overdue",
            "zone_name", "created_at",
        ]

    def get_severity_display(self, obj):
        return obj.get_severity_display()

    def get_status_display(self, obj):
        return obj.get_status_display()

    def get_assigned_to_name(self, obj):
        return obj.assigned_to.full_name if obj.assigned_to else None

    def get_zone_name(self, obj):
        return obj.zone.name if obj.zone else None

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None


class AnomalyDetailSerializer(serializers.ModelSerializer):
    severity_display  = serializers.SerializerMethodField()
    status_display    = serializers.SerializerMethodField()
    assigned_to_name  = serializers.SerializerMethodField()
    resolved_by_name  = serializers.SerializerMethodField()
    validated_by_name = serializers.SerializerMethodField()
    created_by_name   = serializers.SerializerMethodField()
    zone_name         = serializers.SerializerMethodField()
    tour_title        = serializers.SerializerMethodField()
    is_overdue        = serializers.ReadOnlyField()

    class Meta:
        model  = Anomaly
        fields = [
            "id", "execution_point", "title", "description",
            "category", "severity", "severity_display", "status", "status_display",
            "assigned_to", "assigned_to_name", "due_date", "is_overdue",
            "resolution", "resolution_photo", "resolved_by", "resolved_by_name",
            "resolved_at", "validated_by", "validated_by_name", "validated_at",
            "created_by", "created_by_name", "zone_name", "tour_title",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_severity_display(self, obj):  return obj.get_severity_display()
    def get_status_display(self, obj):    return obj.get_status_display()
    def get_assigned_to_name(self, obj):  return obj.assigned_to.full_name if obj.assigned_to else None
    def get_resolved_by_name(self, obj):  return obj.resolved_by.full_name if obj.resolved_by else None
    def get_validated_by_name(self, obj): return obj.validated_by.full_name if obj.validated_by else None
    def get_created_by_name(self, obj):   return obj.created_by.full_name if obj.created_by else None
    def get_zone_name(self, obj):         return obj.zone.name if obj.zone else None
    def get_tour_title(self, obj):        return obj.tour.title if obj.tour else None


class AnomalyCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Anomaly
        fields = [
            "execution_point", "title", "description", "category",
            "severity", "assigned_to", "due_date",
        ]

    def create(self, validated_data):
        _validate_employee_tenant(validated_data.get("assigned_to"), self.context["request"].tenant)
        validated_data["created_by"] = self.context["request"].user
        validated_data["tenant"]     = self.context["request"].tenant
        return Anomaly.objects.create(**validated_data)


# ─── Face-to-Face ────────────────────────────────────────────────────

class FaceToFaceSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source="operator.full_name", read_only=True)
    manager_name  = serializers.CharField(source="manager.full_name", read_only=True)
    mood_display  = serializers.SerializerMethodField()

    class Meta:
        model  = FaceToFace
        fields = [
            "id", "tour", "operator", "operator_name", "manager", "manager_name",
            "subject", "feedback", "mood", "mood_display", "action_required",
            "action_description", "created_at",
        ]
        read_only_fields = ["id", "manager", "created_at"]

    def get_mood_display(self, obj):
        return obj.get_mood_display()

    def create(self, validated_data):
        _validate_employee_tenant(validated_data.get("operator"), self.context["request"].tenant)
        validated_data["manager"] = _request_employee(self.context["request"])
        validated_data["tenant"]  = self.context["request"].tenant
        return super().create(validated_data)


# ─── 5S Audit ────────────────────────────────────────────────────────

class FiveSAuditSerializer(serializers.ModelSerializer):
    total_score      = serializers.ReadOnlyField()
    percentage_score = serializers.ReadOnlyField()
    auditor_name     = serializers.SerializerMethodField()

    class Meta:
        model  = FiveSAudit
        fields = [
            "id", "tour", "sort_score", "set_in_order_score", "shine_score",
            "standardize_score", "sustain_score", "total_score", "percentage_score",
            "before_photo", "after_photo", "comments", "auditor", "auditor_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "auditor", "created_at", "updated_at"]

    def get_auditor_name(self, obj):
        return obj.auditor.full_name if obj.auditor else None

    def create(self, validated_data):
        validated_data["auditor"] = _request_employee(self.context["request"])
        validated_data["tenant"]  = self.context["request"].tenant
        return super().create(validated_data)


# ─── Calendar ────────────────────────────────────────────────────────

class CalendarEventSerializer(serializers.ModelSerializer):
    start = serializers.SerializerMethodField()
    end   = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()

    class Meta:
        model  = Tour
        fields = ["id", "title", "start", "end", "color", "status", "zone"]

    def get_start(self, obj):
        return f"{obj.date}T{obj.start_time}" if obj.start_time else str(obj.date)

    def get_end(self, obj):
        return f"{obj.date}T{obj.end_time}" if obj.end_time else str(obj.date)

    def get_color(self, obj):
        colors = {
            "planned": "#3788d8", "in_progress": "#f59e0b",
            "completed": "#10b981", "cancelled": "#ef4444",
        }
        return colors.get(obj.status, "#6b7280")
