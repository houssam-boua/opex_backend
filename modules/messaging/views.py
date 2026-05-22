# modules/messaging/views.py
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from core.permissions import BelongsToTenant, ModuleIsActive
from .models import Conversation, Message, ConversationParticipant
from .serializers import (
    ConversationSerializer, MessageSerializer, ConversationParticipantSerializer
)


def _request_employee(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee or employee.tenant_id != request.tenant.id:
        raise PermissionDenied("Aucun Employee valide n'est lie a cet utilisateur.")
    return employee


class MessagingBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "messaging"

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.tenant,
            created_by=self.request.user
        )

    def perform_destroy(self, instance):
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()

class ConversationViewSet(MessagingBaseViewSet):
    serializer_class = ConversationSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "content_type", "object_id"]
    search_fields = ["title"]
    ordering_fields = ["updated_at", "created_at"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        # Users can only see conversations they are part of
        employee = _request_employee(self.request)
        user_convs = ConversationParticipant.objects.filter(
            user=employee,
            tenant=self.request.tenant
        ).values_list("conversation_id", flat=True)
        return Conversation.objects.filter(id__in=user_convs, tenant=self.request.tenant)

    def perform_create(self, serializer):
        # Creates the conversation and auto-adds the creator as an Admin participant
        conversation = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        ConversationParticipant.objects.create(
            conversation=conversation,
            user=_request_employee(self.request),
            role=ConversationParticipant.Role.ADMIN,
            tenant=self.request.tenant,
            created_by=self.request.user
        )

class ConversationParticipantViewSet(MessagingBaseViewSet):
    serializer_class = ConversationParticipantSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["conversation", "user", "role"]

    def get_queryset(self):
        return ConversationParticipant.objects.filter(tenant=self.request.tenant)

class MessageViewSet(MessagingBaseViewSet):
    serializer_class = MessageSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["conversation", "sender", "is_system_generated"]
    ordering_fields = ["created_at"]
    ordering = ["created_at"]

    def get_queryset(self):
        # Filter messages by conversations the user is in
        employee = _request_employee(self.request)
        user_convs = ConversationParticipant.objects.filter(
            user=employee,
            tenant=self.request.tenant
        ).values_list("conversation_id", flat=True)
        return Message.objects.filter(conversation_id__in=user_convs, tenant=self.request.tenant)

    def perform_create(self, serializer):
        # Ensure user can't spoof system messages via API
        conversation = serializer.validated_data["conversation"]
        employee = _request_employee(self.request)
        
        # Verify user is in conversation
        if not ConversationParticipant.objects.filter(conversation=conversation, user=employee).exists():
            raise PermissionDenied("You are not a participant in this conversation.")

        serializer.save(
            tenant=self.request.tenant,
            created_by=self.request.user,
            sender=employee,
            is_system_generated=False
        )
        
        # Update conversation updated_at
        conversation.save() # Triggers auto_now update
