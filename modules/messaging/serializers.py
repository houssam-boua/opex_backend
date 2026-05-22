# modules/messaging/serializers.py
from rest_framework import serializers
from .models import Conversation, Message, ConversationParticipant


def _request_tenant(serializer):
    request = serializer.context.get("request")
    return getattr(request, "tenant", None)


def _validate_tenant_object(obj, tenant, message):
    if obj and tenant and getattr(obj, "tenant_id", None) != tenant.id:
        raise serializers.ValidationError(message)

class ConversationParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConversationParticipant
        fields = [
            "id", "conversation", "user", "role", "last_read_at",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_user(self, value):
        if not value:
            raise serializers.ValidationError("Employee requis pour un participant.")
        tenant = _request_tenant(self)
        if value and tenant and value.tenant_id != tenant.id:
            raise serializers.ValidationError("Employee invalide pour ce tenant.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        _validate_tenant_object(
            attrs.get("conversation", getattr(self.instance, "conversation", None)),
            tenant,
            "Conversation invalide pour ce tenant.",
        )
        return attrs

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id", "conversation", "sender", "content", "is_system_generated",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "sender", "is_system_generated", "created_at", "updated_at"]

    def validate(self, attrs):
        tenant = _request_tenant(self)
        _validate_tenant_object(
            attrs.get("conversation", getattr(self.instance, "conversation", None)),
            tenant,
            "Conversation invalide pour ce tenant.",
        )
        return attrs

class ConversationSerializer(serializers.ModelSerializer):
    participants = ConversationParticipantSerializer(many=True, read_only=True)
    
    class Meta:
        model = Conversation
        fields = [
            "id", "title", "status", "content_type", "object_id",
            "participants", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "participants", "created_at", "updated_at"]

    def validate(self, attrs):
        tenant = _request_tenant(self)
        content_type = attrs.get("content_type", getattr(self.instance, "content_type", None))
        object_id = attrs.get("object_id", getattr(self.instance, "object_id", None))

        if bool(content_type) != bool(object_id):
            raise serializers.ValidationError("content_type et object_id doivent etre fournis ensemble.")
        if content_type and object_id:
            try:
                linked_object = content_type.get_object_for_this_type(id=object_id)
            except Exception:
                raise serializers.ValidationError("Objet lie introuvable.")
            if not hasattr(linked_object, "tenant_id"):
                raise serializers.ValidationError("Objet lie non compatible avec le tenant.")
            _validate_tenant_object(
                linked_object,
                tenant,
                "Objet lie invalide pour ce tenant.",
            )
        return attrs
