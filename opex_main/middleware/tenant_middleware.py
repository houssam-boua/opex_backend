# opex_main/middleware/tenant_middleware.py
from django.utils.deprecation import MiddlewareMixin
from core.models import Tenant
from accounts.managers import set_current_tenant


class TenantMiddleware(MiddlewareMixin):
    """
    Résout le tenant depuis le sous-domaine.
    acme.opex.app → request.tenant = Tenant(slug="acme")
    """
    def process_request(self, request):
        host   = request.get_host().split(":")[0]
        parts  = host.split(".")
        tenant = None

        if len(parts) >= 3:
            slug = parts[0]
            if slug not in ("app", "www", "api", "admin"):
                try:
                    tenant = Tenant.objects.select_related("license").get(
                        slug=slug, status__in=["active", "trial"]
                    )
                except Tenant.DoesNotExist:
                    pass

        request.tenant = tenant
        set_current_tenant(tenant)

    def process_response(self, request, response):
        set_current_tenant(None)    # Nettoyage thread-local
        return response
