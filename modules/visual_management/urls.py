# modules/visual_management/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductionLineViewSet, AndonCallViewSet, AndonResponseViewSet

router = DefaultRouter()
router.register(r"lines", ProductionLineViewSet, basename="production-line")
router.register(r"calls", AndonCallViewSet, basename="andon-call")
router.register(r"responses", AndonResponseViewSet, basename="andon-response")

urlpatterns = [
    path("", include(router.urls)),
]
