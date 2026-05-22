# modules/iso9001/services.py
from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone
from datetime import timedelta
from .models import (
    ISO9001Clause, ComplianceAssessment, NonConformity, ISODocument,
    ISO9001EvaluationSession, ISO9001Question, ISO9001Response
)
from shared.models import Notification

class ISO9001Service:
    @staticmethod
    def calculate_compliance(tenant):
        """
        Calculates compliance_score per clause and overall_compliance_score.
        """
        assessments = ComplianceAssessment.objects.filter(tenant=tenant, is_active=True)
        
        # Compliance by clause
        compliance_by_clause = list(assessments.values(
            "clause__clause_number", "clause__title"
        ).annotate(
            avg_score=Avg("score")
        ).order_by("clause__clause_number"))
        
        # Overall compliance score (weighted avg across all assessments)
        overall_agg = assessments.aggregate(overall=Avg("score"))
        overall_compliance_score = overall_agg["overall"] or 0.0

        return {
            "overall_compliance_score": round(overall_compliance_score, 2),
            "compliance_by_clause": compliance_by_clause
        }

    @staticmethod
    def trigger_capa_if_needed(non_conformity):
        """
        If severity == major or critical, fire decoupled signal.
        """
        if non_conformity.severity in [NonConformity.Severity.MAJOR, NonConformity.Severity.CRITICAL]:
            from .signals import iso_nc_created
            iso_nc_created.send(sender=ISO9001Service, non_conformity=non_conformity)

    @staticmethod
    def check_iso_document_expiry():
        """
        Finds documents expiring exactly 30 days from now and alerts the owner.
        Intended to be run daily by Celery at 7:00 AM.
        """
        target_date = timezone.localdate() + timedelta(days=30)
        
        expiring_docs = ISODocument.objects.filter(
            valid_until=target_date,
            is_active=True
        ).select_related('uploaded_by__user_account', 'tenant')

        for doc in expiring_docs:
            if doc.uploaded_by and doc.uploaded_by.user_account:
                if Notification.objects.filter(
                    tenant=doc.tenant,
                    recipient=doc.uploaded_by.user_account,
                    notification_type="iso_doc_expiry",
                    related_object_id=doc.id,
                    created_at__date=timezone.localdate(),
                ).exists():
                    continue
                Notification.objects.create(
                    recipient=doc.uploaded_by.user_account,
                    title=f"ISO Document Expiry Alert: {doc.title}",
                    message=f"Your document '{doc.title}' (v{doc.version}) will expire in exactly 30 days on {doc.valid_until}.",
                    notification_type="iso_doc_expiry",
                    related_object_id=doc.id,
                    tenant=doc.tenant
                )

    # ═══════════════════════════════════════════════════════════════
    # LEGACY COMPATIBILITY BRIDGE — Business Logic
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    @transaction.atomic
    def process_response_nc_bridge(response):
        """
        RULE 1 — Non-Conformity Bridge.
        When a response is non_compliant, auto-generate a NonConformity
        linked to the clause and session, then fire the decoupled CAPA
        signal if the clause warrants it.
        """
        if response.response_status != ISO9001Response.ResponseStatus.NON_COMPLIANT:
            return None

        clause = response.question.clause

        nc = NonConformity.objects.create(
            clause=clause,
            description=(
                f"Non-conformité détectée lors de l'évaluation « {response.session.title} » "
                f"— Question : {response.question.question_text[:120]}"
            ),
            severity=NonConformity.Severity.MINOR,  # Default; reviewer can upgrade
            detected_by=response.session.evaluator,
            status=NonConformity.Status.OPEN,
            tenant=response.tenant,
            created_by=response.created_by,
        )

        # Fire decoupled CAPA signal (will only emit if severity is major/critical,
        # but we call it defensively so future severity upgrades are captured)
        ISO9001Service.trigger_capa_if_needed(nc)
        return nc

    @staticmethod
    @transaction.atomic
    def complete_session(session):
        """
        RULE 2 — Session Score Engine.
        Calculates global_score using legacy weighting:
            compliant     = 100 points
            partial       = 50  points
            non_compliant = 0   points
            n_a           = excluded from denominator
        Stores the final percentage in session.global_score.
        """
        SCORE_MAP = {
            ISO9001Response.ResponseStatus.COMPLIANT: 100,
            ISO9001Response.ResponseStatus.PARTIAL: 50,
            ISO9001Response.ResponseStatus.NON_COMPLIANT: 0,
        }

        responses = ISO9001Response.objects.filter(
            session=session,
            is_active=True
        ).select_related("question__clause")

        total_points = 0
        max_points = 0

        for resp in responses:
            if resp.response_status == ISO9001Response.ResponseStatus.NA:
                continue  # Excluded from denominator
            total_points += SCORE_MAP.get(resp.response_status, 0)
            max_points += 100

        session.global_score = round((total_points / max_points) * 100, 2) if max_points > 0 else 0.0
        session.status = ISO9001EvaluationSession.Status.COMPLETED
        session.save(update_fields=["global_score", "status", "updated_at"])

        return session
