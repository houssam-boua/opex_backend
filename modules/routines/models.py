from django.db import models

from accounts.managers import TenantManager
from shared.base import BaseModel


class RoutineTemplate(BaseModel):
    class RoutineType(models.TextChoices):
        DAILY_STARTUP = "daily_startup", "Daily startup"
        OK_DEMARRAGE = "ok_demarrage", "OK demarrage"
        SAFETY_WALK = "safety_walk", "Safety walk"
        QUALITY_CHECK = "quality_check", "Quality check"
        MAINTENANCE_CHECK = "maintenance_check", "Maintenance check"
        SUPERVISOR_ROUTINE = "supervisor_routine", "Supervisor routine"
        OTHER = "other", "Other"

    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        PER_SHIFT = "per_shift", "Per shift"
        AD_HOC = "ad_hoc", "Ad hoc"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        ARCHIVED = "archived", "Archived"

    class Version(models.TextChoices):
        V1_0 = "v1.0", "v1.0"
        V1_1 = "v1.1", "v1.1"
        V2_0 = "v2.0", "v2.0"

    code = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    video_url = models.URLField(max_length=500, blank=True)
    routine_type = models.CharField(max_length=30, choices=RoutineType.choices, default=RoutineType.OTHER)
    frequency = models.CharField(max_length=20, choices=Frequency.choices)
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_templates",
    )
    line = models.CharField(max_length=150, blank=True)
    workstation_name = models.CharField(max_length=150, blank=True)
    owner = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_templates_owned",
    )
    is_mandatory = models.BooleanField(default=True)
    estimated_duration_min = models.IntegerField(default=10)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    version = models.CharField(max_length=10, choices=Version.choices, default=Version.V1_0)
    requires_validation = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        db_table = "routine_templates"
        ordering = ["title"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "routine_type"]),
            models.Index(fields=["tenant", "frequency"]),
            models.Index(fields=["tenant", "department"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=(
                    models.Q(is_active=True)
                    & models.Q(is_deleted=False)
                    & ~models.Q(code="")
                ),
                name="unique_active_routine_code_per_tenant",
            ),
            models.CheckConstraint(
                condition=models.Q(estimated_duration_min__gt=0),
                name="routine_template_duration_positive",
            ),
        ]

    def __str__(self):
        return self.title


class RoutineStep(BaseModel):
    class StepType(models.TextChoices):
        YES_NO = "yes_no", "Yes/no"
        NUMERIC = "numeric", "Numeric"
        TEXT = "text", "Text"
        PHOTO_REQUIRED = "photo_required", "Photo required"
        SIGNATURE = "signature", "Signature"
        CHECKLIST = "checklist", "Checklist"

    template = models.ForeignKey(RoutineTemplate, on_delete=models.CASCADE, related_name="steps")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    step_type = models.CharField(max_length=20, choices=StepType.choices, default=StepType.YES_NO)
    expected_value = models.CharField(max_length=150, blank=True)
    min_value = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    max_value = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    order = models.IntegerField()
    is_required = models.BooleanField(default=True)
    triggers_action_on_fail = models.BooleanField(default=True)
    is_ok_demarrage = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        db_table = "routine_steps"
        ordering = ["order"]
        indexes = [
            models.Index(fields=["tenant", "template", "order"]),
            models.Index(fields=["tenant", "step_type"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["template", "order"], name="unique_routine_step_order_per_template"),
            models.CheckConstraint(condition=models.Q(order__gte=0), name="routine_step_order_non_negative"),
        ]

    def __str__(self):
        return self.title


class RoutineExecution(BaseModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        MISSED = "missed", "Missed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Shift(models.TextChoices):
        MORNING = "morning", "Morning"
        AFTERNOON = "afternoon", "Afternoon"
        NIGHT = "night", "Night"
        FULL_DAY = "full_day", "Full day"
        UNKNOWN = "unknown", "Unknown"

    class GlobalResult(models.TextChoices):
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        PARTIAL = "partial", "Partial"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    template = models.ForeignKey(RoutineTemplate, on_delete=models.CASCADE, related_name="executions")
    executed_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_executions",
    )
    scheduled_for = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    shift = models.CharField(max_length=20, choices=Shift.choices, default=Shift.UNKNOWN)
    global_result = models.CharField(max_length=20, choices=GlobalResult.choices, default=GlobalResult.NOT_APPLICABLE)
    notes = models.TextField(blank=True)
    validated_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_executions_validated",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    validator_comment = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "routine_executions"
        ordering = ["-scheduled_for"]
        indexes = [
            models.Index(fields=["tenant", "scheduled_for"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "executed_by"]),
            models.Index(fields=["tenant", "template"]),
        ]

    def __str__(self):
        return f"{self.template.title} - {self.status}"


class RoutineStepResponse(BaseModel):
    class Result(models.TextChoices):
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    execution = models.ForeignKey(RoutineExecution, on_delete=models.CASCADE, related_name="responses")
    step = models.ForeignKey(RoutineStep, on_delete=models.CASCADE, related_name="responses")
    result = models.CharField(max_length=20, choices=Result.choices)
    value_text = models.TextField(blank=True)
    value_number = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    comment = models.TextField(blank=True)
    responded_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_step_responses",
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_step_responses",
    )

    objects = TenantManager()

    class Meta:
        db_table = "routine_step_responses"
        ordering = ["step__order"]
        indexes = [
            models.Index(fields=["tenant", "execution"]),
            models.Index(fields=["tenant", "step"]),
            models.Index(fields=["tenant", "result"]),
            models.Index(fields=["tenant", "responded_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["execution", "step"], name="unique_routine_response_per_step"),
        ]

    def __str__(self):
        return f"{self.step.title} - {self.result}"


class RoutineDeviation(BaseModel):
    class Severity(models.TextChoices):
        MINOR = "minor", "Minor"
        MAJOR = "major", "Major"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACTION_REQUIRED = "action_required", "Action required"
        RESOLVED = "resolved", "Resolved"
        VERIFIED = "verified", "Verified"
        CLOSED = "closed", "Closed"

    execution = models.ForeignKey(RoutineExecution, on_delete=models.CASCADE, related_name="deviations")
    response = models.ForeignKey(
        RoutineStepResponse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deviations",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MINOR)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    detected_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_deviations_detected",
    )
    owner = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_deviations_owned",
    )
    due_date = models.DateField(null=True, blank=True)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_deviations",
    )
    verified_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routine_deviations_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "routine_deviations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "severity"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "owner"]),
            models.Index(fields=["tenant", "due_date"]),
        ]

    def __str__(self):
        return self.title
