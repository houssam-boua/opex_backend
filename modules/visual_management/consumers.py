# modules/visual_management/consumers.py
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from .models import ProductionLine

logger = logging.getLogger(__name__)
User = get_user_model()

@database_sync_to_async
def authenticate_jwt(token_string):
    try:
        access_token = AccessToken(token_string)
        user_id = access_token["user_id"]
        user = User.objects.get(id=user_id)
        return user
    except (InvalidToken, TokenError, User.DoesNotExist) as e:
        logger.error(f"WebSocket JWT Auth failed: {e}")
        return AnonymousUser()

@database_sync_to_async
def get_production_line(user, line_id):
    try:
        line = ProductionLine.objects.select_related("tenant").get(id=line_id)
        if line.tenant != user.tenant:
            return None
        return line
    except ProductionLine.DoesNotExist:
        return None


class AndonConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.line_id = self.scope['url_route']['kwargs']['line_id']
        
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        token = None
        for param in query_string.split('&'):
            if param.startswith('token='):
                token = param.split('=')[1]
                break

        if not token:
            await self.close(code=4001)
            return

        # JWT auth BEFORE self.accept()
        self.user = await authenticate_jwt(token)
        
        if isinstance(self.user, AnonymousUser):
            # Reject with code=4003 if invalid
            await self.close(code=4003)
            return

        # Tenant check BEFORE group_add
        self.line = await get_production_line(self.user, self.line_id)
        
        if not self.line:
            await self.close(code=4003)
            return

        self.tenant_id = self.user.tenant.id
        self.room_group_name = f'andon_tenant_{self.tenant_id}_line_{self.line_id}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Check module license before accepting
        license_active = getattr(
            getattr(self.user.tenant, "license", None),
            "is_visual_mgmt_active",
            False
        )
        if not license_active:
            await self.close(code=4003)
            return

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        # We just receive broadcasts. Usually clients don't send from WS directly to create calls,
        # they use the REST API, and the backend broadcasts it.
        # But if they do send something, we can broadcast it.
        pass

    async def andon_update(self, event):
        """Called when an AndonCall is created or updated via the REST API"""
        message = event['message']
        await self.send(text_data=json.dumps({
            'type': 'andon_update',
            'data': message
        }))
