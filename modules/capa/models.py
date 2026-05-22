# modules/capa/models.py
"""
CAPA Module (Corrective and Preventive Actions)
Translates legacy React "Action" into OPEX SaaS standard.

Rules:
- CapaTicket is the parent container tracking problem, root cause, 5M, efficiency.
- Actual tasks are synced to shared.models.Action (module_source="capa").
- Uses Employee for operational ownership. Inherits BaseModel.
"""
from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


class CapaTicket(BaseModel):
    """
    Parent container for a CAPA.
    Maps to the React frontend's 'Action' interface.
    """
    class CapaType(models.TextChoices):
        CORRECTIVE = "corrective", "Corrective"
        PREVENTIVE = "preventive", "Préventive"

    class CapaStatus(models.TextChoices):
        IDENTIFIED  = "identified",  "Identifiée"
        PLANNED     = "planned",     "Prévue"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED   = "completed",   "Finalisée"
        LATE        = "late",        "En retard"
        VALIDATED   = "validated",   "Validée"
        ARCHIVED    = "archived",    "Archivée"

    class Urgency(models.TextChoices):
        LOW    = "low",    "Faible"
        MEDIUM = "medium", "Moyen"
        HIGH   = "high",   "Élevé"

    class Category5M(models.TextChoices):
        MAIN_OEUVRE = "main_oeuvre", "Main d'œuvre"
        MATIERE     = "matiere",     "Matière"
        METHODE     = "methode",     "Méthode"
        MILIEU      = "milieu",      "Milieu"
        MACHINE     = "machine",     "Machine"

    title       = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    problem     = models.TextField(blank=True)
    root_cause  = models.TextField(blank=True)
    
    capa_type   = models.CharField(max_length=20, choices=CapaType.choices, default=CapaType.CORRECTIVE)
    status      = models.CharField(max_length=20, choices=CapaStatus.choices, default=CapaStatus.IDENTIFIED)
    urgency     = models.CharField(max_length=20, choices=Urgency.choices, default=Urgency.MEDIUM)
    category_5m = models.CharField(max_length=20, choices=Category5M.choices, blank=True, null=True)
    
    pilot       = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="capa_piloted"
    )
    
    # Context references (can be UUIDs linking to GembaZone, etc. - kept generic for frontend mapping)
    service_id  = models.UUIDField(null=True, blank=True)
    line_id     = models.UUIDField(null=True, blank=True)
    team_id     = models.UUIDField(null=True, blank=True)
    post_id     = models.UUIDField(null=True, blank=True)

    due_date    = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)

    progress_percent   = models.IntegerField(default=0)
    efficiency_percent = models.IntegerField(null=True, blank=True)
    is_effective       = models.BooleanField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "capa_tickets"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
    
    def sync_to_shared_action(self):
        """
        Synchronise le CapaTicket vers un shared.models.Action.
        Honor la règle "The actual tasks MUST be routed to shared.models.Action".
        """
        from shared.models import Action
        
        priority_map = {
            "low": "low",
            "medium": "medium",
            "high": "high"
        }
        status_map = {
            "identified": "open",
            "planned": "open",
            "in_progress": "in_progress",
            "completed": "done",
            "late": "in_progress",
            "validated": "done",
            "archived": "done"
        }

        action, created = Action.objects.update_or_create(
            reference_id=self.id,
            module_source="capa",
            tenant=self.tenant,
            defaults={
                "title": self.title,
                "description": self.description,
                "priority": priority_map.get(self.urgency, "medium"),
                "status": status_map.get(self.status, "open"),
                "assigned_to": self.pilot,
                "due_date": self.due_date,
                "closed_at": self.completed_at or self.validated_at,
                "created_by": self.created_by,
                "action_type": self.capa_type,
            }
        )
        return action
