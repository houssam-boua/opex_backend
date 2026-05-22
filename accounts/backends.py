# accounts/backends.py
"""
Custom authentication backend for OPEX multi-tenant auth.

Django requires USERNAME_FIELD to be unique, but our architecture uses
(tenant, email) as the unique constraint. This backend handles authentication
by looking up users by email within the context of their tenant.
"""
from django.contrib.auth.backends import ModelBackend
from accounts.models import CustomUser


class TenantEmailBackend(ModelBackend):
    """
    Authenticates against CustomUser using email.
    Since email is not globally unique (unique per tenant),
    we filter by email and validate the password.
    """
    def authenticate(self, request, email=None, password=None, **kwargs):
        # Also support 'username' kwarg for admin compatibility
        if email is None:
            email = kwargs.get("username")
        if email is None:
            return None

        # Get tenant from request if available
        tenant = getattr(request, "tenant", None) if request else None

        try:
            if tenant:
                user = CustomUser.objects.get(tenant=tenant, email=email)
            else:
                # Super admin login or admin panel (no tenant context)
                # Try to find a unique user with this email
                users = CustomUser.objects.filter(email=email)
                if users.count() == 1:
                    user = users.first()
                else:
                    # Multiple users with same email across tenants
                    # Try super_admin first
                    user = users.filter(role="super_admin").first()
                    if not user:
                        return None
        except CustomUser.DoesNotExist:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
