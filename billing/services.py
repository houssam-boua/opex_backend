# billing/services.py
"""
Billing Services — License Key Generation & Activation
NO Stripe. All activation is manual or via license key.
"""
from datetime import timedelta
from django.utils import timezone
from core.models import Tenant
from billing.models import LicenseKey, SubscriptionPlan


def generate_license_key(plan_name: str, duration_days: int = 365, created_by=None, tenant=None):
    """
    Génère une clé de licence. Appelé par un Superadmin.

    Args:
        plan_name: "starter", "pro", or "enterprise"
        duration_days: durée de validité en jours (défaut: 365)
        created_by: CustomUser qui génère la clé (Superadmin)
        tenant: Tenant associé pour le tenant FK de BaseModel

    Returns:
        LicenseKey instance avec clé auto-générée
    """
    plan = SubscriptionPlan.objects.get(name=plan_name)
    return LicenseKey.objects.create(
        plan=plan,
        duration_days=duration_days,
        created_by=created_by,
        tenant=tenant,
    )


def activate_license_key(tenant: Tenant, key_string: str) -> dict:
    """
    Active une clé de licence sur un tenant.

    Workflow:
        1. Valide que la clé existe et n'est pas utilisée
        2. Marque la clé comme utilisée
        3. Met à jour le plan et le statut du tenant
        4. Calcule subscription_ends_at = today + duration_days
        5. Active les modules via TenantLicense.activate_plan()

    Returns:
        dict avec le résultat de l'activation

    Raises:
        ValueError si la clé est invalide ou déjà utilisée
    """
    from django.db import transaction

    try:
        license_key = LicenseKey.objects.select_related("plan").get(key=key_string)
    except LicenseKey.DoesNotExist:
        raise ValueError("Clé de licence invalide.")

    if license_key.is_used:
        raise ValueError(
            f"Cette clé a déjà été utilisée le {license_key.activated_at.strftime('%d/%m/%Y')}."
        )

    with transaction.atomic():
        # 1. Marquer la clé comme utilisée
        license_key.is_used = True
        license_key.activated_by_tenant = tenant
        license_key.activated_at = timezone.now()
        license_key.save(update_fields=["is_used", "activated_by_tenant", "activated_at", "updated_at"])

        # 2. Mettre à jour le tenant
        plan_name = license_key.plan.name
        tenant.plan = plan_name
        tenant.status = "active"
        tenant.max_users = license_key.plan.max_users
        tenant.subscription_ends_at = timezone.now().date() + timedelta(days=license_key.duration_days)
        tenant.save(update_fields=["plan", "status", "max_users", "subscription_ends_at", "updated_at"])

        # 3. Activer les modules
        tenant.license.activate_plan(plan_name)

    return {
        "success": True,
        "plan": plan_name,
        "duration_days": license_key.duration_days,
        "expires_at": str(tenant.subscription_ends_at),
        "modules": tenant.license.to_dict(),
    }
