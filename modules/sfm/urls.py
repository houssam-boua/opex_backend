from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SFMDashboardView, SFMEscalationViewSet, SFMKPIViewSet, SFMSessionViewSet


router = DefaultRouter()
router.register("sessions", SFMSessionViewSet, basename="sfm-session")
router.register("kpis", SFMKPIViewSet, basename="sfm-kpi")
router.register("escalations", SFMEscalationViewSet, basename="sfm-escalation")

urlpatterns = [
    path("dashboard/", SFMDashboardView.as_view(), name="sfm-dashboard"),
    path("", include(router.urls)),
]
