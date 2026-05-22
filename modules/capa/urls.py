# modules/capa/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CapaTicketViewSet

router = DefaultRouter()
# The frontend uses /actions as the endpoint, so we can map it to 'actions' or 'tickets'
router.register(r"actions", CapaTicketViewSet, basename="capa-action")

urlpatterns = [
    path("", include(router.urls)),
]
