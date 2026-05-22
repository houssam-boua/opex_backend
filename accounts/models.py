# accounts/models.py
import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from accounts.managers import TenantManager


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff",     True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role",         "super_admin")
        return self.create_user(email, password, **extra)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    ROLES = [
        ("super_admin",   "Super Admin OPEX"),
        ("tenant_admin",  "Admin Entreprise"),
        ("plant_manager", "Directeur / Plant Manager"),
        ("quality_mgr",   "Responsable Qualité"),
        ("auditor",       "Auditeur"),
        ("supervisor",    "Superviseur"),
        ("operator",      "Opérateur"),
        ("viewer",        "Lecteur"),
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant      = models.ForeignKey(
        "core.Tenant", on_delete=models.CASCADE,
        null=True, blank=True, related_name="users"
    )
    # ─────────────────────────────────────────────────────────────────
    # FIX V3 : email n'est PAS unique globalement.
    # Deux tenants différents peuvent avoir le même email.
    # L'unicité est garantie par la contrainte (tenant, email).
    # ─────────────────────────────────────────────────────────────────
    email       = models.EmailField()
    first_name  = models.CharField(max_length=100, blank=True)
    last_name   = models.CharField(max_length=100, blank=True)
    role        = models.CharField(max_length=20, choices=ROLES, default="operator")
    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "accounts_users"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"],
                name="unique_email_per_tenant"
            )
        ]
        # Super admins (tenant=NULL) gardent un email unique via la DB
        # car la contrainte ne s'applique pas sur NULL

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    @property
    def is_super_admin(self):
        return self.role == "super_admin"


class Site(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant     = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    name       = models.CharField(max_length=200)
    city       = models.CharField(max_length=100, blank=True)
    is_main    = models.BooleanField(default=False)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    objects    = TenantManager()

    class Meta:
        db_table = "accounts_sites"


class Department(models.Model):
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant    = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    site      = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True)
    name      = models.CharField(max_length=150)
    code      = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    objects   = TenantManager()

    class Meta:
        db_table = "accounts_departments"


class Employee(models.Model):
    """
    Fiche RH centrale. Partagée par TOUS les modules.
    user_account OPTIONNEL — scénario hybride.
    Opérateurs terrain sans smartphone = Employee sans CustomUser.
    """
    STATUS   = [("active","Actif"),("inactive","Inactif"),("on_leave","En congé")]
    CONTRACT = [("cdi","CDI"),("cdd","CDD"),("interim","Intérim"),("stagiaire","Stagiaire")]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant       = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    user_account = models.OneToOneField(
        CustomUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="employee_profile"
    )
    employee_id   = models.CharField(max_length=50, blank=True)
    first_name    = models.CharField(max_length=100)
    last_name     = models.CharField(max_length=100)
    email         = models.EmailField(blank=True)
    department    = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True)
    site          = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True)
    manager       = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    contract_type = models.CharField(max_length=20, choices=CONTRACT, default="cdi")
    hire_date     = models.DateField(null=True, blank=True)
    status        = models.CharField(max_length=20, choices=STATUS, default="active")
    is_active     = models.BooleanField(default=True)
    is_deleted    = models.BooleanField(default=False)
    deleted_at    = models.DateTimeField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        db_table = "accounts_employees"
        indexes  = [models.Index(fields=["tenant", "department"])]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
