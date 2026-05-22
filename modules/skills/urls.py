# modules/skills/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SkillCategoryViewSet, SkillViewSet, EmployeeSkillViewSet,
    TrainingSessionViewSet, CertificationViewSet
)

router = DefaultRouter()
router.register(r"categories", SkillCategoryViewSet, basename="skill-category")
router.register(r"matrix", SkillViewSet, basename="skill") # using the same viewset but base routing
router.register(r"employee-skills", EmployeeSkillViewSet, basename="employee-skill")
router.register(r"training", TrainingSessionViewSet, basename="training-session")
router.register(r"certifications", CertificationViewSet, basename="certification")

urlpatterns = [
    path("", include(router.urls)),
]
