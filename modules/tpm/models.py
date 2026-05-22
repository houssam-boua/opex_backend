# modules/tpm/models.py
from django.db import models
from django.utils import timezone
from shared.base import BaseModel
from accounts.managers import TenantManager

# ==========================================
# 1. MACHINES
# ==========================================
class Machine(BaseModel):
    ETAT_CHOICES = [
        ('MARCHE', 'En Marche'),
        ('ARRET', "À l'arrêt"),
        ('MAINTENANCE', 'En Maintenance'),
    ]
    
    code = models.CharField(max_length=10)
    nom = models.CharField(max_length=100)
    emplacement = models.CharField(max_length=50)
    cadence_theorique = models.PositiveIntegerField()
    date_installation = models.DateField(null=True, blank=True)
    etat = models.CharField(max_length=20, choices=ETAT_CHOICES, default='MARCHE')
    
    objects = TenantManager()

    class Meta:
        db_table = "tpm_machines"
        unique_together = ("tenant", "code")

    def __str__(self):
        return f"{self.code} - {self.nom}"


# ==========================================
# 2. PRODUCTION
# ==========================================
class TypeDefaut(BaseModel):
    libelle = models.CharField(max_length=50)
    objects = TenantManager()
    class Meta:
        db_table = "tpm_type_defaut"

class ProductionReport(BaseModel):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='rapports')
    operateur = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name='rapports_saisis_tpm')
    validateur = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name='rapports_valides_tpm')
    date = models.DateField(default=timezone.now)
    temps_ouverture = models.DecimalField(max_digits=4, decimal_places=1, default=8.0)
    qte_produite = models.PositiveIntegerField()
    qte_rebut = models.PositiveIntegerField()
    cause_rebut_principale = models.ForeignKey(TypeDefaut, on_delete=models.SET_NULL, null=True, blank=True)
    defauts_detail = models.JSONField(default=dict)
    est_valide = models.BooleanField(default=False)
    
    objects = TenantManager()
    class Meta:
        db_table = "tpm_production_reports"


# ==========================================
# 3. BREAKDOWN / PANNES & ARRÊTS
# ==========================================
class TypeArret(BaseModel):
    CATEGORIE_CHOICES = [
        ('TECHNIQUE', 'Panne Technique'),
        ('ORGANISATION', 'Organisationnel'),
    ]
    libelle = models.CharField(max_length=100)
    categorie = models.CharField(max_length=20, choices=CATEGORIE_CHOICES)
    objects = TenantManager()
    class Meta:
        db_table = "tpm_type_arret"

class Breakdown(BaseModel): # Panne
    STATUT_CHOICES = [
        ('DECLAREE', 'Déclarée'),
        ('VALIDE_CHEF', 'Validée par Chef d\'équipe'),
        ('AFFECTEE', 'Affectée au Technicien'),
        ('EN_COURS', 'Intervention en Cours'),
        ('TERMINEE', 'Terminée'),
        ('VALIDEE', 'Validée par Superviseur'),
        ('ANNULEE', 'Annulée'),
    ]

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='pannes')
    operateur = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name='pannes_declarees')
    
    description = models.TextField()
    date_declaration = models.DateTimeField(auto_now_add=True)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    
    statut = models.CharField(max_length=30, choices=STATUT_CHOICES, default='DECLAREE')
    chef_equipe = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name='pannes_validees')
    technicien = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name='pannes_affectees')
    superviseur = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name='pannes_supervisees')
    
    cause_racine = models.TextField(blank=True)
    actions_correctives = models.TextField(blank=True)
    temps_intervention_minutes = models.PositiveIntegerField(null=True, blank=True)
    
    objects = TenantManager()
    class Meta:
        db_table = "tpm_breakdowns"

    def sync_to_shared_action(self):
        from shared.models import Action
        status_map = {
            'DECLAREE': 'open',
            'VALIDE_CHEF': 'open',
            'AFFECTEE': 'open',
            'EN_COURS': 'in_progress',
            'TERMINEE': 'done',
            'VALIDEE': 'done',
            'ANNULEE': 'done',
        }
        action, _ = Action.objects.update_or_create(
            reference_id=self.id,
            module_source="tpm",
            tenant=self.tenant,
            defaults={
                "title": f"[Panne] {self.machine.code}",
                "description": self.description,
                "priority": "high",
                "status": status_map.get(self.statut, "open"),
                "assigned_to": self.technicien,
                "created_by": self.created_by,
                "action_type": "tpm_breakdown",
            }
        )
        return action


class ArretMachine(BaseModel):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='arrets_machine')
    operateur = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True)
    cause = models.ForeignKey(TypeArret, on_delete=models.SET_NULL, null=True)
    heure_debut = models.DateTimeField(default=timezone.now)
    heure_fin = models.DateTimeField(null=True, blank=True)
    commentaire = models.TextField(blank=True)
    objects = TenantManager()
    class Meta:
        db_table = "tpm_arret_machine"


# ==========================================
# 4. MAINTENANCE TASKS
# ==========================================
class MaintenanceTask(BaseModel): # Tache
    TYPE_CHOICES = [
        ('PREVENTIVE', 'Maintenance Préventive'),
        ('CORRECTIVE', 'Maintenance Corrective'),
        ('AUTRE', 'Autre'),
    ]
    STATUT_CHOICES = [
        ('EN_ATTENTE', 'En Attente'),
        ('EN_COURS', 'En Cours'),
        ('TERMINEE', 'Terminée'),
        ('ANNULEE', 'Annulée'),
    ]
    
    type_tache = models.CharField(max_length=20, choices=TYPE_CHOICES, default='PREVENTIVE')
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='taches_maintenance', null=True, blank=True)
    description = models.TextField()
    technicien = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name='taches_assignees_tpm')
    deadline = models.DateField()
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_ATTENTE')
    duree_estimee_minutes = models.PositiveIntegerField(null=True, blank=True)
    panne = models.ForeignKey(Breakdown, on_delete=models.SET_NULL, null=True, blank=True, related_name='taches_correctives')

    objects = TenantManager()
    class Meta:
        db_table = "tpm_maintenance_tasks"

    def sync_to_shared_action(self):
        from shared.models import Action
        status_map = {
            'EN_ATTENTE': 'open',
            'EN_COURS': 'in_progress',
            'TERMINEE': 'done',
            'ANNULEE': 'done',
        }
        action, _ = Action.objects.update_or_create(
            reference_id=self.id,
            module_source="tpm",
            tenant=self.tenant,
            defaults={
                "title": f"[Maintenance] {self.machine.code if self.machine else 'Générale'}",
                "description": self.description,
                "priority": "medium",
                "status": status_map.get(self.statut, "open"),
                "assigned_to": self.technicien,
                "due_date": self.deadline,
                "created_by": self.created_by,
                "action_type": "tpm_maintenance",
            }
        )
        return action


# ==========================================
# 5. INTERVENTIONS
# ==========================================
class Intervention(BaseModel):
    STATUS_CHOICES = [
        ('RECEIVED', 'Received'),
        ('ACCEPTED', 'Accepted'),
        ('DIAGNOSTIC', 'Diagnosing'),
        ('REPAIR', 'Repair in Progress'),
        ('TEST', 'Testing'),
        ('COMPLETED', 'Completed'),
        ('VALIDATED', 'Validated'),
    ]

    panne = models.OneToOneField(Breakdown, on_delete=models.CASCADE, related_name='intervention')
    technicien = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name='interventions_tpm')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RECEIVED')
    
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    root_cause = models.TextField(blank=True)

    objects = TenantManager()
    class Meta:
        db_table = "tpm_interventions"


class InterventionAction(BaseModel):
    intervention = models.ForeignKey(Intervention, on_delete=models.CASCADE, related_name='actions')
    step = models.CharField(max_length=20, choices=Intervention.STATUS_CHOICES)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    technicien = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True)

    objects = TenantManager()
    class Meta:
        db_table = "tpm_intervention_actions"


# ==========================================
# 6. CHECKLISTS
# ==========================================
class ChecklistTemplate(BaseModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    items = models.JSONField(default=list)
    objects = TenantManager()
    class Meta:
        db_table = "tpm_checklist_templates"

class ChecklistExecution(BaseModel):
    intervention = models.ForeignKey(Intervention, on_delete=models.CASCADE, related_name='checklists', null=True, blank=True)
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    items_result = models.JSONField(default=list)
    completed = models.BooleanField(default=False)
    objects = TenantManager()
    class Meta:
        db_table = "tpm_checklist_executions"


# ==========================================
# 7. KAIZEN
# ==========================================
class Kaizen(BaseModel): # IdeeAmelioration
    PRIORITE_CHOICES = [
        ('BASSE', 'Basse'),
        ('MOYENNE', 'Moyenne'),
        ('HAUTE', 'Haute'),
        ('URGENTE', 'Urgente'),
    ]
    STATUT_CHOICES = [
        ('EN_ATTENTE', 'En Attente'),
        ('VALIDEE', 'Validée'),
        ('REFUSEE', 'Refusée'),
        ('REALISEE', 'Réalisée'),
    ]

    auteur = models.ForeignKey("accounts.Employee", on_delete=models.CASCADE, related_name='idees_proposees')
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='idees_amelioration')
    titre = models.CharField(max_length=100)
    description = models.TextField()
    priorite = models.CharField(max_length=20, choices=PRIORITE_CHOICES, default='MOYENNE')
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_ATTENTE')
    valide_par = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name='idees_validees')

    objects = TenantManager()
    class Meta:
        db_table = "tpm_kaizen"

    def sync_to_shared_action(self):
        from shared.models import Action
        status_map = {
            'EN_ATTENTE': 'open',
            'VALIDEE': 'in_progress',
            'REFUSEE': 'done',
            'REALISEE': 'done',
        }
        priority_map = {
            'BASSE': 'low',
            'MOYENNE': 'medium',
            'HAUTE': 'high',
            'URGENTE': 'critical',
        }
        action, _ = Action.objects.update_or_create(
            reference_id=self.id,
            module_source="tpm",
            tenant=self.tenant,
            defaults={
                "title": f"[Kaizen] {self.titre}",
                "description": self.description,
                "priority": priority_map.get(self.priorite, "medium"),
                "status": status_map.get(self.statut, "open"),
                "assigned_to": self.auteur,
                "created_by": self.created_by,
                "action_type": "tpm_kaizen",
            }
        )
        return action

# ==========================================
# 8. OEE TRACKING (TempsProduction, Session)
# ==========================================
class TempsProduction(BaseModel):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='temps_production')
    date = models.DateField(default=timezone.now)
    temps_ouverture_heures = models.DecimalField(max_digits=5, decimal_places=2, default=8.0)
    temps_perdu_imprevu_minutes = models.PositiveIntegerField(default=0)
    temps_perdu_prevu_minutes = models.PositiveIntegerField(default=0)
    
    objects = TenantManager()
    class Meta:
        db_table = "tpm_temps_production"

class SessionProduction(BaseModel):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='sessions')
    operateur = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True)
    date = models.DateField(default=timezone.now)
    heure_debut = models.DateTimeField(auto_now_add=True)
    heure_fin = models.DateTimeField(null=True, blank=True)
    est_active = models.BooleanField(default=True)
    est_en_panne = models.BooleanField(default=False)
    
    objects = TenantManager()
    class Meta:
        db_table = "tpm_session_production"

class ArretProduction(BaseModel):
    session = models.ForeignKey(SessionProduction, on_delete=models.CASCADE, related_name='arrets')
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    type_arret = models.CharField(max_length=30)
    categorie = models.CharField(max_length=20)
    heure_debut = models.DateTimeField(default=timezone.now)
    heure_fin = models.DateTimeField(null=True, blank=True)
    
    objects = TenantManager()
    class Meta:
        db_table = "tpm_arret_production"
