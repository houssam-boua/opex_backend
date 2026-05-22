# modules/risk/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RiskCategoryViewSet, RiskViewSet, 
    RiskAssessmentViewSet, RiskMitigationActionViewSet
)

router = DefaultRouter()
router.register(r"categories", RiskCategoryViewSet, basename="risk-category")
router.register(r"risks", RiskViewSet, basename="risk")
router.register(r"assessments", RiskAssessmentViewSet, basename="risk-assessment")
router.register(r"mitigations", RiskMitigationActionViewSet, basename="risk-mitigation")

urlpatterns = [
    path("", include(router.urls)),
]
