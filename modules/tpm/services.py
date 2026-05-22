# modules/tpm/services.py
from django.db import transaction
from django.utils import timezone
from .models import Breakdown, Intervention, MaintenanceTask

class TPMService:
    @staticmethod
    def calculate_oee(availability, performance, quality):
        """
        Exact OEE formula requirement.
        OEE = Availability * Performance * Quality
        """
        return availability * performance * quality

    @staticmethod
    def calculate_kpis(temps_ouverture_heures, temps_perdu_minutes, qte_produite, cadence_theorique, qte_rebut):
        """
        Calculates individual components and OEE.
        All KPI logic lives exclusively here.
        """
        temps_ouverture_min = float(temps_ouverture_heures) * 60.0
        
        # Availability (Disponibilité)
        if temps_ouverture_min > 0:
            availability = max(0, (temps_ouverture_min - temps_perdu_minutes)) / temps_ouverture_min
        else:
            availability = 0.0
            
        # Performance
        temps_production_net = temps_ouverture_min - temps_perdu_minutes
        if temps_production_net > 0 and cadence_theorique > 0:
            qte_theorique = (temps_production_net / 60.0) * cadence_theorique
            performance = min(1.0, qte_produite / qte_theorique) if qte_theorique > 0 else 0.0
        else:
            performance = 0.0
            
        # Quality (Qualité)
        if qte_produite > 0:
            quality = max(0, qte_produite - qte_rebut) / qte_produite
        else:
            quality = 0.0
            
        oee = TPMService.calculate_oee(availability, performance, quality)
        
        return {
            "availability": availability * 100,
            "performance": performance * 100,
            "quality": quality * 100,
            "oee": oee * 100
        }

    # ==========================================
    # WORKFLOW TRANSITIONS (STRICTLY ATOMIC)
    # ==========================================
    
    @staticmethod
    @transaction.atomic
    def assign_breakdown(breakdown, technicien):
        """
        Transition: DECLAREE -> AFFECTEE
        """
        if breakdown.statut != 'DECLAREE':
            raise ValueError("Breakdown must be DECLAREE to be assigned.")
            
        breakdown.statut = 'AFFECTEE'
        breakdown.technicien = technicien
        breakdown.save(update_fields=['statut', 'technicien', 'updated_at'])
        breakdown.sync_to_shared_action()
        return breakdown

    @staticmethod
    @transaction.atomic
    def start_intervention(breakdown):
        """
        Transition: AFFECTEE -> EN_COURS
        """
        if breakdown.statut != 'AFFECTEE':
            raise ValueError("Breakdown must be AFFECTEE to start intervention.")
            
        breakdown.statut = 'EN_COURS'
        breakdown.date_debut = timezone.now()
        breakdown.save(update_fields=['statut', 'date_debut', 'updated_at'])
        
        # Also sync Intervention if needed, but we keep it simple here.
        breakdown.sync_to_shared_action()
        return breakdown

    @staticmethod
    @transaction.atomic
    def finish_intervention(breakdown, cause_racine, actions_correctives):
        """
        Transition: EN_COURS -> TERMINEE
        """
        if breakdown.statut != 'EN_COURS':
            raise ValueError("Breakdown must be EN_COURS to finish.")
            
        breakdown.statut = 'TERMINEE'
        breakdown.date_fin = timezone.now()
        breakdown.cause_racine = cause_racine
        breakdown.actions_correctives = actions_correctives
        
        delta = breakdown.date_fin - breakdown.date_debut
        breakdown.temps_intervention_minutes = int(delta.total_seconds() / 60)
        
        breakdown.save(update_fields=[
            'statut', 'date_fin', 'cause_racine', 
            'actions_correctives', 'temps_intervention_minutes', 'updated_at'
        ])
        breakdown.sync_to_shared_action()
        return breakdown

    @staticmethod
    @transaction.atomic
    def validate_breakdown(breakdown, superviseur):
        """
        Transition: TERMINEE -> VALIDEE
        """
        if breakdown.statut != 'TERMINEE':
            raise ValueError("Breakdown must be TERMINEE to validate.")
            
        breakdown.statut = 'VALIDEE'
        breakdown.superviseur = superviseur
        breakdown.save(update_fields=['statut', 'superviseur', 'updated_at'])
        breakdown.sync_to_shared_action()
        return breakdown
