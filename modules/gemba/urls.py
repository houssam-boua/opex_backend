# modules/gemba/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    GembaZoneViewSet, GembaTeamViewSet, GembaCategoryViewSet,
    CheckpointViewSet, TourViewSet, ExecutionPointViewSet,
    AnomalyViewSet, FaceToFaceViewSet, FiveSAuditViewSet,
)

router = DefaultRouter()
router.register(r"zones",            GembaZoneViewSet,      basename="gemba-zone")
router.register(r"teams",            GembaTeamViewSet,      basename="gemba-team")
router.register(r"categories",       GembaCategoryViewSet,  basename="gemba-category")
router.register(r"checkpoints",      CheckpointViewSet,     basename="gemba-checkpoint")
router.register(r"tours",            TourViewSet,           basename="gemba-tour")
router.register(r"execution-points", ExecutionPointViewSet, basename="gemba-execution")
router.register(r"anomalies",        AnomalyViewSet,        basename="gemba-anomaly")
router.register(r"face-to-face",     FaceToFaceViewSet,     basename="gemba-f2f")
router.register(r"5s-audits",        FiveSAuditViewSet,     basename="gemba-5s")

urlpatterns = [
    path("", include(router.urls)),
]
