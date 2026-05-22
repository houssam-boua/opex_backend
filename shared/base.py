# shared/base.py
import uuid
from django.db import models
from django.utils import timezone


class BaseModel(models.Model):
    """
    Modèle de base hérité par TOUS les modèles métier.
    Élimine toute inconsistance entre les 16 modules.

    UTILISATION :
        from shared.base import BaseModel

        class MonModele(BaseModel):
            title = models.CharField(max_length=300)
            # tenant, created_by, created_at, updated_at,
            # is_active, is_deleted, deleted_at
            # sont automatiquement disponibles
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant     = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set"
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="%(app_label)s_%(class)s_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active  = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True    # ← Aucune table créée — héritage pur

    def soft_delete(self, user=None):
        """Suppression logique — conserve l'historique."""
        self.is_deleted = True
        self.is_active  = False
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "is_active", "deleted_at", "updated_at"])

    def restore(self):
        """Restaure un objet soft-deleted."""
        self.is_deleted = False
        self.is_active  = True
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "is_active", "deleted_at", "updated_at"])
