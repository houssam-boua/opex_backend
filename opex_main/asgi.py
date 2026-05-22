"""
ASGI config for OPEX project.
Exposes the ASGI callable as a module-level variable named ``application``.
Supports Django Channels for WebSocket (Andon + Messaging).
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opex_main.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from modules.messaging.routing import websocket_urlpatterns as msg_ws
from modules.visual_management.routing import websocket_urlpatterns as andon_ws

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        URLRouter(
            msg_ws + andon_ws
        )
    ),
})
