from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    RotationAssignmentViewSet,
    RotationDashboardView,
    RotationIncidentViewSet,
    RotationPlanViewSet,
    RotationRuleViewSet,
    RotationSlotViewSet,
    RotationViolationViewSet,
    WorkstationViewSet,
)


router = DefaultRouter()
router.register("plans", RotationPlanViewSet, basename="rotation-plan")
router.register("workstations", WorkstationViewSet, basename="rotation-workstation")
router.register("slots", RotationSlotViewSet, basename="rotation-slot")
router.register("assignments", RotationAssignmentViewSet, basename="rotation-assignment")
router.register("rules", RotationRuleViewSet, basename="rotation-rule")
router.register("violations", RotationViolationViewSet, basename="rotation-violation")
router.register("incidents", RotationIncidentViewSet, basename="rotation-incident")

urlpatterns = [
    path("dashboard/", RotationDashboardView.as_view(), name="rotation-dashboard"),
    path("", include(router.urls)),
]
