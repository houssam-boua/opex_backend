from django.db import transaction
from rest_framework import serializers

from billing.models import LicenseKey, SubscriptionPlan
from billing.services import activate_license_key, generate_license_key
from core.models import Tenant, TenantLicense


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "name",
            "display_name",
            "price_eur",
            "max_users",
            "modules",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        allowed = {choice[0] for choice in SubscriptionPlan.PLAN_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError("Invalid plan name.")
        return value

    def validate_price_eur(self, value):
        if value < 0:
            raise serializers.ValidationError("Price must be greater than or equal to 0.")
        return value

    def validate_max_users(self, value):
        if value <= 0:
            raise serializers.ValidationError("max_users must be greater than 0.")
        return value

    def validate_modules(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("modules must be a list.")
        valid_modules = set(TenantLicense(tenant=Tenant(name="x", slug="x")).to_dict().keys())
        invalid = sorted(set(value) - valid_modules)
        if invalid:
            raise serializers.ValidationError(f"Invalid module keys: {', '.join(invalid)}")
        return value


class LicenseKeySerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    activated_by_tenant_name = serializers.CharField(source="activated_by_tenant.name", read_only=True)

    class Meta:
        model = LicenseKey
        fields = [
            "id",
            "key",
            "plan",
            "plan_name",
            "duration_days",
            "is_used",
            "activated_by_tenant",
            "activated_by_tenant_name",
            "activated_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "key",
            "is_used",
            "activated_by_tenant",
            "activated_by_tenant_name",
            "activated_at",
            "created_at",
        ]


class LicenseKeyGenerateSerializer(serializers.Serializer):
    plan = serializers.SlugRelatedField(
        slug_field="name",
        queryset=SubscriptionPlan.objects.filter(is_active=True),
    )
    duration_days = serializers.IntegerField(default=365, min_value=1)

    def create(self, validated_data):
        request = self.context["request"]
        return generate_license_key(
            plan_name=validated_data["plan"].name,
            duration_days=validated_data["duration_days"],
            created_by=request.user,
            tenant=None,
        )


class TenantAdminSerializer(serializers.ModelSerializer):
    license = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "contact_email",
            "status",
            "plan",
            "subscription_ends_at",
            "max_users",
            "trial_ends_at",
            "is_deleted",
            "deleted_at",
            "archived_at",
            "license",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_deleted", "deleted_at", "archived_at", "license", "created_at", "updated_at"]

    def get_license(self, obj):
        license_obj, _ = TenantLicense.objects.get_or_create(tenant=obj)
        return license_obj.to_dict()

    def validate_status(self, value):
        allowed = {choice[0] for choice in Tenant.STATUS}
        if value not in allowed:
            raise serializers.ValidationError("Invalid tenant status.")
        return value

    def validate_plan(self, value):
        allowed = {choice[0] for choice in Tenant.PLAN}
        if value not in allowed:
            raise serializers.ValidationError("Invalid tenant plan.")
        return value

    def validate_max_users(self, value):
        if value <= 0:
            raise serializers.ValidationError("max_users must be greater than 0.")
        return value

    def create(self, validated_data):
        tenant = super().create(validated_data)
        TenantLicense.objects.get_or_create(tenant=tenant)
        return tenant


class TenantLicenseSerializer(serializers.Serializer):
    modules = serializers.DictField(child=serializers.BooleanField(), required=False)
    activate_plan = serializers.ChoiceField(choices=[choice[0] for choice in Tenant.PLAN], required=False)

    def validate_modules(self, value):
        valid = set(TenantLicense(tenant=Tenant(name="x", slug="x")).to_dict().keys())
        invalid = sorted(set(value.keys()) - valid)
        if invalid:
            raise serializers.ValidationError(f"Invalid module keys: {', '.join(invalid)}")
        return value

    @transaction.atomic
    def save(self, **kwargs):
        tenant = self.context["tenant"]
        license_obj, _ = TenantLicense.objects.select_for_update().get_or_create(tenant=tenant)
        plan = self.validated_data.get("activate_plan")
        if plan:
            license_obj.activate_plan(plan)
            tenant.plan = plan
            tenant.save(update_fields=["plan", "updated_at"])
            license_obj.refresh_from_db()
        module_updates = self.validated_data.get("modules", {})
        reverse_map = {
            value: key
            for key, value in {
                "is_gemba_active": "gemba",
                "is_audits_active": "audits",
                "is_iso9001_active": "iso9001",
                "is_5s_active": "5s",
                "is_tpm_active": "tpm",
                "is_lean_flow_active": "lean_flow",
                "is_vsm_active": "vsm",
                "is_smed_active": "smed",
                "is_sfm_active": "sfm",
                "is_rotation_active": "rotation",
                "is_capa_active": "capa",
                "is_risk_active": "risk",
                "is_problem_solving_active": "problem_solving",
                "is_poka_yoke_active": "poka_yoke",
                "is_skills_active": "skills",
                "is_visual_mgmt_active": "visual_mgmt",
                "is_routines_active": "routines",
                "is_messaging_active": "messaging",
            }.items()
        }
        for module_key, enabled in module_updates.items():
            setattr(license_obj, reverse_map[module_key], enabled)
        if module_updates:
            license_obj.save()
        return license_obj


class ActivateLicenseSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=19)

    def validate_key(self, value):
        return value.strip().upper()

    def save(self, **kwargs):
        tenant = self.context["tenant"]
        return activate_license_key(tenant, self.validated_data["key"])
