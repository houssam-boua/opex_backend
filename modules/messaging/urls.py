# modules/messaging/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet, MessageViewSet, ConversationParticipantViewSet

router = DefaultRouter()
router.register(r"conversations", ConversationViewSet, basename="conversation")
router.register(r"messages", MessageViewSet, basename="message")
router.register(r"participants", ConversationParticipantViewSet, basename="participant")

urlpatterns = [
    path("", include(router.urls)),
]
