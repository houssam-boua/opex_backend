# modules/messaging/models.py
"""
Messaging Module — OPEX SaaS
System-wide communication layer connecting human actions, issues, and alerts.
"""
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from shared.base import BaseModel
from accounts.managers import TenantManager


class Conversation(BaseModel):
    """
    Core conversation thread.
    Can be standalone or linked to an object (CAPA, 8D, QRQC, etc.) via GenericForeignKey.
    """
    class Status(models.TextChoices):
        OPEN     = "open",     "Ouvert"
        CLOSED   = "closed",   "Fermé"
        ARCHIVED = "archived", "Archivé"

    title  = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    # GenericForeignKey for cross-module linking
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id    = models.UUIDField(null=True, blank=True)
    linked_item  = GenericForeignKey('content_type', 'object_id')

    objects = TenantManager()

    class Meta:
        db_table = "messaging_conversations"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Conversation: {self.title}"


class ConversationParticipant(BaseModel):
    """
    Tracks which employees are in a conversation and their read state.
    """
    class Role(models.TextChoices):
        ADMIN       = "admin",       "Administrateur"
        PARTICIPANT = "participant", "Participant"
        VIEWER      = "viewer",      "Observateur"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    user         = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="conversations"
    )
    role         = models.CharField(max_length=20, choices=Role.choices, default=Role.PARTICIPANT)
    last_read_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "messaging_participants"
        unique_together = ("conversation", "user")


class Message(BaseModel):
    """
    A single message within a conversation.
    Can be human-generated or system-generated.
    """
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender       = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    content      = models.TextField()
    is_system_generated = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        db_table = "messaging_messages"
        ordering = ["created_at"]

    def __str__(self):
        prefix = "[SYS]" if self.is_system_generated else ""
        return f"{prefix} Message in {self.conversation.id} at {self.created_at}"
