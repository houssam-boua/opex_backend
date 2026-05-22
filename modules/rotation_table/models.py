from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


class RotationPlan(BaseModel):
    class Shift(models.TextChoices):
        MORNING = "morning", "Morning"
        AFTERNOON = "afternoon", "Afternoon"
        NIGHT = "night", "Night"
        FULL_DAY = "full_day", "Full day"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=200)
    date = models.DateField()
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_plans",
    )
    line = models.CharField(max_length=150, blank=True)
    shift = models.CharField(max_length=20, choices=Shift.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by_employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_plans_created",
    )
    approved_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_plans_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "rotation_plans"
        ordering = ["-date", "shift", "line"]
        indexes = [
            models.Index(fields=["tenant", "date"]),
            models.Index(fields=["tenant", "department", "date"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "shift"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "date", "department", "line", "shift"],
                name="unique_rotation_plan_scope",
            ),
            models.UniqueConstraint(
                fields=["tenant", "date", "line", "shift"],
                condition=models.Q(department__isnull=True),
                name="unique_rotation_plan_scope_no_department",
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.date} {self.shift}"


class Workstation(BaseModel):
    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, blank=True)
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_workstations",
    )
    line = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.LOW)
    required_skill = models.ForeignKey(
        "skills.Skill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_workstations",
    )
    required_skill_level = models.IntegerField(default=1)
    is_critical = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        db_table = "rotation_workstations"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["tenant", "department"]),
            models.Index(fields=["tenant", "line"]),
            models.Index(fields=["tenant", "risk_level"]),
            models.Index(fields=["tenant", "is_critical"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=(
                    models.Q(is_active=True)
                    & models.Q(is_deleted=False)
                    & ~models.Q(code="")
                ),
                name="unique_active_workstation_code_per_tenant",
            ),
            models.CheckConstraint(
                condition=models.Q(required_skill_level__gte=1)
                & models.Q(required_skill_level__lte=4),
                name="rotation_workstation_skill_level_range",
            ),
        ]

    def __str__(self):
        return self.name


class RotationSlot(BaseModel):
    plan = models.ForeignKey(RotationPlan, on_delete=models.CASCADE, related_name="slots")
    start_time = models.TimeField()
    end_time = models.TimeField()
    order = models.IntegerField()

    objects = TenantManager()

    class Meta:
        db_table = "rotation_slots"
        ordering = ["plan", "order"]
        indexes = [
            models.Index(fields=["tenant", "plan", "order"]),
            models.Index(fields=["tenant", "start_time"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "order"],
                condition=models.Q(is_active=True, is_deleted=False),
                name="unique_rotation_slot_order_per_plan",
            ),
            models.CheckConstraint(
                condition=models.Q(order__gte=0),
                name="rotation_slot_order_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="rotation_slot_start_before_end",
            ),
        ]

    def __str__(self):
        return f"{self.plan} slot {self.order}"


class RotationAssignment(BaseModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        MISSED = "missed", "Missed"
        REPLACED = "replaced", "Replaced"

    plan = models.ForeignKey(RotationPlan, on_delete=models.CASCADE, related_name="assignments")
    slot = models.ForeignKey(RotationSlot, on_delete=models.CASCADE, related_name="assignments")
    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="rotation_assignments",
    )
    workstation = models.ForeignKey(
        Workstation,
        on_delete=models.CASCADE,
        related_name="rotation_assignments",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    replacement_for = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replacements",
    )
    comment = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "rotation_assignments"
        ordering = ["plan", "slot__order", "workstation__name"]
        indexes = [
            models.Index(fields=["tenant", "plan"]),
            models.Index(fields=["tenant", "slot"]),
            models.Index(fields=["tenant", "employee"]),
            models.Index(fields=["tenant", "workstation"]),
            models.Index(fields=["tenant", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "slot", "employee"],
                condition=models.Q(is_active=True, is_deleted=False),
                name="unique_rotation_employee_per_slot",
            ),
            models.UniqueConstraint(
                fields=["tenant", "slot", "workstation"],
                condition=models.Q(is_active=True, is_deleted=False),
                name="unique_rotation_workstation_per_slot",
            ),
        ]

    def __str__(self):
        return f"{self.employee.full_name} -> {self.workstation.name}"


class RotationRule(BaseModel):
    class RuleType(models.TextChoices):
        MAX_CONSECUTIVE_SAME_STATION = "max_consecutive_same_station", "Max consecutive same station"
        REQUIRED_SKILL = "required_skill", "Required skill"
        AVOID_HIGH_RISK_REPETITION = "avoid_high_risk_repetition", "Avoid high risk repetition"
        MAX_HOURS_PER_STATION = "max_hours_per_station", "Max hours per station"
        REST_BETWEEN_HIGH_RISK = "rest_between_high_risk", "Rest between high risk"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        BLOCKING = "blocking", "Blocking"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    rule_type = models.CharField(max_length=50, choices=RuleType.choices)
    value_json = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.WARNING)
    is_enabled = models.BooleanField(default=True)

    objects = TenantManager()

    class Meta:
        db_table = "rotation_rules"
        ordering = ["rule_type", "name"]
        indexes = [
            models.Index(fields=["tenant", "rule_type"]),
            models.Index(fields=["tenant", "severity"]),
            models.Index(fields=["tenant", "is_enabled"]),
        ]

    def __str__(self):
        return self.name


class RotationViolation(BaseModel):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        BLOCKING = "blocking", "Blocking"

    plan = models.ForeignKey(RotationPlan, on_delete=models.CASCADE, related_name="violations")
    assignment = models.ForeignKey(
        RotationAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="violations",
    )
    rule = models.ForeignKey(
        RotationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="violations",
    )
    severity = models.CharField(max_length=20, choices=Severity.choices)
    message = models.TextField()
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_violations_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_violations",
    )

    objects = TenantManager()

    class Meta:
        db_table = "rotation_violations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "plan"]),
            models.Index(fields=["tenant", "severity"]),
            models.Index(fields=["tenant", "resolved"]),
        ]

    def __str__(self):
        return self.message[:80]


class RotationIncident(BaseModel):
    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        CRITICAL = "critical", "Critical"

    title = models.CharField(max_length=150)
    description = models.TextField()
    plan = models.ForeignKey(
        RotationPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )
    assignment = models.ForeignKey(
        RotationAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )
    reported_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_incidents_reported",
    )
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.LOW)
    occurred_at = models.DateTimeField()
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_incidents",
    )

    objects = TenantManager()

    class Meta:
        db_table = "rotation_incidents"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["tenant", "severity"]),
            models.Index(fields=["tenant", "resolved"]),
            models.Index(fields=["tenant", "occurred_at"]),
        ]

    def __str__(self):
        return self.title
