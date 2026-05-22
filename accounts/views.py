from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import BelongsToTenant
from .models import CustomUser, Employee
from .serializers import (
    ChangePasswordSerializer,
    EmployeeSerializer,
    SetPasswordSerializer,
    TenantSummarySerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)


TENANT_ADMIN_ROLES = {"tenant_admin"}
TENANT_MANAGER_ROLES = {"tenant_admin", "plant_manager", "quality_mgr", "supervisor"}


class HasTenantContext(BasePermission):
    message = "Tenant context is required."

    def has_permission(self, request, view):
        return bool(getattr(request, "tenant", None))


class IsTenantManager(BasePermission):
    message = "You do not have permission to manage tenant employees."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in TENANT_MANAGER_ROLES)


class IsTenantAdmin(BasePermission):
    message = "Only tenant admins can manage users."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in TENANT_ADMIN_ROLES)


class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, BelongsToTenant, HasTenantContext, IsTenantManager]
    filterset_fields = ["department", "site", "status", "is_active"]
    search_fields = ["first_name", "last_name", "email", "employee_id"]
    ordering_fields = ["last_name", "first_name", "created_at", "updated_at"]
    ordering = ["last_name", "first_name"]

    def get_queryset(self):
        return Employee.objects.filter(
            tenant=self.request.tenant,
            is_active=True,
            is_deleted=False,
        ).select_related("department", "site", "manager", "user_account")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        instance.status = "inactive"
        instance.save(update_fields=["is_active", "is_deleted", "deleted_at", "status", "updated_at"])


class TeamUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, BelongsToTenant, HasTenantContext, IsTenantAdmin]
    filterset_fields = ["role", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    ordering_fields = ["email", "role", "date_joined"]
    ordering = ["email"]

    def get_queryset(self):
        return CustomUser.objects.filter(
            tenant=self.request.tenant,
        ).exclude(role="super_admin").order_by("email")

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action in ["update", "partial_update"]:
            return UserUpdateSerializer
        return UserSerializer

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        if instance.id == self.request.user.id:
            raise PermissionDenied("You cannot deactivate your own account.")
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    @action(detail=True, methods=["post"])
    def set_password(self, request, pk=None):
        user = self.get_object()
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


class MeView(APIView):
    permission_classes = [IsAuthenticated, BelongsToTenant, HasTenantContext]

    def get(self, request):
        employee = getattr(request.user, "employee_profile", None)
        tenant = request.tenant
        return Response({
            "user": UserSerializer(request.user).data,
            "employee": EmployeeSerializer(employee).data if employee else None,
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "status": tenant.status,
                "plan": tenant.plan,
                "subscription_ends_at": tenant.subscription_ends_at,
                "max_users": tenant.max_users,
            },
            "role": request.user.role,
            "modules": tenant.license.to_dict(),
        })


class ChangeOwnPasswordView(APIView):
    permission_classes = [IsAuthenticated, BelongsToTenant, HasTenantContext]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["old_password"]):
            return Response({"old_password": "Old password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Password changed."})


class CurrentTenantView(APIView):
    permission_classes = [IsAuthenticated, BelongsToTenant, HasTenantContext]

    def get(self, request):
        tenant = request.tenant
        serializer = TenantSummarySerializer({
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "plan": tenant.plan,
            "subscription_ends_at": tenant.subscription_ends_at,
            "max_users": tenant.max_users,
            "license": tenant.license.to_dict(),
        })
        return Response(serializer.data)
