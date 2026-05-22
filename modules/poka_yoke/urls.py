from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    PokaYokeCheckViewSet,
    PokaYokeDashboardView,
    PokaYokeDefectViewSet,
    PokaYokeDeviceViewSet,
    PokaYokeImprovementViewSet,
)


router = DefaultRouter()
router.register("devices", PokaYokeDeviceViewSet, basename="poka-yoke-device")
router.register("checks", PokaYokeCheckViewSet, basename="poka-yoke-check")
router.register("defects", PokaYokeDefectViewSet, basename="poka-yoke-defect")
router.register("improvements", PokaYokeImprovementViewSet, basename="poka-yoke-improvement")

urlpatterns = [
    path("dashboard/", PokaYokeDashboardView.as_view(), name="poka-yoke-dashboard"),
    path("", include(router.urls)),
]
