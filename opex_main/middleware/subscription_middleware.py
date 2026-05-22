# opex_main/middleware/subscription_middleware.py
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse


# Chemins exemptés de la vérification d'abonnement
EXEMPT_PATHS = [
    "/api/v1/auth/login/",
    "/api/v1/auth/refresh/",
    "/api/v1/billing/webhook/",
    "/api/v1/schema/",
    "/api/v1/swagger/",
    "/admin/",
]


class SubscriptionMiddleware(MiddlewareMixin):
    """
    Vérifie que le tenant est actif (non suspendu / non expiré).
    Bloque toutes les requêtes API si le tenant est inactif.
    S'exécute APRÈS TenantMiddleware.
    """
    def process_request(self, request):
        # Exempter les chemins publics
        for path in EXEMPT_PATHS:
            if request.path.startswith(path):
                return None

        # Passer si pas d'API call
        if not request.path.startswith("/api/"):
            return None

        tenant = getattr(request, "tenant", None)

        # Pas de tenant résolu = pas de restriction ici (géré par BelongsToTenant)
        if not tenant:
            return None

        if getattr(tenant, "is_deleted", False) or getattr(tenant, "archived_at", None):
            return JsonResponse(
                {
                    "error": "tenant_archived",
                    "message": "Ce tenant est archivÃ© ou supprimÃ©. Contactez support@opex.app.",
                    "status": tenant.status,
                },
                status=403,
            )

        if not tenant.is_active:
            return JsonResponse(
                {
                    "error": "subscription_inactive",
                    "message": "Votre abonnement est suspendu ou expiré. "
                               "Contactez support@opex.app.",
                    "status": tenant.status,
                },
                status=403,
            )

        return None
