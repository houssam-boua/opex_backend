# modules/audits/models.py
"""
Audits Module — OPEX SaaS
Migrated from: app audit/backend/api/ (single barebones Audit model)

Upgraded to enterprise-grade:
  - AuditType reference data (internal, external, supplier, process, system)
  - AuditPlan for scheduling + recurrence
  - Audit with full lifecycle (planned → in_progress → completed → closed)
  - Finding for non-conformities discovered during audits
  - AuditChecklist with scored items
  All inherit BaseModel. Tenant-isolated. Comments/History via shared.models.
"""
from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


# ─────────────────────────────────────────────────────────────────────
# REFERENCE DATA
# ─────────────────────────────────────────────────────────────────────

class AuditType(BaseModel):
    """Type d'audit : interne, externe, fournisseur, processus, système."""
    class Kind(models.TextChoices):
        INTERNAL  = "internal",  "Interne"
        EXTERNAL  = "external",  "Externe"
        SUPPLIER  = "supplier",  "Fournisseur"
        PROCESS   = "process",   "Processus"
        SYSTEM    = "system",    "Système"

    name        = models.CharField(max_length=100)
    kind        = models.CharField(max_length=20, choices=Kind.choices)
    description = models.TextField(blank=True)
    color       = models.CharField(max_length=7, default="#3788d8")

    objects = TenantManager()

    class Meta:
        db_table = "audits_types"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"


# ─────────────────────────────────────────────────────────────────────
# AUDIT PLAN (Scheduling)
# ─────────────────────────────────────────────────────────────────────

class AuditPlan(BaseModel):
    """Programme d'audit annuel / trimestriel."""
    class Frequency(models.TextChoices):
        ONE_TIME    = "one_time",    "Ponctuel"
        MONTHLY     = "monthly",     "Mensuel"
        QUARTERLY   = "quarterly",   "Trimestriel"
        SEMI_ANNUAL = "semi_annual", "Semestriel"
        ANNUAL      = "annual",      "Annuel"

    title       = models.CharField(max_length=200)
    audit_type  = models.ForeignKey(AuditType, on_delete=models.CASCADE, related_name="plans")
    frequency   = models.CharField(
        max_length=20, choices=Frequency.choices, default=Frequency.ONE_TIME
    )
    year        = models.PositiveIntegerField(help_text="Année du programme d'audit")
    description = models.TextField(blank=True)
    responsible = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_plans_responsible"
    )

    objects = TenantManager()

    class Meta:
        db_table = "audits_plans"
        ordering = ["-year", "title"]

    def __str__(self):
        return f"{self.title} ({self.year})"


# ─────────────────────────────────────────────────────────────────────
# AUDIT (core entity)
# ─────────────────────────────────────────────────────────────────────

class Audit(BaseModel):
    """Audit individuel avec cycle de vie complet."""
    class Status(models.TextChoices):
        PLANNED     = "planned",     "Planifié"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED   = "completed",   "Terminé"
        CLOSED      = "closed",      "Clôturé"
        CANCELLED   = "cancelled",   "Annulé"

    class Priority(models.TextChoices):
        LOW    = "low",    "Basse"
        MEDIUM = "medium", "Moyenne"
        HIGH   = "high",   "Haute"

    plan          = models.ForeignKey(
        AuditPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="audits"
    )
    audit_type    = models.ForeignKey(AuditType, on_delete=models.CASCADE, related_name="audits")
    title         = models.CharField(max_length=200)
    reference     = models.CharField(max_length=50, blank=True, help_text="Référence interne (ex: AUD-2026-001)")
    description   = models.TextField(blank=True)
    zone          = models.CharField(max_length=255, blank=True, help_text="Zone / Département audité")
    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    priority      = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    planned_date  = models.DateField()
    actual_date   = models.DateField(null=True, blank=True)
    lead_auditor  = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audits_as_lead"
    )
    co_auditors   = models.ManyToManyField(
        "accounts.Employee", related_name="audits_as_co", blank=True
    )
    auditee       = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audits_as_auditee",
        help_text="Responsable du processus audité"
    )
    score         = models.IntegerField(null=True, blank=True, help_text="Score global 0-100")
    conclusion    = models.TextField(blank=True)
    completed_at  = models.DateTimeField(null=True, blank=True)
    closed_at     = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "audits_audits"
        ordering = ["-planned_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "reference"],
                condition=models.Q(reference__gt=""),
                name="unique_audit_ref_per_tenant"
            )
        ]

    def __str__(self):
        return f"{self.reference or self.title} — {self.get_status_display()}"

    @property
    def findings_count(self):
        return self.findings.count()

    @property
    def open_findings_count(self):
        return self.findings.exclude(status="closed").count()


# ─────────────────────────────────────────────────────────────────────
# CHECKLIST (scored items during audit)
# ─────────────────────────────────────────────────────────────────────

class AuditChecklistItem(BaseModel):
    """Élément de checklist évalué pendant l'audit."""
    class Rating(models.TextChoices):
        CONFORME     = "conforme",     "Conforme"
        OBSERVATION  = "observation",  "Observation"
        NON_CONFORME = "non_conforme", "Non conforme"
        NA           = "na",           "Non applicable"

    audit       = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="checklist_items")
    question    = models.CharField(max_length=500)
    category    = models.CharField(max_length=100, blank=True, help_text="Rubrique / chapitre ISO")
    rating      = models.CharField(max_length=20, choices=Rating.choices, default=Rating.NA)
    evidence    = models.TextField(blank=True, help_text="Preuves / observations de l'auditeur")
    photo       = models.ImageField(upload_to="audits/checklist/", blank=True, null=True)
    order       = models.PositiveIntegerField(default=0)

    objects = TenantManager()

    class Meta:
        db_table = "audits_checklist_items"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.question[:60]} — {self.get_rating_display()}"


# ─────────────────────────────────────────────────────────────────────
# FINDINGS (non-conformities, observations)
# ─────────────────────────────────────────────────────────────────────

class Finding(BaseModel):
    """
    Constat / Non-conformité découverte pendant un audit.
    Corrective actions link to shared.models.Action.
    """
    class Severity(models.TextChoices):
        OBSERVATION     = "observation",     "Observation"
        MINOR           = "minor",           "Non-conformité mineure"
        MAJOR           = "major",           "Non-conformité majeure"
        CRITICAL        = "critical",        "Non-conformité critique"
        IMPROVEMENT     = "improvement",     "Piste d'amélioration"

    class FindingStatus(models.TextChoices):
        OPEN            = "open",            "Ouvert"
        ACTION_PLANNED  = "action_planned",  "Action planifiée"
        IN_PROGRESS     = "in_progress",     "En cours de traitement"
        PENDING_REVIEW  = "pending_review",  "En attente de vérification"
        CLOSED          = "closed",          "Clôturé"

    audit           = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="findings")
    checklist_item  = models.ForeignKey(
        AuditChecklistItem, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="findings"
    )
    title           = models.CharField(max_length=300)
    description     = models.TextField()
    severity        = models.CharField(max_length=20, choices=Severity.choices)
    status          = models.CharField(
        max_length=20, choices=FindingStatus.choices, default=FindingStatus.OPEN
    )
    clause_reference = models.CharField(
        max_length=50, blank=True, help_text="Référence norme (ex: ISO 9001:2015 §7.1.3)"
    )
    assigned_to     = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_findings_assigned"
    )
    due_date        = models.DateField(null=True, blank=True)
    resolution      = models.TextField(blank=True)
    resolved_at     = models.DateTimeField(null=True, blank=True)
    verified_by     = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_findings_verified"
    )
    verified_at     = models.DateTimeField(null=True, blank=True)
    photo           = models.ImageField(upload_to="audits/findings/", blank=True, null=True)

    objects = TenantManager()

    class Meta:
        db_table = "audits_findings"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_severity_display()})"

    @property
    def is_overdue(self):
        from django.utils import timezone
        if self.due_date and self.status not in ["closed"]:
            return timezone.now().date() > self.due_date
        return False
