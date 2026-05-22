# modules/vsm/views.py
"""
VSM ViewSets -- thin controllers that delegate to VSMService.
"""
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import VSMMap, VSMElement, VSMVersion
from .serializers import (
    VSMMapSerializer, VSMElementSerializer,
    VSMVersionSerializer, SnapshotRequestSerializer,
)
from .services import VSMService


class VSMBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "vsm"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    def perform_destroy(self, instance):
        instance.soft_delete(user=self.request.user)


class VSMMapViewSet(VSMBaseViewSet):
    serializer_class = VSMMapSerializer
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["state", "status", "visibility", "owner", "department"]
    search_fields    = ["name", "description"]
    ordering_fields  = ["name", "created_at", "updated_at"]

    def get_queryset(self):
        return VSMMap.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).select_related("owner", "department")

    @action(detail=True, methods=["post"], url_path="snapshot")
    def snapshot(self, request, pk=None):
        """
        POST /api/v1/vsm/maps/{id}/snapshot/
        Body: { "label": "optional label" }
        Creates an immutable version snapshot via the service layer.
        """
        vsm_map = self.get_object()
        ser = SnapshotRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        version = VSMService.create_snapshot(
            vsm_map=vsm_map,
            user=request.user,
            label=ser.validated_data.get("label", ""),
        )
        return Response(
            VSMVersionSerializer(version).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="recalculate")
    def recalculate(self, request, pk=None):
        """
        POST /api/v1/vsm/maps/{id}/recalculate/
        Triggers metric recalculation from current elements.
        """
        vsm_map = self.get_object()
        updated = VSMService.recalculate_metrics(vsm_map)
        return Response(VSMMapSerializer(updated).data)


class VSMElementViewSet(VSMBaseViewSet):
    serializer_class = VSMElementSerializer
    filter_backends  = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["vsm_map", "element_type"]
    ordering_fields  = ["z_index", "created_at"]

    def get_queryset(self):
        return VSMElement.objects.filter(
            tenant=self.request.tenant, is_active=True
        )

    def perform_create(self, serializer):
        element = serializer.save(
            tenant=self.request.tenant, created_by=self.request.user
        )
        # Auto-recalculate map metrics when elements change
        VSMService.recalculate_metrics(element.vsm_map)

    def perform_update(self, serializer):
        element = serializer.save()
        VSMService.recalculate_metrics(element.vsm_map)


class VSMVersionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    VSMVersion is IMMUTABLE after creation.
    Only list and retrieve are allowed (no create/update/delete via API).
    Snapshots are created exclusively through VSMMapViewSet.snapshot().
    """
    serializer_class   = VSMVersionSerializer
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name        = "vsm"
    filter_backends    = [DjangoFilterBackend, OrderingFilter]
    filterset_fields   = ["vsm_map"]
    ordering_fields    = ["version_num", "created_at"]

    def get_queryset(self):
        return VSMVersion.objects.filter(
            tenant=self.request.tenant, is_active=True
        )
