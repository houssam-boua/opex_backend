# modules/tpm/serializers.py
from rest_framework import serializers
from .models import (
    Machine, ProductionReport, Breakdown, MaintenanceTask,
    Intervention, ChecklistExecution, Kaizen
)

class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = [
            "id", "code", "nom", "emplacement", "cadence_theorique",
            "date_installation", "etat", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class ProductionReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionReport
        fields = [
            "id", "machine", "operateur", "validateur", "date",
            "temps_ouverture", "qte_produite", "qte_rebut",
            "cause_rebut_principale", "defauts_detail", "est_valide",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class BreakdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = Breakdown
        fields = [
            "id", "machine", "operateur", "description", "date_declaration",
            "date_debut", "date_fin", "statut", "chef_equipe", "technicien",
            "superviseur", "cause_racine", "actions_correctives",
            "temps_intervention_minutes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "date_declaration", "created_at", "updated_at"]

class MaintenanceTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceTask
        fields = [
            "id", "type_tache", "machine", "description", "technicien",
            "deadline", "statut", "duree_estimee_minutes", "panne",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_deadline(self, value):
        from django.utils import timezone
        if value and value < timezone.now().date():
            raise serializers.ValidationError("La date d'échéance ne peut pas être dans le passé.")
        return value

class InterventionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Intervention
        fields = [
            "id", "panne", "technicien", "status", "start_time", "end_time",
            "root_cause", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class ChecklistExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistExecution
        fields = [
            "id", "intervention", "template", "items_result", "completed",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class KaizenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Kaizen
        fields = [
            "id", "auteur", "machine", "titre", "description", "priorite",
            "statut", "valide_par", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
