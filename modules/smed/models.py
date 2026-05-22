from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


class SMEDSession(BaseModel):
    class Status(models.TextChoices):
        OBSERVATION = "observation", "Observation"
        ANALYSIS = "analysis", "Analysis"
        OPTIMISED = "optimised", "Optimised"

    machine = models.ForeignKey(
        "tpm.Machine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smed_sessions",
    )
    product_before = models.CharField(max_length=150)
    product_after = models.CharField(max_length=150)
    observed_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smed_sessions_observed",
    )
    validated_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smed_sessions_validated",
    )
    date_observed = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OBSERVATION)
    notes = models.TextField(blank=True)

    total_time_before = models.IntegerField(default=0)
    total_time_after = models.IntegerField(default=0)
    internal_time_before = models.IntegerField(default=0)
    internal_time_after = models.IntegerField(default=0)
    external_time_before = models.IntegerField(default=0)
    external_time_after = models.IntegerField(default=0)
    improvement_pct = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    externalisation_gain_pct = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smed_sessions_approved",
    )
    locked_for_editing = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        db_table = "smed_sessions"
        ordering = ["-date_observed", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "date_observed"]),
            models.Index(fields=["tenant", "machine", "date_observed"]),
            models.Index(fields=["tenant", "status", "date_observed"]),
            models.Index(fields=["tenant", "observed_by"]),
            models.Index(fields=["tenant", "validated_by"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_time_before__gte=0),
                name="smed_session_total_before_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_time_after__gte=0),
                name="smed_session_total_after_nonnegative",
            ),
        ]

    def __str__(self):
        return f"SMED {self.product_before} -> {self.product_after}"


class SMEDStep(BaseModel):
    class StepType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        EXTERNAL = "external", "External"

    session = models.ForeignKey(SMEDSession, on_delete=models.CASCADE, related_name="steps")
    description = models.TextField()
    step_type = models.CharField(max_length=20, choices=StepType.choices, default=StepType.INTERNAL)
    duration_before_sec = models.IntegerField(default=0)
    duration_after_sec = models.IntegerField(default=0)
    can_externalise = models.BooleanField(default=False)
    is_optimised = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    operator = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="smed_steps_operated",
    )
    notes = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "smed_steps"
        ordering = ["session", "order", "created_at"]
        indexes = [
            models.Index(fields=["tenant", "session", "order"]),
            models.Index(fields=["tenant", "step_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "order"],
                condition=models.Q(is_active=True, is_deleted=False),
                name="unique_smed_step_order_per_session",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_before_sec__gte=0),
                name="smed_step_duration_before_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_after_sec__gte=0),
                name="smed_step_duration_after_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.order}. {self.description[:60]}"
