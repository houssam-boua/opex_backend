from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


class PokaYokeDevice(BaseModel):
    class DeviceType(models.TextChoices):
        PHYSICAL_FIXTURE = "physical_fixture", "Physical fixture"
        SENSOR = "sensor", "Sensor"
        BARCODE_SCAN = "barcode_scan", "Barcode scan"
        CHECKLIST_CONTROL = "checklist_control", "Checklist control"
        SOFTWARE_VALIDATION = "software_validation", "Software validation"
        VISUAL_CONTROL = "visual_control", "Visual control"
        INTERLOCK = "interlock", "Interlock"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        UNDER_REVIEW = "under_review", "Under review"
        RETIRED = "retired", "Retired"

    class Criticality(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    device_type = models.CharField(max_length=30, choices=DeviceType.choices, default=DeviceType.OTHER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_devices",
    )
    machine = models.ForeignKey(
        "tpm.Machine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_devices",
    )
    workstation_name = models.CharField(max_length=150, blank=True)
    process_name = models.CharField(max_length=150, blank=True)
    owner = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_devices_owned",
    )
    criticality = models.CharField(max_length=20, choices=Criticality.choices, default=Criticality.MEDIUM)
    failure_mode = models.TextField(blank=True)
    prevention_method = models.TextField(blank=True)
    detection_method = models.TextField(blank=True)
    automatic_detection = models.BooleanField(default=False)
    standard_reference = models.CharField(max_length=150, blank=True)
    installed_date = models.DateField(null=True, blank=True)
    verification_interval_days = models.IntegerField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    next_verification_due = models.DateField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "poka_yoke_devices"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "device_type"]),
            models.Index(fields=["tenant", "criticality"]),
            models.Index(fields=["tenant", "department"]),
            models.Index(fields=["tenant", "next_verification_due"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=(
                    models.Q(is_active=True)
                    & models.Q(is_deleted=False)
                    & ~models.Q(code="")
                ),
                name="unique_active_poka_yoke_device_code_per_tenant",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(verification_interval_days__isnull=True)
                    | models.Q(verification_interval_days__gt=0)
                ),
                name="poka_yoke_verification_interval_positive",
            ),
        ]

    def __str__(self):
        return self.name


class PokaYokeCheck(BaseModel):
    class Result(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    device = models.ForeignKey(PokaYokeDevice, on_delete=models.CASCADE, related_name="checks")
    checked_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_checks",
    )
    checked_at = models.DateTimeField()
    result = models.CharField(max_length=20, choices=Result.choices)
    observation = models.TextField(blank=True)
    measured_value = models.CharField(max_length=150, blank=True)
    expected_value = models.CharField(max_length=150, blank=True)
    requires_action = models.BooleanField(default=False)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_checks",
    )

    objects = TenantManager()

    class Meta:
        db_table = "poka_yoke_checks"
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["tenant", "device"]),
            models.Index(fields=["tenant", "result"]),
            models.Index(fields=["tenant", "checked_at"]),
            models.Index(fields=["tenant", "requires_action"]),
        ]

    def __str__(self):
        return f"{self.device.name} - {self.result}"


class PokaYokeDefect(BaseModel):
    class Severity(models.TextChoices):
        MINOR = "minor", "Minor"
        MAJOR = "major", "Major"
        CRITICAL = "critical", "Critical"

    class DefectSource(models.TextChoices):
        DEVICE_FAILED = "device_failed", "Device failed"
        DEVICE_BYPASSED = "device_bypassed", "Device bypassed"
        MISSING_POKA_YOKE = "missing_poka_yoke", "Missing poka-yoke"
        WRONG_STANDARD = "wrong_standard", "Wrong standard"
        HUMAN_ERROR = "human_error", "Human error"
        PROCESS_DRIFT = "process_drift", "Process drift"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        INVESTIGATING = "investigating", "Investigating"
        ACTION_REQUIRED = "action_required", "Action required"
        RESOLVED = "resolved", "Resolved"
        VERIFIED = "verified", "Verified"
        CLOSED = "closed", "Closed"

    device = models.ForeignKey(
        PokaYokeDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="defects",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    detected_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_defects_detected",
    )
    detected_at = models.DateTimeField()
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MINOR)
    defect_source = models.CharField(max_length=30, choices=DefectSource.choices, default=DefectSource.OTHER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_defects",
    )
    verified_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_defects_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "poka_yoke_defects"
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["tenant", "severity"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "detected_at"]),
            models.Index(fields=["tenant", "defect_source"]),
        ]

    def __str__(self):
        return self.title


class PokaYokeImprovement(BaseModel):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        IN_PROGRESS = "in_progress", "In progress"
        IMPLEMENTED = "implemented", "Implemented"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    device = models.ForeignKey(
        PokaYokeDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="improvements",
    )
    defect = models.ForeignKey(
        PokaYokeDefect,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="improvements",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    proposed_by = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_improvements_proposed",
    )
    owner = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_improvements_owned",
    )
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    due_date = models.DateField(null=True, blank=True)
    linked_action = models.ForeignKey(
        "shared.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="poka_yoke_improvements",
    )

    objects = TenantManager()

    class Meta:
        db_table = "poka_yoke_improvements"
        ordering = ["due_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "priority"]),
            models.Index(fields=["tenant", "due_date"]),
            models.Index(fields=["tenant", "owner"]),
        ]

    def __str__(self):
        return self.title
