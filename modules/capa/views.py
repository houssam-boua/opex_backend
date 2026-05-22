# modules/capa/views.py
"""
CAPA Module ViewSets
API endpoints for CAPA.
"""
from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from core.permissions import BelongsToTenant, ModuleIsActive
from .models import CapaTicket
from .serializers import CapaTicketSerializer

class CapaTicketViewSet(viewsets.ModelViewSet):
    """
    ViewSet for CAPA tickets.
    The frontend calls this the 'actions' API.
    """
    serializer_class = CapaTicketSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "capa"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["capa_type", "status", "urgency", "pilot"]
    search_fields = ["title", "description", "problem", "root_cause"]
    ordering_fields = ["created_at", "due_date", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return CapaTicket.objects.filter(
            tenant=self.request.tenant
        ).select_related("pilot", "created_by")

    def perform_create(self, serializer):
        ticket = serializer.save()
        ticket.sync_to_shared_action()

    def perform_update(self, serializer):
        ticket = serializer.save()
        ticket.sync_to_shared_action()

    def perform_destroy(self, instance):
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()

