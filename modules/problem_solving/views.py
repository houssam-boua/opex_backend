# modules/problem_solving/views.py
from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from core.permissions import BelongsToTenant, ModuleIsActive
from .models import Problem8D, RootCause8D, Action8D, QRQC, QRQCAction
from .serializers import (
    Problem8DSerializer, RootCause8DSerializer, Action8DSerializer,
    QRQCSerializer, QRQCActionSerializer
)

class ProblemSolvingBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "problem_solving"

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

class Problem8DViewSet(ProblemSolvingBaseViewSet):
    serializer_class = Problem8DSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "current_step", "level", "leader"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Problem8D.objects.filter(tenant=self.request.tenant)

class RootCause8DViewSet(ProblemSolvingBaseViewSet):
    serializer_class = RootCause8DSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["problem", "category", "analysis_method"]

    def get_queryset(self):
        return RootCause8D.objects.filter(tenant=self.request.tenant)

class Action8DViewSet(ProblemSolvingBaseViewSet):
    serializer_class = Action8DSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["problem", "status", "action_type", "assigned_to"]

    def get_queryset(self):
        return Action8D.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        action = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        action.sync_to_shared_action()

    def perform_update(self, serializer):
        action = serializer.save()
        action.sync_to_shared_action()

class QRQCViewSet(ProblemSolvingBaseViewSet):
    serializer_class = QRQCSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "urgency", "poste"]
    search_fields = ["title", "problem", "cause"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return QRQC.objects.filter(tenant=self.request.tenant)

class QRQCActionViewSet(ProblemSolvingBaseViewSet):
    serializer_class = QRQCActionSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["qrqc", "status", "assigned_to"]

    def get_queryset(self):
        return QRQCAction.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        action = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        action.sync_to_shared_action()

    def perform_update(self, serializer):
        action = serializer.save()
        action.sync_to_shared_action()
