# modules/risk/services.py
from django.db import transaction
from django.utils import timezone
from .models import Risk, RiskAssessment, RiskHistory, RiskMitigationAction
from .signals import risk_escalated

class RiskService:
    @staticmethod
    @transaction.atomic
    def assess_risk(risk, likelihood, impact, assessor, notes=""):
        """
        Business logic for assessing a risk.
        1. Calculates risk_score = likelihood * impact
        2. Saves history
        3. Checks escalation rules
        """
        old_score = risk.risk_score
        
        # 1. Calculate Score
        new_score = likelihood * impact
        
        # Determine Severity based on score (optional refinement, but usually done manually or via matrix)
        # Assuming standard 5x5 matrix:
        if new_score >= 16:
            severity = Risk.Severity.CRITICAL
        elif new_score >= 10:
            severity = Risk.Severity.HIGH
        elif new_score >= 5:
            severity = Risk.Severity.MEDIUM
        else:
            severity = Risk.Severity.LOW

        # Update Risk
        risk.likelihood = likelihood
        risk.impact = impact
        risk.risk_score = new_score
        risk.severity = severity
        risk.save(update_fields=["likelihood", "impact", "risk_score", "severity", "updated_at"])

        # 2. Track Assessment
        RiskAssessment.objects.create(
            risk=risk,
            assessor=assessor,
            notes=notes,
            updated_score=new_score,
            tenant=risk.tenant,
            created_by=assessor.user_account
        )

        # 3. Track History
        if old_score != new_score:
            RiskHistory.objects.create(
                risk=risk,
                old_score=old_score,
                new_score=new_score,
                changed_by=assessor,
                tenant=risk.tenant,
                created_by=assessor.user_account
            )

        # 4. CAPA Trigger Rule (Decoupled)
        if new_score >= 16:
            # Emitting an internal event hook to remain completely decoupled.
            # The CAPA module (or core orchestrator) will listen to this signal.
            risk_escalated.send(sender=RiskService, risk=risk, assessor=assessor)

        return risk

    @staticmethod
    @transaction.atomic
    def add_mitigation_action(risk, description, deadline, owner=None, creator=None):
        """
        Adds a mitigation action and triggers shared sync.
        """
        action = RiskMitigationAction.objects.create(
            risk=risk,
            description=description,
            deadline=deadline,
            owner=owner,
            tenant=risk.tenant,
            created_by=creator
        )
        action.sync_to_shared_action()
        return action
