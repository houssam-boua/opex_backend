# modules/visual_management/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Count
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from core.permissions import BelongsToTenant, ModuleIsActive
from .models import ProductionLine, AndonCall, AndonResponse, AndonAlert
from .serializers import (
    ProductionLineSerializer, AndonCallSerializer, AndonResponseSerializer, AndonAlertSerializer
)
from .services import AndonService
from .tasks import check_andon_sla_breach_task

class VMBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [BelongsToTenant, ModuleIsActive]
    module_name = "visual_mgmt"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        
    def perform_destroy(self, instance):
        if hasattr(instance, 'soft_delete'):
            instance.soft_delete(user=self.request.user)
        else:
            instance.delete()


class ProductionLineViewSet(VMBaseViewSet):
    serializer_class = ProductionLineSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["site", "department", "status"]
    search_fields = ["name"]
    ordering_fields = ["name"]

    def get_queryset(self):
        return ProductionLine.objects.filter(tenant=self.request.tenant, is_active=True)


class AndonCallViewSet(VMBaseViewSet):
    serializer_class = AndonCallSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["line", "operator", "call_type", "severity", "status"]
    search_fields = ["description"]
    ordering_fields = ["created_at", "severity"]

    def get_queryset(self):
        return AndonCall.objects.filter(tenant=self.request.tenant, is_active=True)

    def perform_create(self, serializer):
        call = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        
        # Sync to shared.models.Action if High/Critical
        call.sync_to_shared_action()
        
        # SLA Breach Logic: Trigger Celery task (10 minutes = 600 seconds)
        if call.severity in [AndonCall.Severity.HIGH, AndonCall.Severity.CRITICAL]:
            check_andon_sla_breach_task.apply_async((str(call.id),), countdown=600)
            
        # Broadcast to WebSocket
        channel_layer = get_channel_layer()
        group_name = f'andon_tenant_{self.request.tenant.id}_line_{call.line.id}'
        
        # Serialize the message for broadcast
        message_data = self.get_serializer(call).data
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'andon_update',
                'message': message_data
            }
        )

    @action(detail=False, methods=["get"])
    def analytics(self, request):
        """
        Analytics Endpoint
        GET /api/v1/visual-management/calls/analytics/
        """
        tenant = request.tenant
        
        # 1. avg_response_time_per_line
        avg_response_time_per_line = AndonService.calculate_response_time(tenant)
        
        # 2. calls_by_type
        calls_by_type = list(AndonCall.objects.filter(tenant=tenant).values('call_type').annotate(count=Count('id')))
        
        # 3. sla_breach_rate
        total_high_critical = AndonCall.objects.filter(
            tenant=tenant, 
            severity__in=[AndonCall.Severity.HIGH, AndonCall.Severity.CRITICAL]
        ).count()
        total_breaches = AndonAlert.objects.filter(call__tenant=tenant).count()
        sla_breach_rate = (total_breaches / total_high_critical * 100) if total_high_critical > 0 else 0
        
        # 4. open_calls_right_now
        open_calls_right_now = AndonCall.objects.filter(
            tenant=tenant,
            status=AndonCall.Status.OPEN
        ).count()
        
        return Response({
            "avg_response_time_per_line": avg_response_time_per_line,
            "calls_by_type": calls_by_type,
            "sla_breach_rate": sla_breach_rate,
            "open_calls_right_now": open_calls_right_now
        })


class AndonResponseViewSet(VMBaseViewSet):
    serializer_class = AndonResponseSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["call", "responder"]
    
    def get_queryset(self):
        return AndonResponse.objects.filter(tenant=self.request.tenant, is_active=True)
