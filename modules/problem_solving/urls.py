# modules/problem_solving/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    Problem8DViewSet, RootCause8DViewSet, Action8DViewSet,
    QRQCViewSet, QRQCActionViewSet
)

router = DefaultRouter()
router.register(r"8d/problems", Problem8DViewSet, basename="8d-problem")
router.register(r"8d/root-causes", RootCause8DViewSet, basename="8d-root-cause")
router.register(r"8d/actions", Action8DViewSet, basename="8d-action")
router.register(r"qrqc/tickets", QRQCViewSet, basename="qrqc-ticket")
router.register(r"qrqc/actions", QRQCActionViewSet, basename="qrqc-action")

urlpatterns = [
    path("", include(router.urls)),
]
