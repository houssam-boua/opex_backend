# modules/vsm/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VSMMapViewSet, VSMElementViewSet, VSMVersionViewSet

router = DefaultRouter()
router.register(r"maps",     VSMMapViewSet,     basename="vsm-map")
router.register(r"elements", VSMElementViewSet, basename="vsm-element")
router.register(r"versions", VSMVersionViewSet, basename="vsm-version")

urlpatterns = [
    path("", include(router.urls)),
]
