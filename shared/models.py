# shared/models.py
import uuid as _uuid
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from shared.base import BaseModel


class Action(BaseModel):
    """
    Action corrective/préventive générique.
    Référencée depuis Gemba, Audits, 5S, QRQC, Risk, etc.
    NE PAS recréer dans un module.
    """
    PRIORITY = [("low","Bas"),("medium","Moyen"),("high","Élevé"),("critical","Critique")]
    STATUS   = [("open","Ouvert"),("in_progress","En cours"),
                ("done","Terminé"),("cancelled","Annulé")]

    title         = models.CharField(max_length=300)
    description   = models.TextField(blank=True)
    priority      = models.CharField(max_length=20, choices=PRIORITY, default="medium")
    status        = models.CharField(max_length=20, choices=STATUS,   default="open")
    assigned_to   = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="actions_assigned"
    )
    due_date      = models.DateField(null=True, blank=True)
    closed_at     = models.DateTimeField(null=True, blank=True)
    module_source = models.CharField(max_length=50, blank=True)
    reference_id  = models.UUIDField(null=True, blank=True)
    action_type   = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = "shared_actions"
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["tenant", "status"])]


class Attachment(BaseModel):
    """Pièce jointe universelle via GenericForeignKey."""
    file            = models.FileField(upload_to="attachments/%Y/%m/")
    filename        = models.CharField(max_length=255)
    file_size       = models.IntegerField(default=0)
    mime_type       = models.CharField(max_length=100, blank=True)
    content_type    = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id       = models.UUIDField()
    content_object  = GenericForeignKey("content_type", "object_id")

    class Meta:
        db_table = "shared_attachments"


class Notification(BaseModel):
    TYPE = [("info","Info"),("warning","Avertissement"),
            ("error","Erreur"),("success","Succès")]

    recipient = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.CASCADE, related_name="notifications"
    )
    title     = models.CharField(max_length=255)
    message   = models.TextField()
    type      = models.CharField(max_length=20, choices=TYPE, default="info")
    is_read   = models.BooleanField(default=False)
    link      = models.CharField(max_length=500, blank=True)
    notification_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="e.g. certification_expiry · iso_doc_expiry · andon_sla_breach · capa_due"
    )
    related_object_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID of the related object that triggered this notification"
    )

    class Meta:
        db_table = "shared_notifications"
        ordering = ["-created_at"]


class Comment(BaseModel):
    content        = models.TextField()
    author         = models.ForeignKey("accounts.CustomUser", on_delete=models.CASCADE)
    content_type   = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id      = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        db_table = "shared_comments"
        ordering = ["created_at"]


class AuditLog(models.Model):
    """
    AuditLog N'hérite PAS de BaseModel (on ne soft-delete pas les logs).
    Trace : qui · quoi · où · avant · après · quand
    """
    id         = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    tenant     = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    user       = models.ForeignKey("accounts.CustomUser", on_delete=models.SET_NULL, null=True)
    action     = models.CharField(max_length=50)
    module     = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    object_id  = models.CharField(max_length=100)
    before     = models.JSONField(default=dict)
    after      = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shared_audit_logs"
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["tenant", "module", "created_at"])]
