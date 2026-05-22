# modules/gemba/models.py
"""
Gemba Walk Module — OPEX SaaS
Migrated from: Gemba Walk/prj/backend/ (tours, anomalies, checkpoints, core)

Changes from legacy:
  - All models inherit from BaseModel (UUID PK, tenant, soft-delete, audit)
  - Legacy operational users mapped to accounts.Employee
  - AnomalieComment mapped to shared.models.Comment (GenericFK)
  - AnomalieHistory mapped to shared.models.AuditLog
  - TenantManager on all models
  - Zone, Team, Category, Checkpoint internalized into this module
"""
from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


# ─────────────────────────────────────────────────────────────────────
# REFERENCE DATA  (ex-core app: Zone, Team, Category)
# ─────────────────────────────────────────────────────────────────────

class GembaZone(BaseModel):
    """Zone de production / atelier visité pendant le Gemba Walk."""
    name        = models.CharField(max_length=100)
    code        = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    parent      = models.ForeignKey(
        "self", on_delete=models.CASCADE,
        null=True, blank=True, related_name="children"
    )

    objects = TenantManager()

    class Meta:
        db_table = "gemba_zones"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="unique_zone_code_per_tenant"
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class GembaTeam(BaseModel):
    """Équipe de production associée à une zone."""
    name    = models.CharField(max_length=100)
    zone    = models.ForeignKey(GembaZone, on_delete=models.CASCADE, related_name="teams")
    leader  = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_led_teams"
    )
    members = models.ManyToManyField(
        "accounts.Employee", related_name="gemba_teams", blank=True
    )

    objects = TenantManager()

    class Meta:
        db_table = "gemba_teams"
        ordering = ["name"]

    def __str__(self):
        return self.name


class GembaCategory(BaseModel):
    """Catégorie de checkpoint (Sécurité, Qualité, 5S, etc.)."""
    class CategoryType(models.TextChoices):
        SECURITY    = "security",    "Sécurité"
        QUALITY     = "quality",     "Qualité"
        PROCESS     = "process",     "Process"
        MAINTENANCE = "maintenance", "Maintenance"
        HR          = "hr",          "Ressources Humaines"
        FIVE_S      = "5s",          "5S"

    name  = models.CharField(max_length=100)
    type  = models.CharField(max_length=20, choices=CategoryType.choices)
    color = models.CharField(max_length=7, default="#000000")
    icon  = models.CharField(max_length=50, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "gemba_categories"
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────
# CHECKPOINTS
# ─────────────────────────────────────────────────────────────────────

class Checkpoint(BaseModel):
    """Point de contrôle standard à vérifier pendant un Gemba Walk."""
    name                 = models.CharField(max_length=200)
    description          = models.TextField(blank=True)
    category             = models.ForeignKey(
        GembaCategory, on_delete=models.CASCADE, related_name="checkpoints"
    )
    zones                = models.ManyToManyField(GembaZone, related_name="checkpoints", blank=True)
    standard_photo       = models.ImageField(upload_to="gemba/standards/", blank=True, null=True)
    standard_description = models.TextField(blank=True)
    order                = models.PositiveIntegerField(default=0)
    is_critical          = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        db_table = "gemba_checkpoints"
        ordering = ["category", "order", "name"]

    def __str__(self):
        return f"{self.category.name} - {self.name}"


# ─────────────────────────────────────────────────────────────────────
# TOURNÉES (Gemba Walks)
# ─────────────────────────────────────────────────────────────────────

class Tour(BaseModel):
    """
    Tournée Gemba Walk (ex-Tournee).
    Renamed to English for consistency with OPEX naming conventions.
    """
    class Status(models.TextChoices):
        PLANNED     = "planned",     "Planifiée"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED   = "completed",   "Réalisée"
        CANCELLED   = "cancelled",   "Annulée"

    class Objective(models.TextChoices):
        SECURITY = "security", "Sécurité"
        QUALITY  = "quality",  "Qualité"
        FIVE_S   = "5s",       "5S"
        PROCESS  = "process",  "Process"
        GENERAL  = "general",  "Général"

    title        = models.CharField(max_length=200)
    date         = models.DateField()
    start_time   = models.TimeField(null=True, blank=True)
    end_time     = models.TimeField(null=True, blank=True)
    zone         = models.ForeignKey(GembaZone, on_delete=models.CASCADE, related_name="tours")
    team         = models.ForeignKey(
        GembaTeam, on_delete=models.CASCADE, related_name="tours", null=True, blank=True
    )
    objective    = models.CharField(
        max_length=20, choices=Objective.choices, default=Objective.GENERAL
    )
    description  = models.TextField(blank=True)
    status       = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PLANNED
    )
    participants = models.ManyToManyField(
        "accounts.Employee", through="TourParticipant",
        through_fields=("tour", "user"), related_name="gemba_tours"
    )
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end   = models.DateTimeField(null=True, blank=True)
    notes        = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "gemba_tours"
        ordering = ["-date", "-start_time"]

    def __str__(self):
        return f"{self.title} - {self.date} ({self.zone.name})"

    @property
    def duration_minutes(self):
        if self.actual_start and self.actual_end:
            delta = self.actual_end - self.actual_start
            return int(delta.total_seconds() / 60)
        return None


class TourParticipant(BaseModel):
    """Participant à une tournée Gemba Walk (ex-Participant)."""
    class Role(models.TextChoices):
        LEADER   = "leader",   "Animateur"
        OBSERVER = "observer", "Observateur"
        TRAINEE  = "trainee",  "En formation"

    tour     = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="participant_set")
    user     = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_tour_participations"
    )
    role     = models.CharField(max_length=20, choices=Role.choices, default=Role.OBSERVER)
    attended = models.BooleanField(default=False)
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at   = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "gemba_tour_participants"
        constraints = [
            models.UniqueConstraint(
                fields=["tour", "user"],
                name="unique_participant_per_tour"
            )
        ]

    def __str__(self):
        name = self.user.full_name if self.user else "Unassigned"
        return f"{name} - {self.tour.title}"


# ─────────────────────────────────────────────────────────────────────
# EXECUTION (checkpoint results during a tour)
# ─────────────────────────────────────────────────────────────────────

class ExecutionPoint(BaseModel):
    """Résultat d'un checkpoint exécuté pendant une tournée."""
    class Status(models.TextChoices):
        OK      = "ok",      "Conforme"
        NOK     = "nok",     "Non conforme"
        NA      = "na",      "Non applicable"
        PENDING = "pending", "En attente"

    tour          = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="execution_points")
    checkpoint    = models.ForeignKey(Checkpoint, on_delete=models.CASCADE, related_name="executions")
    status        = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    photo         = models.ImageField(upload_to="gemba/executions/", blank=True, null=True)
    comment       = models.TextField(blank=True)
    voice_note    = models.FileField(upload_to="gemba/voice_notes/", blank=True, null=True)
    gps_latitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    executed_by   = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_executed_points"
    )
    executed_at   = models.DateTimeField(null=True, blank=True)
    synced_at     = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "gemba_execution_points"
        constraints = [
            models.UniqueConstraint(
                fields=["tour", "checkpoint"],
                name="unique_execution_per_tour_checkpoint"
            )
        ]
        ordering = ["checkpoint__order"]

    def __str__(self):
        return f"{self.tour.title} - {self.checkpoint.name}: {self.status}"


# ─────────────────────────────────────────────────────────────────────
# ANOMALIES (findings during Gemba Walk)
# ─────────────────────────────────────────────────────────────────────

class Anomaly(BaseModel):
    """
    Anomalie détectée pendant un Gemba Walk (ex-Anomalie).
    Comments → shared.models.Comment (GenericFK)
    History  → shared.models.AuditLog
    """
    class Severity(models.TextChoices):
        MINOR    = "minor",    "Mineur"
        MAJOR    = "major",    "Majeur"
        CRITICAL = "critical", "Critique"

    class AnomalyStatus(models.TextChoices):
        TODO               = "todo",               "À faire"
        IN_PROGRESS        = "in_progress",        "En cours"
        PENDING_VALIDATION = "pending_validation", "En attente validation"
        CLOSED             = "closed",             "Clôturé"
        REJECTED           = "rejected",           "Rejeté"

    execution_point  = models.OneToOneField(
        ExecutionPoint, on_delete=models.CASCADE,
        related_name="anomaly", null=True, blank=True
    )
    title            = models.CharField(max_length=200)
    description      = models.TextField()
    category         = models.ForeignKey(
        GembaCategory, on_delete=models.SET_NULL, null=True, related_name="anomalies"
    )
    severity         = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MINOR)
    status           = models.CharField(
        max_length=20, choices=AnomalyStatus.choices, default=AnomalyStatus.TODO
    )
    assigned_to      = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_assigned_anomalies"
    )
    due_date         = models.DateField(null=True, blank=True)
    resolution       = models.TextField(blank=True)
    resolution_photo = models.ImageField(upload_to="gemba/resolutions/", blank=True, null=True)
    resolved_by      = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_resolved_anomalies"
    )
    resolved_at      = models.DateTimeField(null=True, blank=True)
    validated_by     = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_validated_anomalies"
    )
    validated_at     = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "gemba_anomalies"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_severity_display()})"

    @property
    def is_overdue(self):
        from django.utils import timezone
        if self.due_date and self.status not in ["closed", "rejected"]:
            return timezone.now().date() > self.due_date
        return False

    @property
    def zone(self):
        if self.execution_point:
            return self.execution_point.tour.zone
        return None

    @property
    def tour(self):
        if self.execution_point:
            return self.execution_point.tour
        return None


# ─────────────────────────────────────────────────────────────────────
# FACE-TO-FACE INTERVIEWS
# ─────────────────────────────────────────────────────────────────────

class FaceToFace(BaseModel):
    """Entretien face-à-face réalisé pendant un Gemba Walk."""
    class Mood(models.TextChoices):
        POSITIVE = "positive", "Positif"
        NEUTRAL  = "neutral",  "Neutre"
        NEGATIVE = "negative", "Négatif"

    tour               = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="face_to_faces")
    operator           = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_f2f_as_operator"
    )
    manager            = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_f2f_as_manager"
    )
    subject            = models.CharField(max_length=200)
    feedback           = models.TextField()
    mood               = models.CharField(max_length=20, choices=Mood.choices, default=Mood.NEUTRAL)
    action_required    = models.BooleanField(default=False)
    action_description = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "gemba_face_to_faces"
        ordering = ["-created_at"]

    def __str__(self):
        name = self.operator.full_name if self.operator else "Unassigned"
        return f"{self.subject} - {name}"


# ─────────────────────────────────────────────────────────────────────
# 5S AUDIT (during Gemba Walk)
# ─────────────────────────────────────────────────────────────────────

class FiveSAudit(BaseModel):
    """Audit 5S réalisé pendant un Gemba Walk."""
    tour               = models.OneToOneField(Tour, on_delete=models.CASCADE, related_name="five_s_audit")
    sort_score         = models.PositiveIntegerField(default=0)
    set_in_order_score = models.PositiveIntegerField(default=0)
    shine_score        = models.PositiveIntegerField(default=0)
    standardize_score  = models.PositiveIntegerField(default=0)
    sustain_score      = models.PositiveIntegerField(default=0)
    before_photo       = models.ImageField(upload_to="gemba/5s/before/", blank=True, null=True)
    after_photo        = models.ImageField(upload_to="gemba/5s/after/", blank=True, null=True)
    comments           = models.TextField(blank=True)
    auditor            = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="gemba_five_s_audits"
    )

    objects = TenantManager()

    class Meta:
        db_table = "gemba_five_s_audits"

    @property
    def total_score(self):
        return (
            self.sort_score + self.set_in_order_score + self.shine_score
            + self.standardize_score + self.sustain_score
        )

    @property
    def percentage_score(self):
        return self.total_score * 4  # Max 25 → 100%

    def __str__(self):
        return f"5S Audit - {self.tour.title}: {self.percentage_score}%"
