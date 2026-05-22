# modules/audits/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AuditTypeViewSet, AuditPlanViewSet, AuditViewSet,
    AuditChecklistItemViewSet, FindingViewSet,
)

router = DefaultRouter()
router.register(r"types",           AuditTypeViewSet,          basename="audit-type")
router.register(r"plans",           AuditPlanViewSet,          basename="audit-plan")
router.register(r"audits",          AuditViewSet,              basename="audit")
router.register(r"checklist-items", AuditChecklistItemViewSet, basename="audit-checklist")
router.register(r"findings",        FindingViewSet,            basename="audit-finding")

urlpatterns = [
    path("", include(router.urls)),
]
