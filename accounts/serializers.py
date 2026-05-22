from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import CustomUser, Department, Employee, Site


USER_READ_FIELDS = [
    "id",
    "email",
    "first_name",
    "last_name",
    "role",
    "is_active",
    "employee_id",
    "created_at",
]


def _request_tenant(serializer):
    request = serializer.context.get("request")
    return getattr(request, "tenant", None)


def _validate_same_tenant(obj, tenant, label):
    if obj and tenant and obj.tenant_id != tenant.id:
        raise serializers.ValidationError(f"{label} does not belong to this tenant.")


class EmployeeSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True)
    manager_name = serializers.CharField(source="manager.full_name", read_only=True)
    user_account_id = serializers.UUIDField(source="user_account.id", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "department",
            "department_name",
            "site",
            "site_name",
            "manager",
            "manager_name",
            "contract_type",
            "hire_date",
            "status",
            "is_active",
            "user_account_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "full_name",
            "is_active",
            "user_account_id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        tenant = _request_tenant(self)
        department = attrs.get("department", getattr(self.instance, "department", None))
        site = attrs.get("site", getattr(self.instance, "site", None))
        manager = attrs.get("manager", getattr(self.instance, "manager", None))
        _validate_same_tenant(department, tenant, "Department")
        _validate_same_tenant(site, tenant, "Site")
        _validate_same_tenant(manager, tenant, "Manager")
        if manager and self.instance and manager.id == self.instance.id:
            raise serializers.ValidationError("Employee cannot manage themselves.")
        return attrs


class UserSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(source="date_joined", read_only=True)
    employee_id = serializers.SerializerMethodField()
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = USER_READ_FIELDS + ["employee_name"]
        read_only_fields = fields

    def get_employee_id(self, obj):
        employee = getattr(obj, "employee_profile", None)
        return str(employee.id) if employee else None

    def get_employee_name(self, obj):
        employee = getattr(obj, "employee_profile", None)
        return employee.full_name if employee else None


class UserCreateSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(source="date_joined", read_only=True)
    password = serializers.CharField(write_only=True, required=True, trim_whitespace=False)
    employee_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "password",
            "employee_id",
            "created_at",
        ]
        read_only_fields = ["id", "is_active", "created_at"]

    def validate_role(self, value):
        if value == "super_admin":
            raise serializers.ValidationError("Cannot create super_admin users through tenant API.")
        allowed = {choice[0] for choice in CustomUser.ROLES if choice[0] != "super_admin"}
        if value not in allowed:
            raise serializers.ValidationError("Invalid role.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_email(self, value):
        tenant = _request_tenant(self)
        if tenant and CustomUser.objects.filter(tenant=tenant, email=value).exists():
            raise serializers.ValidationError("A user with this email already exists in this tenant.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        if not tenant:
            raise serializers.ValidationError("Tenant context is required.")
        active_users = CustomUser.objects.filter(tenant=tenant, is_active=True).count()
        if active_users >= tenant.max_users:
            raise serializers.ValidationError("Tenant user limit reached.")
        employee_id = attrs.get("employee_id")
        if employee_id:
            employee = Employee.objects.filter(
                id=employee_id,
                tenant=tenant,
                is_active=True,
                is_deleted=False,
            ).first()
            if not employee:
                raise serializers.ValidationError({"employee_id": "Employee does not belong to this tenant."})
            if employee.user_account_id:
                raise serializers.ValidationError({"employee_id": "Employee is already linked to a user."})
            attrs["_employee"] = employee
        return attrs

    def create(self, validated_data):
        employee = validated_data.pop("_employee", None)
        validated_data.pop("employee_id", None)
        password = validated_data.pop("password")
        tenant = _request_tenant(self)
        user = CustomUser.objects.create_user(
            tenant=tenant,
            password=password,
            **validated_data,
        )
        if employee:
            employee.user_account = user
            employee.email = employee.email or user.email
            employee.save(update_fields=["user_account", "email", "updated_at"])
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(source="date_joined", read_only=True)
    employee_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "employee_id",
            "created_at",
        ]
        read_only_fields = ["id", "email", "created_at"]

    def validate_role(self, value):
        if value == "super_admin":
            raise serializers.ValidationError("Cannot assign super_admin through tenant API.")
        allowed = {choice[0] for choice in CustomUser.ROLES if choice[0] != "super_admin"}
        if value not in allowed:
            raise serializers.ValidationError("Invalid role.")
        return value

    def validate(self, attrs):
        tenant = _request_tenant(self)
        employee_id = attrs.get("employee_id")
        if employee_id is not None:
            employee = None
            if employee_id:
                employee = Employee.objects.filter(
                    id=employee_id,
                    tenant=tenant,
                    is_active=True,
                    is_deleted=False,
                ).first()
                if not employee:
                    raise serializers.ValidationError({"employee_id": "Employee does not belong to this tenant."})
                if employee.user_account_id and employee.user_account_id != self.instance.id:
                    raise serializers.ValidationError({"employee_id": "Employee is already linked to another user."})
            attrs["_employee"] = employee
        return attrs

    def update(self, instance, validated_data):
        employee = validated_data.pop("_employee", None)
        employee_id_present = "employee_id" in validated_data
        validated_data.pop("employee_id", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if employee_id_present:
            Employee.objects.filter(user_account=instance).update(user_account=None)
            if employee:
                employee.user_account = instance
                employee.email = employee.email or instance.email
                employee.save(update_fields=["user_account", "email", "updated_at"])
        return instance


class SetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        validate_password(value)
        return value


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class MeSerializer(serializers.Serializer):
    user = UserSerializer(read_only=True)
    employee = EmployeeSerializer(read_only=True, allow_null=True)
    tenant = serializers.DictField(read_only=True)
    modules = serializers.DictField(read_only=True)
    role = serializers.CharField(read_only=True)


class TenantSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    plan = serializers.CharField(read_only=True)
    subscription_ends_at = serializers.DateField(read_only=True, allow_null=True)
    max_users = serializers.IntegerField(read_only=True)
    license = serializers.DictField(read_only=True)
