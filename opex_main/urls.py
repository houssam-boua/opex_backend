# opex_main/urls.py
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from accounts.authentication import LoginView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("admin/",          admin.site.urls),
    path("api/v1/schema/",  SpectacularAPIView.as_view(),                          name="schema"),
    path("api/v1/swagger/", SpectacularSwaggerView.as_view(url_name="schema"),   name="swagger"),
    # Auth
    path("api/v1/auth/login/",   LoginView.as_view(),        name="login"),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Core apps
    path("api/v1/accounts/",  include("accounts.urls")),
    path("api/v1/billing/",   include("billing.urls")),
    path("api/v1/shared/",    include("shared.urls")),
    path("api/v1/analytics/", include("analytics.urls")),
    # 18 Modules — tous préfixés /api/v1/
    path("api/v1/gemba/",             include("modules.gemba.urls")),
    path("api/v1/audits/",            include("modules.audits.urls")),
    path("api/v1/iso9001/",           include("modules.iso9001.urls")),
    path("api/v1/5s/",                include("modules.five_s.urls")),
    path("api/v1/tpm/",               include("modules.tpm.urls")),
    path("api/v1/lean-flow/",         include("modules.lean_flow.urls")),
    path("api/v1/vsm/",               include("modules.vsm.urls")),
    path("api/v1/smed/",              include("modules.smed.urls")),
    path("api/v1/sfm/",               include("modules.sfm.urls")),
    path("api/v1/rotation/",          include("modules.rotation_table.urls")),
    path("api/v1/capa/",              include("modules.capa.urls")),
    path("api/v1/risk/",              include("modules.risk.urls")),
    path("api/v1/problem-solving/",   include("modules.problem_solving.urls")),
    path("api/v1/poka-yoke/",         include("modules.poka_yoke.urls")),
    path("api/v1/skills/",            include("modules.skills.urls")),
    path("api/v1/visual-management/", include("modules.visual_management.urls")),
    path("api/v1/routines/",          include("modules.routines.urls")),
    path("api/v1/messaging/",         include("modules.messaging.urls")),
]
