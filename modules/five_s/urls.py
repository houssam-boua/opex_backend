# modules/five_s/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AuditQuestionViewSet, AuditSession5SViewSet, 
    AuditResponseViewSet, Anomaly5SViewSet
)

router = DefaultRouter()
router.register(r"questions", AuditQuestionViewSet, basename="5s-question")
router.register(r"sessions", AuditSession5SViewSet, basename="5s-session")
router.register(r"responses", AuditResponseViewSet, basename="5s-response")
router.register(r"anomalies", Anomaly5SViewSet, basename="5s-anomaly")

urlpatterns = [
    path("", include(router.urls)),
]
