# modules/visual_management/routing.py
from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/andon/line/<uuid:line_id>/', consumers.AndonConsumer.as_asgi()),
]
