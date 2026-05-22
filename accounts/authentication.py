# accounts/authentication.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate


class LoginView(APIView):
    permission_classes = []

    def post(self, request):
        email    = request.data.get("email")
        password = request.data.get("password")
        tenant   = request.tenant

        if not tenant:
            return Response({"error": "Tenant introuvable."}, status=400)

        user = authenticate(request, email=email, password=password)
        if not user:
            return Response({"error": "Email ou mot de passe incorrect."}, status=401)

        if not user.is_super_admin and user.tenant_id != tenant.id:
            return Response({"error": "Accès refusé."}, status=403)

        if not tenant.is_active:
            return Response({"error": "Compte suspendu ou expiré."}, status=403)

        refresh = RefreshToken.for_user(user)

        return Response({
            "access":  str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id":             str(user.id),
                "email":          user.email,
                "full_name":      user.full_name,
                "role":           user.role,
                "is_super_admin": user.is_super_admin,
            },
            "tenant": {
                "id":   str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "plan": tenant.plan,
            },
            "modules": tenant.license.to_dict(),
        })
