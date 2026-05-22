# modules/capa/signals.py
from django.dispatch import receiver
from django.db import transaction

# Import the signals defined in other modules
# These are the signals that were dispatched but had no receiver
try:
    from modules.risk.signals import risk_escalated
except ImportError:
    risk_escalated = None

try:
    from modules.iso9001.signals import iso_nc_created
except ImportError:
    iso_nc_created = None


def _create_capa_from_source(tenant, title, description, source_module,
                              reference_id, created_by=None):
    """
    Internal helper — creates a CAPA ticket from any module source.
    Wrapped in on_commit to avoid creating tickets for rolled-back transactions.
    """
    from modules.capa.models import CapaTicket

    def _do_create():
        CapaTicket.objects.create(
            tenant=tenant,
            title=title,
            description=description,
            # using default values for capa_type etc as specified in models
            status="identified", # Initial status from models
            urgency="high",
            created_by=created_by,
        )

    transaction.on_commit(_do_create)


if risk_escalated is not None:
    @receiver(risk_escalated)
    def on_risk_escalated(sender, risk, **kwargs):
        """
        Auto-creates a CAPA ticket when a risk reaches criticality ≥ 16 (score = prob × impact).
        Triggered by: risk/services.py when criticality crosses the threshold.
        """
        _create_capa_from_source(
            tenant=risk.tenant,
            title=f"[AUTO] Risque escaladé — {risk.title}",
            description=(
                f"Ce ticket CAPA a été créé automatiquement suite à l'escalade du risque "
                f"'{risk.title}' (criticité : {risk.risk_score}).\n\n"
                f"Description du risque : {risk.description}"
            ),
            source_module="risk",
            reference_id=risk.id,
            created_by=risk.created_by,
        )


if iso_nc_created is not None:
    @receiver(iso_nc_created)
    def on_iso_nc_created(sender, nonconformity=None, non_conformity=None, **kwargs):
        """
        Auto-creates a CAPA ticket when a major or critical ISO non-conformity is detected.
        Triggered by: iso9001/services.py when NC severity is major or critical.
        """
        nonconformity = nonconformity or non_conformity
        if nonconformity is None:
            return

        _create_capa_from_source(
            tenant=nonconformity.tenant,
            title=f"[AUTO] Non-conformité ISO — {nonconformity.id}",
            description=(
                f"Ce ticket CAPA a été créé automatiquement suite à la détection d'une "
                f"non-conformité ISO ({nonconformity.severity}) : {nonconformity.description}"
            ),
            source_module="iso9001",
            reference_id=nonconformity.id,
            created_by=nonconformity.created_by,
        )
