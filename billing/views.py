from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import LicenseKey, SubscriptionPlan
from core.models import Tenant
from .serializers import (
    ActivateLicenseSerializer,
    LicenseKeyGenerateSerializer,
    LicenseKeySerializer,
    SubscriptionPlanSerializer,
    TenantAdminSerializer,
    TenantLicenseSerializer,
)


class IsSuperAdmin(BasePermission):
    message = "Only SuperAdmin users can access this API."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_super_admin", False)
        )


class IsTenantAdmin(BasePermission):
    message = "Only tenant admins can activate licenses."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request, "tenant", None)
            and request.user.tenant_id == request.tenant.id
            and request.user.role == "tenant_admin"
        )


class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    lookup_field = "id"
    filterset_fields = ["name", "is_active"]
    search_fields = ["name", "display_name"]
    ordering_fields = ["name", "price_eur", "max_users", "created_at", "updated_at"]
    ordering = ["price_eur"]

    def get_queryset(self):
        return SubscriptionPlan.objects.all().order_by("price_eur")

    @action(detail=True, methods=["post"])
    def activate(self, request, id=None):
        plan = self.get_object()
        plan.is_active = True
        plan.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(plan).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, id=None):
        plan = self.get_object()
        plan.is_active = False
        plan.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(plan).data)


class LicenseKeyViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    lookup_field = "id"
    filterset_fields = ["is_used", "plan"]
    search_fields = ["key", "activated_by_tenant__name", "activated_by_tenant__slug"]
    ordering_fields = ["created_at", "activated_at", "duration_days"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return LicenseKey._base_manager.filter(is_deleted=False).select_related(
            "plan",
            "activated_by_tenant",
            "created_by",
        )

    def get_serializer_class(self):
        if self.action == "create":
            return LicenseKeyGenerateSerializer
        return LicenseKeySerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        license_key = serializer.save()
        return Response(LicenseKeySerializer(license_key).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revoke(self, request, id=None):
        license_key = self.get_object()
        if license_key.is_used:
            return Response({"detail": "Used license keys cannot be revoked."}, status=status.HTTP_400_BAD_REQUEST)
        license_key.is_active = False
        license_key.is_deleted = True
        license_key.save(update_fields=["is_active", "is_deleted", "updated_at"])
        return Response({"detail": "License key revoked."})


class TenantAdminViewSet(viewsets.ModelViewSet):
    serializer_class = TenantAdminSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    lookup_field = "id"
    filterset_fields = ["status", "plan"]
    search_fields = ["name", "slug", "contact_email"]
    ordering_fields = ["name", "status", "plan", "created_at", "updated_at"]
    ordering = ["name"]

    def get_queryset(self):
        return Tenant.objects.select_related("license").all()

    def perform_destroy(self, instance):
        instance.soft_delete(user=self.request.user)

    @action(detail=True, methods=["post"])
    def suspend(self, request, id=None):
        tenant = self.get_object()
        tenant.status = "suspended"
        tenant.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, id=None):
        tenant = self.get_object()
        tenant.status = "active"
        tenant.is_deleted = False
        tenant.deleted_at = None
        tenant.deleted_by = None
        tenant.archived_at = None
        tenant.archived_by = None
        tenant.save(update_fields=[
            "status",
            "is_deleted",
            "deleted_at",
            "deleted_by",
            "archived_at",
            "archived_by",
            "updated_at",
        ])
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, id=None):
        tenant = self.get_object()
        tenant.archive(user=request.user)
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["get", "patch"])
    def license(self, request, id=None):
        tenant = self.get_object()
        if request.method == "GET":
            return Response(tenant.license.to_dict())
        serializer = TenantLicenseSerializer(data=request.data, context={"tenant": tenant})
        serializer.is_valid(raise_exception=True)
        license_obj = serializer.save()
        return Response(license_obj.to_dict())

    @action(detail=True, methods=["post"])
    def activate_plan(self, request, id=None):
        tenant = self.get_object()
        serializer = TenantLicenseSerializer(
            data={"activate_plan": request.data.get("plan")},
            context={"tenant": tenant},
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            license_obj = serializer.save()
        return Response({
            "tenant": TenantAdminSerializer(tenant).data,
            "modules": license_obj.to_dict(),
        })


class ActivateLicenseView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def post(self, request):
        serializer = ActivateLicenseSerializer(data=request.data, context={"tenant": request.tenant})
        serializer.is_valid(raise_exception=True)
        try:
            result = serializer.save()
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "tenant": {
                "id": str(request.tenant.id),
                "name": request.tenant.name,
                "slug": request.tenant.slug,
                "plan": request.tenant.plan,
                "status": request.tenant.status,
                "subscription_ends_at": request.tenant.subscription_ends_at,
            },
            **result,
        })
