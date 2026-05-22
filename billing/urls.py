from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ActivateLicenseView,
    LicenseKeyViewSet,
    SubscriptionPlanViewSet,
    TenantAdminViewSet,
)


admin_router = DefaultRouter()
admin_router.register("plans", SubscriptionPlanViewSet, basename="billing-admin-plan")
admin_router.register("license-keys", LicenseKeyViewSet, basename="billing-admin-license-key")
admin_router.register("tenants", TenantAdminViewSet, basename="billing-admin-tenant")

urlpatterns = [
    path("activate-license/", ActivateLicenseView.as_view(), name="billing-activate-license"),
    path("admin/", include(admin_router.urls)),
]
