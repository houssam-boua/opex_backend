# core/permissions.py
from rest_framework.permissions import BasePermission


class BelongsToTenant(BasePermission):
    """L'user doit appartenir au tenant courant."""
    message = "Accès refusé — vous n'appartenez pas à ce tenant."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_super_admin:
            return True
        return (
            hasattr(request, "tenant") and
            request.tenant is not None and
            request.user.tenant_id == request.tenant.id
        )


class ModuleIsActive(BasePermission):
    """
    Bloque si le module est désactivé dans TenantLicense.
    Le ViewSet doit définir : module_name = "gemba"  (clé dans to_dict())
    """
    message = "Ce module n'est pas activé dans votre abonnement."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_super_admin:
            return True
        module_key = getattr(view, "module_name", None)
        if not module_key:
            return True   # Pas de vérification si module_name absent
        try:
            return request.tenant.license.to_dict().get(module_key, False)
        except Exception:
            return False
