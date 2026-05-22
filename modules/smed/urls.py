from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import SMEDDashboardView, SMEDSessionViewSet, SMEDStepViewSet


router = DefaultRouter()
router.register(r"sessions", SMEDSessionViewSet, basename="smed-sessions")
router.register(r"steps", SMEDStepViewSet, basename="smed-steps")

urlpatterns = router.urls
urlpatterns += [
    path("dashboard/", SMEDDashboardView.as_view(), name="smed-dashboard"),
]
