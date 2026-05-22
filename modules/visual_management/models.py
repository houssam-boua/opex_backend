# modules/visual_management/models.py
"""
Visual Management Module — OPEX SaaS
Andon System for real-time factory floor alerts.
"""
from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager

class ProductionLine(BaseModel):
    class Status(models.TextChoices):
        RUNNING     = "running",     "En marche"
        STOPPED     = "stopped",     "Arrêté"
        SLOW        = "slow",        "Ralenti"
        MAINTENANCE = "maintenance", "Maintenance"

    name       = models.CharField(max_length=150)
    site       = models.ForeignKey("accounts.Site", on_delete=models.SET_NULL, null=True, related_name="production_lines")
    department = models.ForeignKey("accounts.Department", on_delete=models.SET_NULL, null=True, related_name="production_lines")
    status     = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)

    objects = TenantManager()

    class Meta:
        db_table = "vm_production_lines"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AndonCall(BaseModel):
    class CallType(models.TextChoices):
        QUALITY    = "quality",    "Qualité"
        BREAKDOWN  = "breakdown",  "Panne"
        MATERIAL   = "material",   "Matière"
        SAFETY     = "safety",     "Sécurité"
        OTHER      = "other",      "Autre"

    class Severity(models.TextChoices):
        LOW      = "low",      "Faible"
        MEDIUM   = "medium",   "Moyen"
        HIGH     = "high",     "Élevé"
        CRITICAL = "critical", "Critique"

    class Status(models.TextChoices):
        OPEN         = "open",         "Ouvert"
        ACKNOWLEDGED = "acknowledged", "Pris en compte"
        RESOLVED     = "resolved",     "Résolu"

    line            = models.ForeignKey(ProductionLine, on_delete=models.CASCADE, related_name="andon_calls")
    operator        = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name="andon_calls_made")
    call_type       = models.CharField(max_length=20, choices=CallType.choices)
    severity        = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MEDIUM)
    description     = models.TextField(blank=True)
    status          = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    
    acknowledged_by = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="andon_calls_acknowledged")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at     = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "vm_andon_calls"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Andon {self.line.name} - {self.get_call_type_display()} ({self.get_status_display()})"

    def sync_to_shared_action(self):
        """Routes to shared.models.Action when severity is high or critical."""
        if self.severity in [self.Severity.HIGH, self.Severity.CRITICAL]:
            from shared.models import Action
            
            action_status_map = {
                "open": "open",
                "acknowledged": "in_progress",
                "resolved": "done"
            }
            
            action, _ = Action.objects.update_or_create(
                reference_id=self.id,
                module_source="andon",
                tenant=self.tenant,
                defaults={
                    "title": f"[Andon Alert] {self.line.name} - {self.get_call_type_display()}",
                    "description": self.description or f"Andon severity: {self.severity}",
                    "priority": "critical" if self.severity == self.Severity.CRITICAL else "high",
                    "status": action_status_map.get(self.status, "open"),
                    "assigned_to": self.acknowledged_by,
                    "created_by": self.created_by,
                    "action_type": "andon_call",
                }
            )
            return action
        return None


class AndonResponse(BaseModel):
    call = models.ForeignKey(AndonCall, on_delete=models.CASCADE, related_name="responses")
    responder = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name="andon_responses")
    response_time_seconds = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    action_taken = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "vm_andon_responses"
        ordering = ["-created_at"]


class AndonAlert(BaseModel):
    """System-generated alerts for SLA breaches."""
    call = models.ForeignKey(AndonCall, on_delete=models.CASCADE, related_name="alerts")
    message = models.TextField()
    is_resolved = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        db_table = "vm_andon_alerts"
        ordering = ["-created_at"]
