# modules/iso9001/models.py
"""
ISO 9001 Module — OPEX SaaS
Compliance and document control system.
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from shared.base import BaseModel
from accounts.managers import TenantManager

class ISO9001Clause(BaseModel):
    clause_number = models.CharField(max_length=20)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self", 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name="subclauses"
    )

    objects = TenantManager()

    class Meta:
        db_table = "iso_clauses"
        ordering = ["clause_number"]

    def __str__(self):
        return f"{self.clause_number} - {self.title}"


class ComplianceAssessment(BaseModel):
    class Status(models.TextChoices):
        COMPLIANT     = "compliant",     "Conforme"
        PARTIAL       = "partial",       "Partiellement Conforme"
        NON_COMPLIANT = "non_compliant", "Non Conforme"

    clause = models.ForeignKey(ISO9001Clause, on_delete=models.CASCADE, related_name="assessments")
    assessor = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name="iso_assessments")
    score = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    status = models.CharField(max_length=20, choices=Status.choices)
    evidence = models.TextField(blank=True)
    date = models.DateField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        db_table = "iso_compliance_assessments"
        ordering = ["-date"]

    def __str__(self):
        return f"Assessment {self.clause.clause_number} ({self.score}%)"


class NonConformity(BaseModel):
    class Severity(models.TextChoices):
        MINOR    = "minor",    "Mineure"
        MAJOR    = "major",    "Majeure"
        CRITICAL = "critical", "Critique"

    class Status(models.TextChoices):
        OPEN      = "open",      "Ouvert"
        IN_REVIEW = "in_review", "En revue"
        CLOSED    = "closed",    "Fermé"

    clause = models.ForeignKey(ISO9001Clause, on_delete=models.CASCADE, related_name="non_conformities")
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MINOR)
    detected_by = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name="nc_detected")
    detected_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    objects = TenantManager()

    class Meta:
        db_table = "iso_non_conformities"
        ordering = ["-detected_at"]

    def __str__(self):
        return f"NC {self.clause.clause_number} - {self.get_severity_display()}"


class CorrectiveAction(BaseModel):
    class Status(models.TextChoices):
        OPEN        = "open",        "Ouvert"
        IN_PROGRESS = "in_progress", "En cours"
        DONE        = "done",        "Terminé"

    non_conformity = models.ForeignKey(NonConformity, on_delete=models.CASCADE, related_name="corrective_actions")
    description = models.TextField()
    owner = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name="iso_corrective_actions")
    deadline = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    verified_by = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="iso_actions_verified")

    objects = TenantManager()

    class Meta:
        db_table = "iso_corrective_actions"
        ordering = ["deadline"]

    def sync_to_shared_action(self):
        from shared.models import Action
        
        status_map = {
            "open": "open",
            "in_progress": "in_progress",
            "done": "done"
        }
        
        priority_map = {
            NonConformity.Severity.MINOR: "medium",
            NonConformity.Severity.MAJOR: "high",
            NonConformity.Severity.CRITICAL: "critical"
        }
        
        priority = priority_map.get(self.non_conformity.severity, "medium")

        action, _ = Action.objects.update_or_create(
            reference_id=self.id,
            module_source="iso9001",
            tenant=self.tenant,
            defaults={
                "title": f"[ISO Corrective] NC {self.non_conformity.clause.clause_number}",
                "description": self.description,
                "priority": priority,
                "status": status_map.get(self.status, "open"),
                "assigned_to": self.owner,
                "due_date": self.deadline,
                "created_by": self.created_by,
                "action_type": "iso_corrective_action",
            }
        )
        return action


class ISODocument(BaseModel):
    title = models.CharField(max_length=255)
    clause = models.ForeignKey(ISO9001Clause, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    file_path = models.FileField(upload_to="iso_documents/")
    version = models.CharField(max_length=20, default="1.0")
    valid_from = models.DateField()
    valid_until = models.DateField()
    uploaded_by = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name="uploaded_iso_docs")

    objects = TenantManager()

    class Meta:
        db_table = "iso_documents"
        ordering = ["-valid_from"]

    def __str__(self):
        return f"{self.title} v{self.version}"


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY BRIDGE (0002 — Additive, immutable)
# Supports the React/Supabase frontend's Session → Question → Response
# flow while routing non-compliant findings into the enterprise
# NonConformity → CorrectiveAction → CAPA governance backbone.
# ═══════════════════════════════════════════════════════════════════════

class ISO9001EvaluationSession(BaseModel):
    """Legacy-compatible audit session container."""
    class Status(models.TextChoices):
        DRAFT       = "draft",       "Brouillon"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED   = "completed",   "Terminé"

    title = models.CharField(max_length=255)
    evaluator = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, related_name="iso_evaluation_sessions"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    global_score = models.FloatField(default=0.0, help_text="Computed score 0-100 on session completion")

    objects = TenantManager()

    class Meta:
        db_table = "iso_evaluation_sessions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) — {self.global_score}%"


class ISO9001Question(BaseModel):
    """Legacy frontend question structure bridged to enterprise clauses."""
    clause = models.ForeignKey(
        ISO9001Clause, on_delete=models.CASCADE,
        related_name="questions",
        help_text="Bridge: links legacy questions to enterprise clause hierarchy"
    )
    question_text = models.TextField()

    objects = TenantManager()

    class Meta:
        db_table = "iso_questions"
        ordering = ["clause__clause_number", "created_at"]

    def __str__(self):
        return f"[{self.clause.clause_number}] {self.question_text[:80]}"


class ISO9001Response(BaseModel):
    """Legacy response engine — one answer per question per session."""
    class ResponseStatus(models.TextChoices):
        COMPLIANT     = "compliant",     "Conforme"
        PARTIAL       = "partial",       "Partiellement Conforme"
        NON_COMPLIANT = "non_compliant", "Non Conforme"
        NA            = "n_a",           "Non Applicable"

    session = models.ForeignKey(
        ISO9001EvaluationSession, on_delete=models.CASCADE,
        related_name="responses"
    )
    question = models.ForeignKey(
        ISO9001Question, on_delete=models.CASCADE,
        related_name="responses"
    )
    response_status = models.CharField(max_length=20, choices=ResponseStatus.choices)
    evidence_notes = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "iso_responses"
        unique_together = ("session", "question")

    def __str__(self):
        return f"Response {self.question} → {self.get_response_status_display()}"
