# modules/messaging/consumers.py
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from .models import Conversation, ConversationParticipant, Message

logger = logging.getLogger(__name__)
User = get_user_model()

@database_sync_to_async
def authenticate_jwt(token_string):
    """
    Validates JWT token and returns the user object.
    Returns AnonymousUser if invalid.
    """
    try:
        access_token = AccessToken(token_string)
        user_id = access_token["user_id"]
        user = User.objects.get(id=user_id)
        return user
    except (InvalidToken, TokenError, User.DoesNotExist) as e:
        logger.error(f"WebSocket JWT Auth failed: {e}")
        return AnonymousUser()

@database_sync_to_async
def get_conversation_participant(user, conversation_id):
    """
    Validates that the conversation exists AND the user is a participant.
    Also ensures the user belongs to the conversation's tenant.
    Returns the conversation if valid, else None.
    """
    try:
        conv = Conversation.objects.select_related("tenant").get(id=conversation_id)
        # Strict tenant isolation
        if conv.tenant != user.tenant:
            return None
            
        employee = getattr(user, "employee_profile", None)
        if not employee or employee.tenant_id != conv.tenant_id:
            return None

        participant = ConversationParticipant.objects.get(conversation=conv, user=employee)
        return conv
    except (Conversation.DoesNotExist, ConversationParticipant.DoesNotExist):
        return None

@database_sync_to_async
def save_message(user, conversation, content):
    """
    Saves the message to the DB.
    """
    employee = getattr(user, 'employee_profile', None)
    msg = Message.objects.create(
        conversation=conversation,
        sender=employee,
        content=content,
        is_system_generated=False,
        tenant=conversation.tenant,
        created_by=user
    )
    # Touch conversation to update 'updated_at'
    conversation.save()
    return {
        "id": str(msg.id),
        "content": msg.content,
        "sender_id": str(msg.sender.id) if msg.sender else None,
        "sender_name": msg.sender.full_name if msg.sender else "Unknown",
        "created_at": msg.created_at.isoformat(),
        "is_system_generated": msg.is_system_generated
    }


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        
        # Extract JWT from query string
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        token = None
        for param in query_string.split('&'):
            if param.startswith('token='):
                token = param.split('=')[1]
                break

        if not token:
            await self.close(code=4001) # Missing token
            return

        # STRICT REQUIREMENT: WebSocket MUST authenticate using JWT BEFORE connection is accepted
        self.user = await authenticate_jwt(token)
        
        if isinstance(self.user, AnonymousUser):
            await self.close(code=4003) # Invalid token
            return

        # TENANT ISOLATION (CRITICAL SECURITY RULE)
        # Tenant check happens BEFORE group join
        self.conversation = await get_conversation_participant(self.user, self.conversation_id)
        
        if not self.conversation:
            # User is not in conversation or cross-tenant attempt
            await self.close(code=4003)
            return

        # Every WebSocket group MUST be scoped: chat_tenant_{tenant_id}conv_{conversation_id}
        self.tenant_id = self.user.tenant.id
        self.room_group_name = f'chat_tenant_{self.tenant_id}_conv_{self.conversation_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Check module license before accepting
        license_active = getattr(
            getattr(self.user.tenant, "license", None),
            "is_messaging_active",
            False
        )
        if not license_active:
            await self.close(code=4003)
            return

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        content = data.get('content')

        if not content:
            return

        # Save to DB
        msg_data = await save_message(self.user, self.conversation, content)

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': msg_data
            }
        )

    # Receive message from room group
    async def chat_message(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'message': message
        }))
