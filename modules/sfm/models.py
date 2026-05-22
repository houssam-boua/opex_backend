from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


class SFMSession(BaseModel):
    class TierLevel(models.TextChoices):
        TIER_1 = "tier_1", "Tier 1"
        TIER_2 = "tier_2", "Tier 2"
        TIER_3 = "tier_3", "Tier 3"
        TIER_4 = "tier_4", "Tier 4"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        ESCALATED = "escalated", "Escalated"
        CANCELLED = "cancelled", "Cancelled"

    date = models.DateField()
    line = models.CharField(max_length=150)
    tier_level = models.CharField(max_length=20, choices=TierLevel.choices)
    facilitated_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sfm_sessions_facilitated",
    )
    participants = models.ManyToManyField(
        "accounts.Employee",
        blank=True,
        related_name="sfm_sessions_participated",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    notes = models.TextField(blank=True)
    meeting_duration_min = models.IntegerField(default=15)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "sfm_sessions"
        ordering = ["-date", "line", "tier_level"]
        indexes = [
            models.Index(fields=["tenant", "date"]),
            models.Index(fields=["tenant", "line", "date"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "tier_level"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "line", "date", "tier_level"],
                name="unique_sfm_session_per_line_date_tier",
            ),
            models.CheckConstraint(
                condition=models.Q(meeting_duration_min__gt=0),
                name="sfm_session_duration_positive",
            ),
        ]

    def __str__(self):
        return f"{self.line} {self.date} {self.tier_level}"


class SFMKPI(BaseModel):
    class Category(models.TextChoices):
        SAFETY = "safety", "Safety"
        QUALITY = "quality", "Quality"
        COST = "cost", "Cost"
        DELIVERY = "delivery", "Delivery"
        PEOPLE = "people", "People"
        ENVIRONMENT = "environment", "Environment"

    class TrendLogic(models.TextChoices):
        HIGHER_IS_BETTER = "HIGHER_IS_BETTER", "Higher is better"
        LOWER_IS_BETTER = "LOWER_IS_BETTER", "Lower is better"

    class ColorStatus(models.TextChoices):
        GREEN = "GREEN", "Green"
        ORANGE = "ORANGE", "Orange"
        RED = "RED", "Red"

    session = models.ForeignKey(SFMSession, on_delete=models.CASCADE, related_name="kpis")
    category = models.CharField(max_length=20, choices=Category.choices)
    kpi_name = models.CharField(max_length=200)
    objective_description = models.TextField(blank=True)
    target_period = models.DateField(null=True, blank=True)
    target = models.DecimalField(max_digits=12, decimal_places=2)
    actual = models.DecimalField(max_digits=12, decimal_places=2)
    unit = models.CharField(max_length=50, blank=True)
    trend_logic = models.CharField(max_length=30, choices=TrendLogic.choices)
    color_status = models.CharField(
        max_length=10,
        choices=ColorStatus.choices,
        default=ColorStatus.GREEN,
    )
    orange_threshold_pct = models.DecimalField(max_digits=5, decimal_places=2, default=90)
    comment = models.TextField(blank=True)
    owner = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sfm_kpis_owned",
    )
    requires_action = models.BooleanField(default=False)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sfm_kpis",
    )

    objects = TenantManager()

    class Meta:
        db_table = "sfm_kpis"
        ordering = ["session", "category", "kpi_name"]
        indexes = [
            models.Index(fields=["tenant", "session", "category"]),
            models.Index(fields=["tenant", "color_status"]),
            models.Index(fields=["tenant", "category"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(target__gte=0),
                name="sfm_kpi_target_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(actual__gte=0),
                name="sfm_kpi_actual_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(orange_threshold_pct__gt=0)
                & models.Q(orange_threshold_pct__lte=100),
                name="sfm_kpi_orange_threshold_range",
            ),
        ]

    def __str__(self):
        return f"{self.category} - {self.kpi_name}"


class SFMEscalation(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"

    session = models.ForeignKey(SFMSession, on_delete=models.CASCADE, related_name="escalations")
    kpi = models.ForeignKey(SFMKPI, on_delete=models.CASCADE, related_name="escalations")
    escalated_from_tier = models.CharField(max_length=20, choices=SFMSession.TierLevel.choices)
    escalated_to_tier = models.CharField(max_length=20, choices=SFMSession.TierLevel.choices)
    escalated_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sfm_escalations_created",
    )
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    resolved_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sfm_escalations_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "sfm_escalations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "escalated_to_tier"]),
            models.Index(fields=["tenant", "session"]),
        ]

    def __str__(self):
        return f"{self.kpi} {self.escalated_from_tier}->{self.escalated_to_tier}"
