from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ChangeOwnPasswordView,
    CurrentTenantView,
    EmployeeViewSet,
    MeView,
    TeamUserViewSet,
)


router = DefaultRouter()
router.register("employees", EmployeeViewSet, basename="account-employee")
router.register("users", TeamUserViewSet, basename="account-user")

urlpatterns = [
    path("me/", MeView.as_view(), name="accounts-me"),
    path("me/change_password/", ChangeOwnPasswordView.as_view(), name="accounts-change-password"),
    path("tenant/", CurrentTenantView.as_view(), name="accounts-tenant"),
    path("", include(router.urls)),
]
