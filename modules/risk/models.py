# modules/risk/models.py
"""
Risk Module — OPEX SaaS
Predictive enterprise control layer models.
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from shared.base import BaseModel
from accounts.managers import TenantManager


class RiskCategory(BaseModel):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    color_code = models.CharField(max_length=20, default="#808080")

    objects = TenantManager()

    class Meta:
        db_table = "risk_categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Risk(BaseModel):
    class Severity(models.TextChoices):
        LOW      = "low",      "Faible"
        MEDIUM   = "medium",   "Moyen"
        HIGH     = "high",     "Élevé"
        CRITICAL = "critical", "Critique"

    class Status(models.TextChoices):
        OPEN      = "open",      "Ouvert"
        MITIGATED = "mitigated", "Atténué"
        CLOSED    = "closed",    "Fermé"
        ACCEPTED  = "accepted",  "Accepté"

    title       = models.CharField(max_length=255)
    description = models.TextField()
    category    = models.ForeignKey(RiskCategory, on_delete=models.SET_NULL, null=True, related_name="risks")
    severity    = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MEDIUM)
    likelihood  = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], default=1)
    impact      = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], default=1)
    risk_score  = models.IntegerField(default=1) # Persisted in DB, calculated by Service
    owner       = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_risks")
    status      = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    objects = TenantManager()

    class Meta:
        db_table = "risk_risks"
        ordering = ["-risk_score"]

    def __str__(self):
        return f"[{self.severity}] {self.title} (Score: {self.risk_score})"


class RiskAssessment(BaseModel):
    risk          = models.ForeignKey(Risk, on_delete=models.CASCADE, related_name="assessments")
    assessor      = models.ForeignKey("accounts.Employee", on_delete=models.CASCADE)
    date          = models.DateField(auto_now_add=True)
    notes         = models.TextField(blank=True)
    updated_score = models.IntegerField()

    objects = TenantManager()

    class Meta:
        db_table = "risk_assessments"
        ordering = ["-created_at"]


class RiskMitigationAction(BaseModel):
    class Status(models.TextChoices):
        OPEN        = "open",        "Ouvert"
        IN_PROGRESS = "in_progress", "En cours"
        DONE        = "done",        "Terminé"

    risk        = models.ForeignKey(Risk, on_delete=models.CASCADE, related_name="mitigations")
    description = models.TextField()
    owner       = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True)
    deadline    = models.DateField()
    status      = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    objects = TenantManager()

    class Meta:
        db_table = "risk_mitigation_actions"
        ordering = ["deadline"]

    def sync_to_shared_action(self):
        from shared.models import Action
        
        priority_map = {
            Risk.Severity.LOW: "low",
            Risk.Severity.MEDIUM: "medium",
            Risk.Severity.HIGH: "high",
            Risk.Severity.CRITICAL: "critical"
        }
        status_map = {
            "open": "open",
            "in_progress": "in_progress",
            "done": "done"
        }

        # Severity mapping: HIGH -> High priority, CRITICAL -> Immediate escalation 
        # (For CRITICAL, could add special flag, but 'critical' priority is enough here)
        action_priority = priority_map.get(self.risk.severity, "medium")

        action, _ = Action.objects.update_or_create(
            reference_id=self.id,
            module_source="risk",
            tenant=self.tenant,
            defaults={
                "title": f"[Risk Mitigation] {self.risk.title}",
                "description": self.description,
                "priority": action_priority,
                "status": status_map.get(self.status, "open"),
                "assigned_to": self.owner,
                "due_date": self.deadline,
                "created_by": self.created_by,
                "action_type": "risk_mitigation",
            }
        )
        return action


class RiskHistory(BaseModel):
    risk       = models.ForeignKey(Risk, on_delete=models.CASCADE, related_name="history")
    old_score  = models.IntegerField()
    new_score  = models.IntegerField()
    changed_by = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        db_table = "risk_history"
        ordering = ["-changed_at"]
