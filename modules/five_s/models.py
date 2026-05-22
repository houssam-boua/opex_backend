# modules/five_s/models.py
"""
5S Module — OPEX SaaS
Workplace Excellence & Discipline Engine
"""
from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager

class SCategory(models.TextChoices):
    SEIRI    = "seiri",    "1S - Trier (Seiri)"
    SEITON   = "seiton",   "2S - Ranger (Seiton)"
    SEISO    = "seiso",    "3S - Nettoyer (Seiso)"
    SEIKETSU = "seiketsu", "4S - Standardiser (Seiketsu)"
    SHITSUKE = "shitsuke", "5S - Suivre (Shitsuke)"

class AuditQuestion(BaseModel):
    category = models.CharField(max_length=20, choices=SCategory.choices)
    text     = models.CharField(max_length=255)
    order    = models.IntegerField(default=0)

    objects = TenantManager()

    class Meta:
        db_table = "five_s_questions"
        ordering = ["category", "order"]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.text}"


class AuditSession5S(BaseModel):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED   = "completed",   "Terminé"

    zone_id  = models.CharField(max_length=100)
    auditor  = models.ForeignKey("accounts.Employee", on_delete=models.CASCADE, related_name="audits_5s")
    status   = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    
    # Calculated Scores (0-100 or actual points)
    score_seiri    = models.FloatField(default=0.0)
    score_seiton   = models.FloatField(default=0.0)
    score_seiso    = models.FloatField(default=0.0)
    score_seiketsu = models.FloatField(default=0.0)
    score_shitsuke = models.FloatField(default=0.0)
    total_score    = models.FloatField(default=0.0)

    completed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "five_s_audit_sessions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Audit 5S - Zone {self.zone_id} ({self.total_score}%)"
    
    def calculate_scores(self):
        """
        Recalculates scores based on responses.
        Called when session is completed or updated.
        """
        responses = self.responses.select_related("question")
        
        scores = {
            SCategory.SEIRI: [],
            SCategory.SEITON: [],
            SCategory.SEISO: [],
            SCategory.SEIKETSU: [],
            SCategory.SHITSUKE: []
        }
        
        for r in responses:
            scores[r.question.category].append(r.score)
            
        def avg(lst):
            return sum(lst) / len(lst) if lst else 0.0

        self.score_seiri = avg(scores[SCategory.SEIRI])
        self.score_seiton = avg(scores[SCategory.SEITON])
        self.score_seiso = avg(scores[SCategory.SEISO])
        self.score_seiketsu = avg(scores[SCategory.SEIKETSU])
        self.score_shitsuke = avg(scores[SCategory.SHITSUKE])
        
        self.total_score = (
            self.score_seiri + self.score_seiton + 
            self.score_seiso + self.score_seiketsu + 
            self.score_shitsuke
        ) / 5.0
        
        self.save(update_fields=[
            "score_seiri", "score_seiton", "score_seiso", 
            "score_seiketsu", "score_shitsuke", "total_score"
        ])


class AuditResponse(BaseModel):
    session  = models.ForeignKey(AuditSession5S, on_delete=models.CASCADE, related_name="responses")
    question = models.ForeignKey(AuditQuestion, on_delete=models.CASCADE)
    score    = models.FloatField(default=0.0, help_text="Note sur 100")
    comment  = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "five_s_audit_responses"
        unique_together = ("session", "question")


class Anomaly5S(BaseModel):
    """
    Anomalie identifiée durant un audit 5S.
    Syncs to shared.models.Action
    """
    class Priority(models.TextChoices):
        HAUTE   = "haute",   "Haute"
        MOYENNE = "moyenne", "Moyenne"
        BASSE   = "basse",   "Basse"

    class Status(models.TextChoices):
        NOUVEAU  = "nouveau",  "Nouveau"
        EN_COURS = "en_cours", "En cours"
        TERMINE  = "termine",  "Terminé"

    session     = models.ForeignKey(AuditSession5S, on_delete=models.CASCADE, related_name="anomalies")
    description = models.TextField()
    priority    = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MOYENNE)
    status      = models.CharField(max_length=20, choices=Status.choices, default=Status.NOUVEAU)
    assigned_to = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True)
    due_date    = models.DateField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "five_s_anomalies"

    def sync_to_shared_action(self):
        from shared.models import Action
        
        priority_map = {
            "haute": "high",
            "moyenne": "medium",
            "basse": "low"
        }
        status_map = {
            "nouveau": "open",
            "en_cours": "in_progress",
            "termine": "done"
        }

        action, _ = Action.objects.update_or_create(
            reference_id=self.id,
            module_source="5s",
            tenant=self.tenant,
            defaults={
                "title": f"[5S Anomaly] Zone {self.session.zone_id}",
                "description": self.description,
                "priority": priority_map.get(self.priority, "medium"),
                "status": status_map.get(self.status, "open"),
                "assigned_to": self.assigned_to,
                "due_date": self.due_date,
                "created_by": self.created_by,
                "action_type": "5s_anomaly",
            }
        )
        return action
