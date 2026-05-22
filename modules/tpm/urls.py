# modules/tpm/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    MachineViewSet, ProductionReportViewSet, BreakdownViewSet,
    MaintenanceTaskViewSet, InterventionViewSet, 
    ChecklistViewSet, KaizenViewSet
)

router = DefaultRouter()
router.register(r"machines", MachineViewSet, basename="tpm-machine")
router.register(r"production-reports", ProductionReportViewSet, basename="tpm-production")
router.register(r"breakdowns", BreakdownViewSet, basename="tpm-breakdown")
router.register(r"maintenance-tasks", MaintenanceTaskViewSet, basename="tpm-maintenance")
router.register(r"interventions", InterventionViewSet, basename="tpm-intervention")
router.register(r"checklists", ChecklistViewSet, basename="tpm-checklist")
router.register(r"kaizen", KaizenViewSet, basename="tpm-kaizen")

urlpatterns = [
    path("", include(router.urls)),
]
