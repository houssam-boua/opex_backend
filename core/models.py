# core/models.py
import uuid
from django.db import models


class Tenant(models.Model):
    PLAN   = [("starter","Starter"),("pro","Pro"),("enterprise","Enterprise")]
    STATUS = [("trial","Essai"),("active","Actif"),
              ("suspended","Suspendu"),("expired","Expiré")]

    id                     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name                   = models.CharField(max_length=200)
    slug                   = models.SlugField(max_length=100, unique=True)
    plan                   = models.CharField(max_length=20, choices=PLAN, default="trial")
    status                 = models.CharField(max_length=20, choices=STATUS, default="trial")
    contact_email          = models.EmailField(blank=True)
    max_users              = models.IntegerField(default=10)
    trial_ends_at          = models.DateField(null=True, blank=True)
    subscription_ends_at   = models.DateField(null=True, blank=True)
    created_at             = models.DateTimeField(auto_now_add=True)
    updated_at             = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_tenants"

    def __str__(self):
        return f"{self.name} ({self.plan})"

    @property
    def is_active(self):
        return self.status in ["active", "trial"]


class TenantLicense(models.Model):
    """
    1 ligne par tenant. 18 feature flags.
    Toujours créée automatiquement à la création du Tenant (signal post_save).
    """
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="license")

    # Audit & Compliance
    is_gemba_active       = models.BooleanField(default=False)
    is_audits_active      = models.BooleanField(default=False)
    is_iso9001_active     = models.BooleanField(default=False)
    is_5s_active          = models.BooleanField(default=False)
    is_tpm_active         = models.BooleanField(default=False)
    # Lean / Flow
    is_lean_flow_active   = models.BooleanField(default=False)
    is_vsm_active         = models.BooleanField(default=False)
    is_smed_active        = models.BooleanField(default=False)
    is_sfm_active         = models.BooleanField(default=False)
    is_rotation_active    = models.BooleanField(default=False)
    # Quality & Risk
    is_capa_active            = models.BooleanField(default=False)
    is_risk_active            = models.BooleanField(default=False)
    is_problem_solving_active = models.BooleanField(default=False)
    is_poka_yoke_active       = models.BooleanField(default=False)
    # People & Communication
    is_skills_active      = models.BooleanField(default=False)
    is_visual_mgmt_active = models.BooleanField(default=False)
    is_routines_active    = models.BooleanField(default=False)
    is_messaging_active   = models.BooleanField(default=True)  # Toujours actif

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_tenant_licenses"

    def to_dict(self):
        return {
            "gemba":           self.is_gemba_active,
            "audits":          self.is_audits_active,
            "iso9001":         self.is_iso9001_active,
            "5s":              self.is_5s_active,
            "tpm":             self.is_tpm_active,
            "lean_flow":       self.is_lean_flow_active,
            "vsm":             self.is_vsm_active,
            "smed":            self.is_smed_active,
            "sfm":             self.is_sfm_active,
            "rotation":        self.is_rotation_active,
            "capa":            self.is_capa_active,
            "risk":            self.is_risk_active,
            "problem_solving": self.is_problem_solving_active,
            "poka_yoke":       self.is_poka_yoke_active,
            "skills":          self.is_skills_active,
            "visual_mgmt":     self.is_visual_mgmt_active,
            "routines":        self.is_routines_active,
            "messaging":       self.is_messaging_active,
        }

    def activate_plan(self, plan: str):
        """Active les modules selon le plan souscrit."""
        if plan in ("starter", "pro", "enterprise"):
            self.is_gemba_active     = True
            self.is_5s_active        = True
            self.is_capa_active      = True
            self.is_messaging_active = True
        if plan in ("pro", "enterprise"):
            self.is_audits_active          = True
            self.is_iso9001_active         = True
            self.is_tpm_active             = True
            self.is_smed_active            = True
            self.is_risk_active            = True
            self.is_problem_solving_active = True
            self.is_routines_active        = True
        if plan == "enterprise":
            self.is_lean_flow_active   = True
            self.is_vsm_active         = True
            self.is_sfm_active         = True
            self.is_rotation_active    = True
            self.is_poka_yoke_active   = True
            self.is_skills_active      = True
            self.is_visual_mgmt_active = True
        self.save()


# Signal — auto-créer TenantLicense à chaque nouveau Tenant
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Tenant)
def create_tenant_license(sender, instance, created, **kwargs):
    if created:
        TenantLicense.objects.get_or_create(tenant=instance)
