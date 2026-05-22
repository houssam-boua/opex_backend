# accounts/managers.py
import threading
from django.db import models

_thread_local = threading.local()

def get_current_tenant():
    return getattr(_thread_local, "tenant", None)

def set_current_tenant(tenant):
    _thread_local.tenant = tenant


class TenantManager(models.Manager):
    """
    Filtre automatiquement par tenant ET exclut les soft-deleted.
    À utiliser sur tous les modèles qui héritent de BaseModel.
    """
    def get_queryset(self):
        tenant = get_current_tenant()
        qs = super().get_queryset().filter(is_deleted=False)
        if tenant:
            qs = qs.filter(tenant=tenant)
        return qs

    def all_including_deleted(self):
        """Accès admin uniquement — inclut les soft-deleted."""
        tenant = get_current_tenant()
        qs = super().get_queryset()
        if tenant:
            qs = qs.filter(tenant=tenant)
        return qs
