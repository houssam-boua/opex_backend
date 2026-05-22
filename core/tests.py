from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Employee
from billing.models import SubscriptionPlan
from billing.services import activate_license_key, generate_license_key
from core.models import Tenant
from modules.capa.models import CapaTicket
from modules.messaging.models import Conversation, ConversationParticipant
from modules.poka_yoke.models import PokaYokeCheck, PokaYokeDevice
from modules.poka_yoke.services import PokaYokeService
from modules.routines.models import RoutineTemplate
from modules.sfm.models import SFMSession
from modules.tpm.models import Machine
from shared.models import Action, Notification


TEST_SETTINGS = {
    "ALLOWED_HOSTS": ["*"],
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "CELERY_TASK_ALWAYS_EAGER": True,
    "CHANNEL_LAYERS": {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
}


@override_settings(**TEST_SETTINGS)
class ProductionSafetyTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.starter = cls._plan("starter", 10)
        cls.pro = cls._plan("pro", 50)
        cls.enterprise = cls._plan("enterprise", 250)

    @classmethod
    def _plan(cls, name, max_users):
        return SubscriptionPlan.objects.update_or_create(
            name=name,
            defaults={
                "display_name": name.title(),
                "price_eur": Decimal("99.00"),
                "max_users": max_users,
                "modules": [],
                "is_active": True,
            },
        )[0]

    def tenant_host(self, tenant):
        return f"{tenant.slug}.opex.test"

    def make_tenant(self, slug, plan="enterprise", max_users=250, status="active"):
        tenant = Tenant.objects.create(
            name=slug.replace("-", " ").title(),
            slug=slug,
            plan=plan,
            status=status,
            max_users=max_users,
        )
        tenant.license.activate_plan(plan)
        return tenant

    def make_user_employee(self, tenant, email, role="tenant_admin", first="Test", last="User"):
        user = CustomUser.objects.create_user(
            email=email,
            password="StrongPass123!",
            tenant=tenant,
            role=role,
            first_name=first,
            last_name=last,
        )
        employee = Employee.objects.create(
            tenant=tenant,
            user_account=user,
            email=email,
            first_name=first,
            last_name=last,
        )
        return user, employee

    def result_ids(self, response):
        data = response.data
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {str(row["id"]) for row in rows}

    def test_tenant_isolation_and_cross_tenant_fk_rejection(self):
        tenant_a = self.make_tenant("tenant-a")
        tenant_b = self.make_tenant("tenant-b")
        user_a, employee_a = self.make_user_employee(tenant_a, "admin-a@example.com")
        user_b, employee_b = self.make_user_employee(tenant_b, "admin-b@example.com")

        capa_a = CapaTicket.objects.create(tenant=tenant_a, title="A CAPA", pilot=employee_a, created_by=user_a)
        capa_b = CapaTicket.objects.create(tenant=tenant_b, title="B CAPA", pilot=employee_b, created_by=user_b)
        machine_a = Machine.objects.create(tenant=tenant_a, code="A1", nom="Machine A", emplacement="A", cadence_theorique=1, created_by=user_a)
        machine_b = Machine.objects.create(tenant=tenant_b, code="B1", nom="Machine B", emplacement="B", cadence_theorique=1, created_by=user_b)
        sfm_a = SFMSession.objects.create(tenant=tenant_a, date=timezone.localdate(), line="A", tier_level="tier_1", created_by=user_a)
        sfm_b = SFMSession.objects.create(tenant=tenant_b, date=timezone.localdate(), line="B", tier_level="tier_1", created_by=user_b)
        routine_a = RoutineTemplate.objects.create(tenant=tenant_a, title="Routine A", frequency="daily", line="A", status="active", owner=employee_a, created_by=user_a)
        routine_b = RoutineTemplate.objects.create(tenant=tenant_b, title="Routine B", frequency="daily", line="B", status="active", owner=employee_b, created_by=user_b)
        device_a = PokaYokeDevice.objects.create(tenant=tenant_a, name="Device A", status="active", owner=employee_a, machine=machine_a, created_by=user_a)
        device_b = PokaYokeDevice.objects.create(tenant=tenant_b, name="Device B", status="active", owner=employee_b, machine=machine_b, created_by=user_b)

        ct = ContentType.objects.get_for_model(CapaTicket)
        conv_a = Conversation.objects.create(tenant=tenant_a, title="A conversation", content_type=ct, object_id=capa_a.id, created_by=user_a)
        conv_b = Conversation.objects.create(tenant=tenant_b, title="B conversation", content_type=ct, object_id=capa_b.id, created_by=user_b)
        ConversationParticipant.objects.create(tenant=tenant_a, conversation=conv_a, user=employee_a, created_by=user_a)
        ConversationParticipant.objects.create(tenant=tenant_b, conversation=conv_b, user=employee_b, created_by=user_b)

        self.client.force_authenticate(user=user_a)
        endpoints = [
            ("/api/v1/capa/actions/", capa_a.id, capa_b.id),
            ("/api/v1/tpm/machines/", machine_a.id, machine_b.id),
            ("/api/v1/sfm/sessions/", sfm_a.id, sfm_b.id),
            ("/api/v1/routines/templates/", routine_a.id, routine_b.id),
            ("/api/v1/poka-yoke/devices/", device_a.id, device_b.id),
            ("/api/v1/messaging/conversations/", conv_a.id, conv_b.id),
        ]
        for endpoint, own_id, foreign_id in endpoints:
            response = self.client.get(endpoint, HTTP_HOST=self.tenant_host(tenant_a))
            self.assertEqual(response.status_code, 200)
            ids = self.result_ids(response)
            self.assertIn(str(own_id), ids)
            self.assertNotIn(str(foreign_id), ids)

        response = self.client.post(
            "/api/v1/poka-yoke/devices/",
            {
                "name": "Attack device",
                "status": "active",
                "machine": str(machine_b.id),
                "owner": str(employee_a.id),
            },
            format="json",
            HTTP_HOST=self.tenant_host(tenant_a),
        )
        self.assertEqual(response.status_code, 400)

    def test_module_licensing_blocks_and_restores_endpoint_access(self):
        tenant = self.make_tenant("licensed-tenant")
        user, _employee = self.make_user_employee(tenant, "license-admin@example.com")
        self.client.force_authenticate(user=user)

        tenant.license.is_sfm_active = False
        tenant.license.save(update_fields=["is_sfm_active", "updated_at"])
        response = self.client.get("/api/v1/sfm/sessions/", HTTP_HOST=self.tenant_host(tenant))
        self.assertEqual(response.status_code, 403)

        tenant.license.is_sfm_active = True
        tenant.license.save(update_fields=["is_sfm_active", "updated_at"])
        response = self.client.get("/api/v1/sfm/sessions/", HTTP_HOST=self.tenant_host(tenant))
        self.assertEqual(response.status_code, 200)

    def test_billing_license_activation_and_plan_max_users(self):
        superadmin = CustomUser.objects.create_superuser(email="super@example.com", password="StrongPass123!")
        tenant = self.make_tenant("activation-tenant", plan="starter", max_users=10, status="trial")
        tenant_admin, _employee = self.make_user_employee(tenant, "activate@example.com")

        self.client.force_authenticate(user=superadmin)
        response = self.client.post(
            "/api/v1/billing/admin/license-keys/",
            {"plan": "enterprise", "duration_days": 30},
            format="json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201)
        key = response.data["key"]

        self.client.force_authenticate(user=tenant_admin)
        response = self.client.post(
            "/api/v1/billing/activate-license/",
            {"key": key},
            format="json",
            HTTP_HOST=self.tenant_host(tenant),
        )
        self.assertEqual(response.status_code, 200)
        tenant.refresh_from_db()
        self.assertEqual(tenant.status, "active")
        self.assertEqual(tenant.plan, "enterprise")
        self.assertEqual(tenant.max_users, self.enterprise.max_users)
        self.assertTrue(all(tenant.license.to_dict().values()))

        response = self.client.post(
            "/api/v1/billing/activate-license/",
            {"key": key},
            format="json",
            HTTP_HOST=self.tenant_host(tenant),
        )
        self.assertEqual(response.status_code, 400)

        for plan, expected in [("starter", 10), ("pro", 50), ("enterprise", 250)]:
            plan_tenant = self.make_tenant(f"{plan}-max-users", status="trial")
            license_key = generate_license_key(plan, duration_days=10)
            activate_license_key(plan_tenant, license_key.key)
            plan_tenant.refresh_from_db()
            self.assertEqual(plan_tenant.max_users, expected)

    def test_accounts_api_roles_employee_linking_and_max_users(self):
        tenant = self.make_tenant("accounts-tenant", max_users=5)
        tenant_b = self.make_tenant("accounts-tenant-b", max_users=5)
        admin, _employee = self.make_user_employee(tenant, "accounts-admin@example.com")
        _user_b, employee_b = self.make_user_employee(tenant_b, "accounts-b@example.com")
        unlinked_b = Employee.objects.create(tenant=tenant_b, first_name="Foreign", last_name="Employee")

        self.client.force_authenticate(user=admin)
        response = self.client.post(
            "/api/v1/accounts/users/",
            {
                "email": "new-user@example.com",
                "password": "StrongPass123!",
                "role": "operator",
                "first_name": "New",
                "last_name": "User",
            },
            format="json",
            HTTP_HOST=self.tenant_host(tenant),
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            "/api/v1/accounts/users/",
            {
                "email": "bad-super@example.com",
                "password": "StrongPass123!",
                "role": "super_admin",
            },
            format="json",
            HTTP_HOST=self.tenant_host(tenant),
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/v1/accounts/users/",
            {
                "email": "cross-link@example.com",
                "password": "StrongPass123!",
                "role": "operator",
                "employee_id": str(unlinked_b.id),
            },
            format="json",
            HTTP_HOST=self.tenant_host(tenant),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(employee_b.tenant_id, tenant_b.id)

        tenant.max_users = CustomUser.objects.filter(tenant=tenant, is_active=True).count()
        tenant.save(update_fields=["max_users", "updated_at"])
        response = self.client.post(
            "/api/v1/accounts/users/",
            {
                "email": "over-limit@example.com",
                "password": "StrongPass123!",
                "role": "operator",
            },
            format="json",
            HTTP_HOST=self.tenant_host(tenant),
        )
        self.assertEqual(response.status_code, 400)

    def test_superadmin_api_and_tenant_archive_soft_delete(self):
        tenant = self.make_tenant("superadmin-target")
        tenant_admin, _employee = self.make_user_employee(tenant, "target-admin@example.com")
        superadmin = CustomUser.objects.create_superuser(email="root@example.com", password="StrongPass123!")

        self.client.force_authenticate(user=tenant_admin)
        response = self.client.get("/api/v1/billing/admin/tenants/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(user=superadmin)
        response = self.client.post(
            "/api/v1/billing/admin/tenants/",
            {
                "name": "Created By Superadmin",
                "slug": "created-by-superadmin",
                "status": "trial",
                "plan": "starter",
                "max_users": 10,
            },
            format="json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201)
        created_tenant = Tenant.objects.get(slug="created-by-superadmin")

        response = self.client.patch(
            f"/api/v1/billing/admin/plans/{self.starter.id}/",
            {"max_users": 12},
            format="json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        self.starter.refresh_from_db()
        self.assertEqual(self.starter.max_users, 12)

        response = self.client.post(
            "/api/v1/billing/admin/license-keys/",
            {"plan": "starter", "duration_days": 30},
            format="json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            f"/api/v1/billing/admin/tenants/{created_tenant.id}/suspend/",
            format="json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        created_tenant.refresh_from_db()
        self.assertEqual(created_tenant.status, "suspended")

        response = self.client.post(
            f"/api/v1/billing/admin/tenants/{created_tenant.id}/reactivate/",
            format="json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        created_tenant.refresh_from_db()
        self.assertEqual(created_tenant.status, "active")
        created_admin, _created_employee = self.make_user_employee(
            created_tenant,
            "created-admin@example.com",
        )

        response = self.client.post(
            f"/api/v1/billing/admin/tenants/{created_tenant.id}/archive/",
            format="json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        created_tenant.refresh_from_db()
        self.assertEqual(created_tenant.status, "suspended")
        self.assertIsNotNone(created_tenant.archived_at)

        self.client.force_authenticate(user=created_admin)
        response = self.client.get(
            "/api/v1/accounts/tenant/",
            HTTP_HOST=self.tenant_host(created_tenant),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "tenant_archived")

        self.client.force_authenticate(user=superadmin)
        capa = CapaTicket.objects.create(tenant=created_tenant, title="Preserved CAPA")
        response = self.client.delete(
            f"/api/v1/billing/admin/tenants/{created_tenant.id}/",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 204)
        created_tenant.refresh_from_db()
        self.assertTrue(created_tenant.is_deleted)
        self.assertEqual(created_tenant.status, "suspended")
        self.assertTrue(CapaTicket.objects.filter(id=capa.id, tenant=created_tenant).exists())

        self.client.force_authenticate(user=created_admin)
        response = self.client.get(
            "/api/v1/accounts/tenant/",
            HTTP_HOST=self.tenant_host(created_tenant),
        )
        self.assertEqual(response.status_code, 403)

    def test_shared_action_and_notification_tenant_integrity(self):
        tenant = self.make_tenant("shared-tenant")
        user, employee = self.make_user_employee(tenant, "shared-admin@example.com")
        capa = CapaTicket.objects.create(tenant=tenant, title="Action source", pilot=employee, created_by=user)
        action = capa.sync_to_shared_action()
        self.assertEqual(action.tenant_id, tenant.id)
        self.assertEqual(action.module_source, "capa")

        device = PokaYokeDevice.objects.create(tenant=tenant, name="Notify device", status="active", owner=employee, created_by=user)
        check = PokaYokeCheck.objects.create(
            tenant=tenant,
            device=device,
            checked_by=employee,
            checked_at=timezone.now(),
            result=PokaYokeCheck.Result.FAILED,
            created_by=user,
        )
        PokaYokeService.evaluate_check(check)
        notification = Notification.objects.get(
            tenant=tenant,
            recipient=user,
            notification_type="poka_yoke_check_failed",
            related_object_id=check.id,
        )
        self.assertEqual(notification.tenant_id, tenant.id)
        self.assertEqual(notification.recipient_id, user.id)

    def test_messaging_generic_foreign_key_and_cross_tenant_rejection(self):
        tenant_a = self.make_tenant("messaging-a")
        tenant_b = self.make_tenant("messaging-b")
        user_a, employee_a = self.make_user_employee(tenant_a, "msg-a@example.com")
        user_b, employee_b = self.make_user_employee(tenant_b, "msg-b@example.com")
        capa_a = CapaTicket.objects.create(tenant=tenant_a, title="A linked CAPA", pilot=employee_a, created_by=user_a)
        capa_b = CapaTicket.objects.create(tenant=tenant_b, title="B linked CAPA", pilot=employee_b, created_by=user_b)
        ct = ContentType.objects.get_for_model(CapaTicket)

        self.client.force_authenticate(user=user_a)
        response = self.client.post(
            "/api/v1/messaging/conversations/",
            {"title": "Tenant A thread", "content_type": ct.id, "object_id": str(capa_a.id)},
            format="json",
            HTTP_HOST=self.tenant_host(tenant_a),
        )
        self.assertEqual(response.status_code, 201)
        conversation = Conversation.objects.get(id=response.data["id"])
        self.assertEqual(conversation.linked_item, capa_a)
        self.assertTrue(ConversationParticipant.objects.filter(conversation=conversation, user=employee_a).exists())

        response = self.client.post(
            "/api/v1/messaging/conversations/",
            {"title": "Attack thread", "content_type": ct.id, "object_id": str(capa_b.id)},
            format="json",
            HTTP_HOST=self.tenant_host(tenant_a),
        )
        self.assertEqual(response.status_code, 400)
