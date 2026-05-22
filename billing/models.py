# billing/models.py
"""
Billing Module — Offline Contract + License Key Architecture
NO Stripe. All sales are manual via offline contracts.
Tenants are activated by Superadmin or via License Key.
"""
import uuid
import secrets
import string
from django.db import models
from shared.base import BaseModel
from accounts.managers import TenantManager


class SubscriptionPlan(models.Model):
    """
    Définit les plans disponibles et les modules inclus dans chaque plan.
    Utilisé en référence — la source de vérité reste TenantLicense.
    """
    PLAN_CHOICES = [("starter", "Starter"), ("pro", "Pro"), ("enterprise", "Enterprise")]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=50, choices=PLAN_CHOICES, unique=True)
    display_name = models.CharField(max_length=100)
    price_eur    = models.DecimalField(max_digits=8, decimal_places=2)
    max_users    = models.IntegerField(default=10)
    modules      = models.JSONField(default=list)  # ["gemba","capa","5s","messaging"]
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_plans"

    def __str__(self):
        return f"{self.display_name} — {self.price_eur}€/mois"


def _generate_key():
    """Génère une clé XXXX-XXXX-XXXX-XXXX (16 chars alphanumériques)."""
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(4)]
    return "-".join(parts)


class LicenseKey(BaseModel):
    """
    Clé de licence générée par un Superadmin.
    Workflow : Superadmin crée la clé → la donne au client →
    le client (ou le Superadmin) l'active sur son tenant.

    NOTE : tenant est nullable car les clés sont créées au niveau
    plateforme (par un Superadmin) avant d'être associées à un tenant.
    """
    # Override BaseModel.tenant to allow NULL (platform-level entity)
    tenant             = models.ForeignKey(
        "core.Tenant", on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="%(app_label)s_%(class)s_set",
    )
    key                = models.CharField(max_length=19, unique=True, default=_generate_key)
    plan               = models.ForeignKey(
        SubscriptionPlan, on_delete=models.CASCADE, related_name="license_keys"
    )
    duration_days      = models.IntegerField(default=365, help_text="Durée de la licence en jours")
    is_used            = models.BooleanField(default=False)
    activated_by_tenant = models.ForeignKey(
        "core.Tenant", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="used_license_keys"
    )
    activated_at       = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "billing_license_keys"
        ordering = ["-created_at"]

    def __str__(self):
        status = "USED" if self.is_used else "AVAILABLE"
        return f"{self.key} ({self.plan.name}) [{status}]"
