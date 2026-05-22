"""
Phase 3.8 live enterprise model communication runner.

This script creates real database records, triggers service/task logic, verifies
persisted state, runs cross-tenant attacks, and prints a structured report.
Run only with: venv\\Scripts\\python phase_3_8_live_enterprise_e2e.py
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import date, time, timedelta
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opex_main.settings")

import django

django.setup()

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from accounts.managers import set_current_tenant
from accounts.models import CustomUser, Department, Employee, Site
from billing.models import SubscriptionPlan
from billing.services import activate_license_key, generate_license_key
from billing.tasks import check_expired_subscriptions
from core.models import Tenant
from modules.audits.models import AuditType
from modules.capa.models import CapaTicket
from modules.capa.tasks import send_due_reminders
from modules.five_s.models import Anomaly5S, AuditQuestion, AuditSession5S
from modules.gemba.models import Anomaly, Checkpoint, GembaCategory, GembaTeam, GembaZone, Tour
from modules.gemba.tasks import send_weekly_summary
from modules.iso9001.models import (
    CorrectiveAction,
    ISODocument,
    ISO9001Clause,
    ISO9001EvaluationSession,
    ISO9001Question,
    ISO9001Response,
    NonConformity,
)
from modules.iso9001.services import ISO9001Service
from modules.iso9001.tasks import check_iso_document_expiry_task
from modules.lean_flow.models import (
    DDMRPBuffer,
    DDMRPRecommendation,
    FlowBoard,
    FlowCard,
    FlowColumn,
    KanbanCard,
    KanbanFlowConfig,
)
from modules.messaging.models import Conversation, ConversationParticipant, Message
from modules.messaging.serializers import ConversationSerializer
from modules.messaging.consumers import get_conversation_participant
from modules.poka_yoke.models import PokaYokeCheck, PokaYokeDefect, PokaYokeDevice
from modules.poka_yoke.serializers import PokaYokeDeviceSerializer
from modules.poka_yoke.services import PokaYokeService
from modules.poka_yoke.tasks import check_overdue_poka_yoke_verifications_task
from modules.problem_solving.models import QRQC, QRQCAction
from modules.risk.models import Risk, RiskCategory, RiskMitigationAction
from modules.risk.services import RiskService
from modules.rotation_table.models import (
    RotationAssignment,
    RotationPlan,
    RotationRule,
    RotationSlot,
    RotationViolation,
    Workstation,
)
from modules.rotation_table.serializers import RotationAssignmentSerializer, WorkstationSerializer
from modules.rotation_table.services import RotationService
from modules.routines.models import (
    RoutineExecution,
    RoutineStep,
    RoutineStepResponse,
    RoutineTemplate,
)
from modules.routines.serializers import RoutineStepResponseSerializer
from modules.routines.services import RoutineService
from modules.routines.tasks import check_missed_routine_executions_task
from modules.sfm.models import SFMKPI, SFMSession
from modules.sfm.serializers import SFMKPISerializer
from modules.sfm.services import SFMService
from modules.skills.models import Certification, EmployeeSkill, Skill, SkillCategory
from modules.skills.services import SkillsService
from modules.skills.tasks import check_expiring_certifications_task
from modules.smed.models import SMEDSession, SMEDStep
from modules.smed.services import SMEDService
from modules.tpm.models import Breakdown, Machine, MaintenanceTask
from modules.visual_management.consumers import get_production_line
from modules.visual_management.models import AndonCall, ProductionLine
from modules.visual_management.serializers import AndonCallSerializer, ProductionLineSerializer
from modules.visual_management.services import AndonService
from modules.visual_management.tasks import check_andon_sla_breach_task
from modules.vsm.models import VSMElement, VSMMap
from modules.vsm.services import VSMService
from shared.models import Action, Notification


class Report:
    def __init__(self):
        self.rows = []
        self.bugs = []
        self.notes = []
        self.license_key = ""
        self.phase = ""
        self.created = {}

    def set_phase(self, phase):
        self.phase = phase
        print(f"\n[{phase}]")

    def check(self, name, ok, detail=""):
        status = "PASS" if ok else "FAIL"
        self.rows.append((self.phase, name, status, str(detail or "")))
        print(f"  {status:4} {name}" + (f" -- {detail}" if detail else ""))
        return ok

    def fail(self, name, exc):
        detail = f"{exc.__class__.__name__}: {exc}"
        self.rows.append((self.phase, name, "FAIL", detail))
        self.bugs.append(f"[{self.phase}] {name}: {detail}")
        print(f"  FAIL {name} -- {detail}")

    def bug(self, text):
        if text not in self.bugs:
            self.bugs.append(text)

    def summary_counts(self):
        counts = Counter(row[2] for row in self.rows)
        return counts["PASS"], counts["FAIL"]

    def by_phase(self):
        data = defaultdict(lambda: Counter())
        for phase, _name, status, _detail in self.rows:
            data[phase][status] += 1
        return data


R = Report()


def req_for(tenant, user):
    factory = APIRequestFactory()
    request = factory.post("/")
    request.tenant = tenant
    request.user = user
    return request


def tenant_host(slug):
    return f"{slug}.opex.local"


def clean_previous_data():
    set_current_tenant(None)
    Tenant.objects.filter(
        slug__in=["acme-e2e", "beta-e2e", "expired-e2e", "signal-e2e-test"]
    ).delete()


def create_plan(name, display, price, max_users, modules):
    return SubscriptionPlan.objects.update_or_create(
        name=name,
        defaults={
            "display_name": display,
            "price_eur": Decimal(str(price)),
            "max_users": max_users,
            "modules": modules,
            "is_active": True,
        },
    )[0]


def create_user_employee(tenant, site, departments, spec):
    label, email, role, first, last, dept_name = spec
    user = CustomUser.objects.create_user(
        email=email,
        password="Phase38!",
        tenant=tenant,
        role=role,
        first_name=first,
        last_name=last,
    )
    employee = Employee.objects.create(
        tenant=tenant,
        user_account=user,
        first_name=first,
        last_name=last,
        email=email,
        department=departments[dept_name],
        site=site,
    )
    return label, user, employee


def setup_enterprise():
    R.set_phase("A - Enterprise Tenant Setup")
    clean_previous_data()
    create_plan("starter", "Starter", 99, 10, ["gemba", "5s", "capa", "messaging"])
    create_plan("pro", "Pro", 199, 50, [])
    create_plan("enterprise", "Enterprise", 399, 200, ["all"])

    tenant = Tenant.objects.create(name="Acme Manufacturing E2E", slug="acme-e2e")
    R.check("Tenant created with requested slug", tenant.slug == "acme-e2e")
    R.check("TenantLicense auto-created", hasattr(tenant, "license"))

    license_key = generate_license_key("enterprise", duration_days=365)
    R.license_key = license_key.key
    activation = activate_license_key(tenant, license_key.key)
    tenant.refresh_from_db()
    license_flags = tenant.license.to_dict()
    R.check("Enterprise license activation returns success", activation.get("success") is True)
    R.check("Tenant status active", tenant.status == "active")
    R.check("Tenant plan enterprise", tenant.plan == "enterprise")
    R.check("Subscription end date set", tenant.subscription_ends_at is not None)
    R.check("All TenantLicense flags true", all(license_flags.values()), license_flags)

    site = Site.objects.create(tenant=tenant, name="Main Plant", city="Casablanca", is_main=True)
    departments = {}
    for name in ["Production", "Quality", "Maintenance", "Safety", "Continuous Improvement"]:
        departments[name] = Department.objects.create(tenant=tenant, site=site, name=name)
    R.check("Site and 5 departments created", len(departments) == 5)

    specs = [
        ("tenant_admin", "tenant-admin@acme-e2e.test", "tenant_admin", "Tenant", "Admin", "Production"),
        ("plant_manager", "plant-manager@acme-e2e.test", "plant_manager", "Plant", "Manager", "Production"),
        ("quality_manager", "quality-manager@acme-e2e.test", "quality_mgr", "Quality", "Manager", "Quality"),
        ("maintenance_manager", "maintenance-manager@acme-e2e.test", "supervisor", "Maintenance", "Manager", "Maintenance"),
        ("production_supervisor", "production-supervisor@acme-e2e.test", "supervisor", "Production", "Supervisor", "Production"),
        ("safety_officer", "safety-officer@acme-e2e.test", "supervisor", "Safety", "Officer", "Safety"),
        ("operator_1", "operator1@acme-e2e.test", "operator", "Operator", "One", "Production"),
        ("operator_2", "operator2@acme-e2e.test", "operator", "Operator", "Two", "Production"),
        ("maintenance_technician", "maintenance-tech@acme-e2e.test", "operator", "Maintenance", "Technician", "Maintenance"),
        ("auditor", "auditor@acme-e2e.test", "auditor", "Internal", "Auditor", "Quality"),
        ("ci_engineer", "ci-engineer@acme-e2e.test", "supervisor", "CI", "Engineer", "Continuous Improvement"),
    ]
    users = {}
    employees = {}
    for spec in specs:
        label, user, employee = create_user_employee(tenant, site, departments, spec)
        users[label] = user
        employees[label] = employee

    employees["operator_1"].manager = employees["production_supervisor"]
    employees["operator_2"].manager = employees["production_supervisor"]
    employees["maintenance_technician"].manager = employees["maintenance_manager"]
    employees["quality_manager"].manager = employees["plant_manager"]
    for employee in employees.values():
        employee.save(update_fields=["manager", "updated_at"])

    no_account_employee = Employee.objects.create(
        tenant=tenant,
        user_account=None,
        first_name="NoAccount",
        last_name="Operator",
        department=departments["Production"],
        site=site,
        manager=employees["production_supervisor"],
    )
    employees["no_account_operator"] = no_account_employee

    R.check("11 users created for Acme", CustomUser.objects.filter(tenant=tenant).count() == 11)
    R.check("12 employees created including no-account operator", Employee.objects.filter(tenant=tenant).count() == 12)
    R.check("All users belong to tenant", all(user.tenant_id == tenant.id for user in users.values()))
    R.check("All employees belong to tenant", all(emp.tenant_id == tenant.id for emp in employees.values()))
    R.check(
        "Operational users have Employee profiles",
        all(getattr(user, "employee_profile", None) for user in users.values()),
    )

    R.created.update({
        "tenant": tenant,
        "site": site,
        "departments": departments,
        "users": users,
        "employees": employees,
    })
    return tenant, site, departments, users, employees


def ensure_action(name, obj, expected_source, expected_employee=None, sync=None, expected_type=None):
    if sync is None:
        sync = obj.sync_to_shared_action
    action = sync()
    before = Action.objects.filter(
        tenant=obj.tenant,
        module_source=expected_source,
        reference_id=obj.id,
        is_active=True,
        is_deleted=False,
    ).count()
    action2 = sync()
    after = Action.objects.filter(
        tenant=obj.tenant,
        module_source=expected_source,
        reference_id=obj.id,
        is_active=True,
        is_deleted=False,
    ).count()
    ok = (
        action
        and action2
        and action.tenant_id == obj.tenant_id
        and action.module_source == expected_source
        and before == 1
        and after == 1
        and action.id == action2.id
    )
    if expected_employee is not None:
        ok = ok and action.assigned_to_id == expected_employee.id
    if expected_type:
        ok = ok and action.action_type == expected_type
    detail = f"action={getattr(action, 'id', None)} source={getattr(action, 'module_source', None)} before={before} after={after}"
    R.check(name, ok, detail)
    if not ok:
        R.bug(f"{name} failed shared.Action contract: {detail}")
    return action


def phase_b_actions(tenant, site, departments, users, employees):
    R.set_phase("B - Shared Action Communication")
    today = timezone.localdate()

    capa = CapaTicket.objects.create(
        tenant=tenant,
        title="Supplier defect containment",
        description="E2E CAPA from live test",
        problem="Defect escapes to assembly",
        root_cause="Supplier process drift",
        capa_type=CapaTicket.CapaType.CORRECTIVE,
        status=CapaTicket.CapaStatus.IN_PROGRESS,
        urgency=CapaTicket.Urgency.HIGH,
        pilot=employees["quality_manager"],
        due_date=today + timedelta(days=1),
        created_by=users["tenant_admin"],
    )
    capa_action = ensure_action("CAPA ticket creates shared.Action", capa, "capa", employees["quality_manager"])

    qrqc = QRQC.objects.create(
        tenant=tenant,
        title="QRQC bearing noise",
        problem="Noise at end of line",
        urgency=QRQC.Urgency.HAUTE,
        status=QRQC.Status.EN_COURS,
        created_by=users["tenant_admin"],
    )
    qrqc_action_src = QRQCAction.objects.create(
        tenant=tenant,
        qrqc=qrqc,
        description="Contain suspect lot and inspect stock",
        assigned_to=employees["quality_manager"],
        due_date=today + timedelta(days=3),
        status=QRQCAction.Status.A_FAIRE,
        created_by=users["tenant_admin"],
    )
    ensure_action("Problem Solving QRQC creates shared.Action", qrqc_action_src, "qrqc", employees["quality_manager"])

    session_5s = AuditSession5S.objects.create(
        tenant=tenant,
        zone_id="LINE-A",
        auditor=employees["auditor"],
        created_by=users["tenant_admin"],
    )
    anomaly_5s = Anomaly5S.objects.create(
        tenant=tenant,
        session=session_5s,
        description="Oil spill near press",
        priority=Anomaly5S.Priority.HAUTE,
        assigned_to=employees["production_supervisor"],
        due_date=today + timedelta(days=2),
        created_by=users["tenant_admin"],
    )
    ensure_action("5S anomaly creates shared.Action", anomaly_5s, "5s", employees["production_supervisor"])

    risk_cat = RiskCategory.objects.create(tenant=tenant, name="Safety", created_by=users["tenant_admin"])
    risk = Risk.objects.create(
        tenant=tenant,
        title="Chemical storage spill",
        description="Solvent tank spill risk",
        category=risk_cat,
        likelihood=4,
        impact=4,
        owner=employees["safety_officer"],
        severity=Risk.Severity.HIGH,
        risk_score=16,
        created_by=users["tenant_admin"],
    )
    risk_mitigation = RiskMitigationAction.objects.create(
        tenant=tenant,
        risk=risk,
        description="Install secondary containment",
        owner=employees["maintenance_manager"],
        deadline=today + timedelta(days=30),
        created_by=users["tenant_admin"],
    )
    risk_action = ensure_action("Risk mitigation creates shared.Action", risk_mitigation, "risk", employees["maintenance_manager"])

    machine = Machine.objects.create(
        tenant=tenant,
        code="CNC38",
        nom="CNC Mill E2E",
        emplacement="Main Plant A",
        cadence_theorique=120,
        etat="MARCHE",
        created_by=users["tenant_admin"],
    )
    breakdown = Breakdown.objects.create(
        tenant=tenant,
        machine=machine,
        operateur=employees["operator_1"],
        description="Spindle vibration exceeded limit",
        technicien=employees["maintenance_technician"],
        created_by=users["tenant_admin"],
    )
    tpm_breakdown_action = ensure_action("TPM breakdown creates shared.Action", breakdown, "tpm", employees["maintenance_technician"])
    maintenance_task = MaintenanceTask.objects.create(
        tenant=tenant,
        machine=machine,
        type_tache="CORRECTIVE",
        description="Inspect spindle bearing",
        technicien=employees["maintenance_technician"],
        deadline=today + timedelta(days=7),
        created_by=users["tenant_admin"],
        panne=breakdown,
    )
    ensure_action("TPM maintenance task creates shared.Action", maintenance_task, "tpm", employees["maintenance_technician"])

    skill_cat = SkillCategory.objects.create(tenant=tenant, name="Operations", created_by=users["tenant_admin"])
    cnc_skill = Skill.objects.create(
        tenant=tenant,
        category=skill_cat,
        name="CNC Operation",
        description="Operate CNC equipment",
        created_by=users["tenant_admin"],
    )
    employee_skill = EmployeeSkill.objects.create(
        tenant=tenant,
        employee=employees["operator_1"],
        skill=cnc_skill,
        level=1,
        target_level=4,
        created_by=users["tenant_admin"],
    )
    skills_action = ensure_action("Skills training gap creates shared.Action", employee_skill, "skills")
    R.check("Skills action uses current design unassigned owner", skills_action.assigned_to_id is None)

    board = FlowBoard.objects.create(tenant=tenant, name="Assembly Kanban", board_type="kanban", created_by=users["tenant_admin"])
    column = FlowColumn.objects.create(tenant=tenant, board=board, name="Todo", position=0)
    flow_card = FlowCard.objects.create(
        tenant=tenant,
        board=board,
        column=column,
        title="Stabilize pull loop",
        description="Review WIP supermarket",
        priority=FlowCard.Priority.HIGH,
        assigned_to=employees["ci_engineer"],
        due_date=today + timedelta(days=5),
        created_by=users["tenant_admin"],
    )
    ensure_action("Lean Flow card creates shared.Action", flow_card, "lean_flow", employees["ci_engineer"])

    sfm_session = SFMSession.objects.create(
        tenant=tenant,
        date=today,
        line="Assembly Line A",
        tier_level=SFMSession.TierLevel.TIER_1,
        facilitated_by=employees["plant_manager"],
        status=SFMSession.Status.IN_PROGRESS,
        created_by=users["tenant_admin"],
    )
    sfm_kpi = SFMKPI.objects.create(
        tenant=tenant,
        session=sfm_session,
        category=SFMKPI.Category.SAFETY,
        kpi_name="Recordable incidents",
        target=Decimal("0"),
        actual=Decimal("2"),
        trend_logic=SFMKPI.TrendLogic.LOWER_IS_BETTER,
        color_status=SFMKPI.ColorStatus.GREEN,
        owner=employees["safety_officer"],
        created_by=users["tenant_admin"],
    )
    before = Action.objects.filter(tenant=tenant, module_source="sfm", reference_id=sfm_kpi.id).count()
    SFMService.evaluate_kpi(sfm_kpi)
    sfm_kpi.refresh_from_db()
    SFMService.evaluate_kpi(sfm_kpi)
    after = Action.objects.filter(tenant=tenant, module_source="sfm", reference_id=sfm_kpi.id).count()
    sfm_action = sfm_kpi.linked_action
    R.check(
        "SFM RED KPI creates idempotent shared.Action",
        sfm_action and sfm_action.module_source == "sfm" and sfm_action.assigned_to_id == employees["safety_officer"].id and before == 0 and after == 1,
        f"action={getattr(sfm_action, 'id', None)} count={after}",
    )

    workstation = Workstation.objects.create(
        tenant=tenant,
        name="Critical Press",
        code="PRESS38",
        department=departments["Production"],
        line="Assembly Line A",
        required_skill=cnc_skill,
        required_skill_level=3,
        risk_level=Workstation.RiskLevel.CRITICAL,
        is_critical=True,
        created_by=users["tenant_admin"],
    )
    rotation_plan = RotationPlan.objects.create(
        tenant=tenant,
        name="Morning Rotation E2E",
        date=today,
        department=departments["Production"],
        line="Assembly Line A",
        shift=RotationPlan.Shift.MORNING,
        created_by_employee=employees["production_supervisor"],
        created_by=users["tenant_admin"],
    )
    rotation_slot = RotationSlot.objects.create(
        tenant=tenant,
        plan=rotation_plan,
        start_time=time(6, 0),
        end_time=time(14, 0),
        order=1,
        created_by=users["tenant_admin"],
    )
    RotationRule.objects.create(
        tenant=tenant,
        name="Required skill gate",
        rule_type=RotationRule.RuleType.REQUIRED_SKILL,
        severity=RotationRule.Severity.BLOCKING,
        is_enabled=True,
        created_by=users["tenant_admin"],
    )
    rotation_assignment = RotationAssignment.objects.create(
        tenant=tenant,
        plan=rotation_plan,
        slot=rotation_slot,
        employee=employees["operator_1"],
        workstation=workstation,
        created_by=users["tenant_admin"],
    )
    result1 = RotationService.validate_plan(rotation_plan)
    result2 = RotationService.validate_plan(rotation_plan)
    rotation_violation = RotationViolation.objects.filter(tenant=tenant, plan=rotation_plan, resolved=False).first()
    R.check(
        "Rotation skill gap creates violation and shared.Action",
        rotation_violation
        and rotation_violation.linked_action
        and rotation_violation.linked_action.module_source == "rotation"
        and result1["blocking"] == 1
        and result2["blocking"] == 1,
        f"violation={getattr(rotation_violation, 'id', None)}",
    )

    poka_device = PokaYokeDevice.objects.create(
        tenant=tenant,
        name="Light Curtain E2E",
        code="PY38",
        device_type=PokaYokeDevice.DeviceType.SENSOR,
        status=PokaYokeDevice.Status.ACTIVE,
        machine=machine,
        owner=employees["maintenance_technician"],
        criticality=PokaYokeDevice.Criticality.CRITICAL,
        verification_interval_days=7,
        next_verification_due=today - timedelta(days=1),
        created_by=users["tenant_admin"],
    )
    poka_check = PokaYokeCheck.objects.create(
        tenant=tenant,
        device=poka_device,
        checked_by=employees["operator_2"],
        checked_at=timezone.now(),
        result=PokaYokeCheck.Result.FAILED,
        observation="Sensor misaligned",
        created_by=users["tenant_admin"],
    )
    PokaYokeService.evaluate_check(poka_check)
    poka_check.refresh_from_db()
    PokaYokeService.evaluate_check(poka_check)
    poka_check.refresh_from_db()
    R.check(
        "Poka-Yoke failed check creates idempotent shared.Action",
        poka_check.linked_action
        and poka_check.linked_action.module_source == "poka_yoke"
        and Action.objects.filter(tenant=tenant, module_source="poka_yoke", reference_id=poka_check.id, action_type="failed_check").count() == 1,
        f"action={getattr(poka_check.linked_action, 'id', None)}",
    )
    poka_defect = PokaYokeDefect.objects.create(
        tenant=tenant,
        device=poka_device,
        title="Light curtain bypass risk",
        description="Bypass switch found unlocked",
        detected_by=employees["operator_2"],
        detected_at=timezone.now(),
        severity=PokaYokeDefect.Severity.CRITICAL,
        defect_source=PokaYokeDefect.DefectSource.DEVICE_BYPASSED,
        created_by=users["tenant_admin"],
    )
    PokaYokeService.register_defect(poka_defect)
    poka_defect.refresh_from_db()
    R.check("Poka-Yoke defect creates shared.Action", poka_defect.linked_action and poka_defect.linked_action.module_source == "poka_yoke")

    routine_template = RoutineTemplate.objects.create(
        tenant=tenant,
        code="OKD38",
        title="OK Demarrage E2E",
        routine_type=RoutineTemplate.RoutineType.OK_DEMARRAGE,
        frequency=RoutineTemplate.Frequency.DAILY,
        department=departments["Safety"],
        line="Assembly Line A",
        owner=employees["production_supervisor"],
        status=RoutineTemplate.Status.ACTIVE,
        is_mandatory=True,
        created_by=users["tenant_admin"],
    )
    routine_step = RoutineStep.objects.create(
        tenant=tenant,
        template=routine_template,
        title="Emergency stop check",
        step_type=RoutineStep.StepType.YES_NO,
        order=1,
        is_required=True,
        is_ok_demarrage=True,
        created_by=users["tenant_admin"],
    )
    routine_execution = RoutineExecution.objects.create(
        tenant=tenant,
        template=routine_template,
        scheduled_for=timezone.now(),
        status=RoutineExecution.Status.SCHEDULED,
        created_by=users["tenant_admin"],
    )
    RoutineService.start_execution(routine_execution, employees["operator_1"])
    routine_response = RoutineStepResponse.objects.create(
        tenant=tenant,
        execution=routine_execution,
        step=routine_step,
        result=RoutineStepResponse.Result.FAIL,
        comment="Emergency stop failed to latch",
        responded_by=employees["operator_1"],
        created_by=users["tenant_admin"],
    )
    RoutineService.submit_step_response(routine_response)
    routine_response.refresh_from_db()
    routine_deviation = routine_response.deviations.first()
    before = Action.objects.filter(tenant=tenant, module_source="routines", reference_id=routine_deviation.id).count()
    RoutineService.sync_deviation_action(routine_deviation)
    after = Action.objects.filter(tenant=tenant, module_source="routines", reference_id=routine_deviation.id).count()
    R.check(
        "Routine failed critical step creates deviation and shared.Action",
        routine_deviation and routine_response.linked_action and before == 1 and after == 1,
        f"deviation={getattr(routine_deviation, 'id', None)} action={getattr(routine_response.linked_action, 'id', None)}",
    )

    clause = ISO9001Clause.objects.create(
        tenant=tenant,
        clause_number="8.7",
        title="Control of nonconforming outputs",
        description="E2E clause",
        created_by=users["tenant_admin"],
    )
    iso_nc = NonConformity.objects.create(
        tenant=tenant,
        clause=clause,
        description="Uncontrolled rework instruction",
        severity=NonConformity.Severity.MAJOR,
        detected_by=employees["auditor"],
        created_by=users["tenant_admin"],
    )
    iso_ca = CorrectiveAction.objects.create(
        tenant=tenant,
        non_conformity=iso_nc,
        description="Update and train rework process",
        owner=employees["quality_manager"],
        deadline=today + timedelta(days=14),
        created_by=users["tenant_admin"],
    )
    ensure_action("ISO9001 corrective action creates shared.Action", iso_ca, "iso9001", employees["quality_manager"])

    production_line = ProductionLine.objects.create(
        tenant=tenant,
        name="Assembly Line A",
        site=site,
        department=departments["Production"],
        status=ProductionLine.Status.RUNNING,
        created_by=users["tenant_admin"],
    )
    andon_call = AndonCall.objects.create(
        tenant=tenant,
        line=production_line,
        operator=employees["operator_1"],
        call_type=AndonCall.CallType.SAFETY,
        severity=AndonCall.Severity.HIGH,
        description="Guard door alarm active",
        created_by=users["tenant_admin"],
    )
    andon_action = ensure_action("Andon high severity creates shared.Action", andon_call, "andon")

    vsm_map = VSMMap.objects.create(
        tenant=tenant,
        name="Assembly Value Stream E2E",
        owner=employees["ci_engineer"],
        department=departments["Continuous Improvement"],
        created_by=users["tenant_admin"],
    )
    VSMElement.objects.create(
        tenant=tenant,
        vsm_map=vsm_map,
        element_type=VSMElement.ElementType.PROCESS,
        position_x=100,
        position_y=100,
        properties={"name": "Welding", "cycleTime": 30, "changeoverTime": 120, "availability": 95, "uptime": 98, "defectRate": 2},
        created_by=users["tenant_admin"],
    )
    VSMService.recalculate_metrics(vsm_map)
    snapshot = VSMService.create_snapshot(vsm_map, users["tenant_admin"], label="E2E snapshot")
    R.check("VSM metrics and snapshot created", snapshot and snapshot.version_num == 1)

    smed_session = SMEDSession.objects.create(
        tenant=tenant,
        machine=machine,
        product_before="Part A",
        product_after="Part B",
        observed_by=employees["ci_engineer"],
        date_observed=today,
        created_by=users["tenant_admin"],
    )
    SMEDStep.objects.create(
        tenant=tenant,
        session=smed_session,
        description="Remove old fixture",
        step_type=SMEDStep.StepType.INTERNAL,
        duration_before_sec=300,
        duration_after_sec=180,
        order=1,
        operator=employees["maintenance_technician"],
        created_by=users["tenant_admin"],
    )
    SMEDService.recalculate_session_metrics(smed_session)
    smed_session.refresh_from_db()
    R.check("SMED KPI recalculation persisted", smed_session.total_time_before == 300 and smed_session.total_time_after == 180)

    action_sources = sorted(Action.objects.filter(tenant=tenant, is_active=True, is_deleted=False).values_list("module_source", flat=True).distinct())
    R.check(
        "Global shared.Action list contains multiple modules",
        len(action_sources) >= 10,
        f"sources={action_sources}",
    )

    R.created.update({
        "capa": capa,
        "capa_action": capa_action,
        "risk": risk,
        "risk_mitigation": risk_mitigation,
        "risk_action": risk_action,
        "machine": machine,
        "breakdown": breakdown,
        "tpm_breakdown_action": tpm_breakdown_action,
        "sfm_session": sfm_session,
        "sfm_kpi": sfm_kpi,
        "sfm_action": sfm_action,
        "rotation_plan": rotation_plan,
        "rotation_violation": rotation_violation,
        "poka_device": poka_device,
        "poka_check": poka_check,
        "poka_defect": poka_defect,
        "routine_template": routine_template,
        "routine_execution": routine_execution,
        "routine_deviation": routine_deviation,
        "iso_clause": clause,
        "iso_nc": iso_nc,
        "production_line": production_line,
        "andon_call": andon_call,
        "andon_action": andon_action,
        "vsm_map": vsm_map,
        "smed_session": smed_session,
        "skill": cnc_skill,
        "skill_category": skill_cat,
        "employee_skill": employee_skill,
    })


def phase_c_notifications_and_tasks(tenant, departments, users, employees):
    R.set_phase("C - Shared Notification Communication")
    today = timezone.localdate()

    sfm_kpi = R.created["sfm_kpi"]
    sfm_count_before = Notification.objects.filter(tenant=tenant, notification_type="sfm_escalation").count()
    escalation = SFMService.escalate_kpi(
        sfm_kpi,
        SFMSession.TierLevel.TIER_2,
        employees["safety_officer"],
        "Safety KPI requires tier 2 review",
    )
    sfm_count_after = Notification.objects.filter(tenant=tenant, notification_type="sfm_escalation", related_object_id=escalation.id).count()
    R.check("SFM escalation creates shared.Notification", sfm_count_after >= 1 and sfm_count_after > sfm_count_before)
    R.created["sfm_escalation"] = escalation

    rotation_violation = R.created["rotation_violation"]
    R.check(
        "Rotation violation creates shared.Notification",
        Notification.objects.filter(tenant=tenant, notification_type="rotation_blocking_violation", related_object_id=rotation_violation.id).exists(),
    )

    poka_check = R.created["poka_check"]
    failed_check_notifications = Notification.objects.filter(
        tenant=tenant,
        notification_type="poka_yoke_check_failed",
        related_object_id=poka_check.id,
    ).count()
    R.check(
        "Poka-Yoke failed check notification exists",
        failed_check_notifications >= 1,
        f"count={failed_check_notifications}",
    )
    if failed_check_notifications > 1:
        R.bug("Duplicate Poka-Yoke failed-check notifications are created by repeated service execution.")

    routine_deviation = R.created["routine_deviation"]
    routine_notifications = Notification.objects.filter(
        tenant=tenant,
        notification_type="routine_critical_deviation",
        related_object_id=routine_deviation.id,
    ).count()
    R.check("Routine failed critical step notification exists", routine_notifications >= 1, f"count={routine_notifications}")
    if routine_notifications > 1:
        R.bug("Duplicate routine critical-deviation notifications are created by repeated sync execution.")

    missed_execution = RoutineExecution.objects.create(
        tenant=tenant,
        template=R.created["routine_template"],
        scheduled_for=timezone.now() - timedelta(days=1),
        status=RoutineExecution.Status.SCHEDULED,
        executed_by=employees["operator_2"],
        created_by=users["tenant_admin"],
    )
    missed_result_1 = RoutineService.mark_missed_executions(tenant=tenant)
    missed_result_2 = RoutineService.mark_missed_executions(tenant=tenant)
    missed_notifs = Notification.objects.filter(
        tenant=tenant,
        notification_type="routine_missed",
        related_object_id=missed_execution.id,
    ).count()
    R.check(
        "Routine missed execution task creates bounded Notification",
        missed_notifs == 1 and len(missed_result_1) >= 1 and len(missed_result_2) == 0,
        f"notifications={missed_notifs}",
    )
    R.created["missed_execution"] = missed_execution

    cert = Certification.objects.create(
        tenant=tenant,
        employee=employees["operator_1"],
        name="Forklift permit",
        issued_date=today - timedelta(days=300),
        expiry_date=today + timedelta(days=10),
        created_by=users["tenant_admin"],
    )
    before = Notification.objects.filter(tenant=tenant, notification_type="certification_expiry", related_object_id=cert.id).count()
    SkillsService.check_expiring_certifications()
    SkillsService.check_expiring_certifications()
    after = Notification.objects.filter(tenant=tenant, notification_type="certification_expiry", related_object_id=cert.id).count()
    R.check("Skills certification expiry creates Notification", after >= 1, f"before={before} after={after}")
    if after > 1:
        R.bug("Skills certification expiry task is not idempotent for same-day repeated execution.")

    due_capa = R.created["capa"]
    CapaService_result_1 = send_due_reminders()
    CapaService_result_2 = send_due_reminders()
    capa_notifs = Notification.objects.filter(
        tenant=tenant,
        notification_type="capa_due_reminder",
        related_object_id=due_capa.id,
    ).count()
    R.check(
        "CAPA due reminder creates idempotent Notification",
        capa_notifs == 1,
        f"notifications={capa_notifs} summary1={CapaService_result_1} summary2={CapaService_result_2}",
    )

    iso_doc = ISODocument.objects.create(
        tenant=tenant,
        title="Control Plan",
        clause=R.created["iso_clause"],
        file_path="iso_documents/e2e-control-plan.pdf",
        version="1.0",
        valid_from=today - timedelta(days=60),
        valid_until=today + timedelta(days=30),
        uploaded_by=employees["quality_manager"],
        created_by=users["tenant_admin"],
    )
    check_iso_document_expiry_task()
    check_iso_document_expiry_task()
    iso_doc_notifs = Notification.objects.filter(
        tenant=tenant,
        notification_type="iso_doc_expiry",
        related_object_id=iso_doc.id,
    ).count()
    R.check("ISO document expiry task creates Notification", iso_doc_notifs >= 1, f"count={iso_doc_notifs}")
    if iso_doc_notifs > 1:
        R.bug("ISO document expiry task is not idempotent for same-day repeated execution.")

    no_account_device = PokaYokeDevice.objects.create(
        tenant=tenant,
        name="No Account Owner Device",
        code="PYNOACC",
        status=PokaYokeDevice.Status.ACTIVE,
        owner=employees["no_account_operator"],
        criticality=PokaYokeDevice.Criticality.LOW,
        next_verification_due=today - timedelta(days=2),
        created_by=users["tenant_admin"],
    )
    try:
        PokaYokeService.check_overdue_verifications(tenant=tenant)
        R.check("Employee without user_account does not crash notification services", True)
    except Exception as exc:
        R.fail("Employee without user_account does not crash notification services", exc)

    # Create Gemba data and weekly summary.
    zone = GembaZone.objects.create(tenant=tenant, name="Assembly Zone", code="GZ38", created_by=users["tenant_admin"])
    team = GembaTeam.objects.create(tenant=tenant, name="Team A", zone=zone, leader=employees["production_supervisor"], created_by=users["tenant_admin"])
    category = GembaCategory.objects.create(tenant=tenant, name="Safety", type=GembaCategory.CategoryType.SECURITY, created_by=users["tenant_admin"])
    checkpoint = Checkpoint.objects.create(tenant=tenant, name="Guarding available", category=category, created_by=users["tenant_admin"])
    tour = Tour.objects.create(
        tenant=tenant,
        title="Weekly Gemba E2E",
        date=today,
        zone=zone,
        team=team,
        objective=Tour.Objective.SECURITY,
        status=Tour.Status.COMPLETED,
        created_by=users["tenant_admin"],
    )
    gemba_anomaly = Anomaly.objects.create(
        tenant=tenant,
        title="Guarding missing label",
        description="Guarding label missing",
        category=category,
        severity=Anomaly.Severity.MAJOR,
        assigned_to=employees["production_supervisor"],
        due_date=today + timedelta(days=3),
        created_by=users["tenant_admin"],
    )
    gemba_summary_1 = send_weekly_summary()
    gemba_summary_2 = send_weekly_summary()
    gemba_notifs = Notification.objects.filter(tenant=tenant, notification_type="gemba_weekly_summary").count()
    R.check(
        "Gemba weekly summary creates email-safe idempotent Notifications",
        gemba_notifs >= 1 and gemba_summary_2.get("duplicates_skipped", 0) >= 1,
        f"notifications={gemba_notifs}",
    )
    R.created.update({"gemba_zone": zone, "gemba_team": team, "gemba_category": category, "gemba_checkpoint": checkpoint, "gemba_tour": tour, "gemba_anomaly": gemba_anomaly})

    notif_tenant_ok = Notification.objects.filter(tenant=tenant).exclude(recipient__tenant=tenant).count() == 0
    R.check("All Acme notifications target Acme users", notif_tenant_ok)


def phase_d_signals(tenant, users, employees):
    R.set_phase("D - Signal Communication")
    before = CapaTicket.objects.filter(tenant=tenant).count()
    risk = R.created["risk"]
    RiskService.assess_risk(risk, 5, 5, employees["safety_officer"], notes="Phase 3.8 critical escalation")
    after = CapaTicket.objects.filter(tenant=tenant).count()
    R.check("Risk escalation signal creates CAPA", after > before, f"before={before} after={after}")

    session = ISO9001EvaluationSession.objects.create(
        tenant=tenant,
        title="ISO bridge session E2E",
        evaluator=employees["auditor"],
        status=ISO9001EvaluationSession.Status.IN_PROGRESS,
        created_by=users["tenant_admin"],
    )
    question = ISO9001Question.objects.create(
        tenant=tenant,
        clause=R.created["iso_clause"],
        question_text="Are nonconforming outputs controlled?",
        created_by=users["tenant_admin"],
    )
    response = ISO9001Response.objects.create(
        tenant=tenant,
        session=session,
        question=question,
        response_status=ISO9001Response.ResponseStatus.NON_COMPLIANT,
        evidence_notes="No quarantine record found",
        created_by=users["tenant_admin"],
    )
    nc = ISO9001Service.process_response_nc_bridge(response)
    R.check("ISO9001 non-compliant response creates NonConformity", nc is not None and nc.tenant_id == tenant.id)
    before = CapaTicket.objects.filter(tenant=tenant).count()
    major_nc = NonConformity.objects.create(
        tenant=tenant,
        clause=R.created["iso_clause"],
        description="Major ISO escalation E2E",
        severity=NonConformity.Severity.MAJOR,
        detected_by=employees["auditor"],
        created_by=users["tenant_admin"],
    )
    ISO9001Service.trigger_capa_if_needed(major_nc)
    after = CapaTicket.objects.filter(tenant=tenant).count()
    R.check("ISO9001 major NC signal creates CAPA", after > before, f"before={before} after={after}")
    if nc and nc.severity == NonConformity.Severity.MINOR:
        R.notes.append("ISO9001 response bridge creates minor NC by design; CAPA signal fires only when NC is major or critical.")

    signal_tenant = Tenant.objects.create(name="Signal Tenant E2E", slug="signal-e2e-test")
    R.check("Tenant post_save creates TenantLicense", hasattr(signal_tenant, "license"))
    signal_tenant.delete()


def phase_e_messaging(tenant, users, employees):
    R.set_phase("E - Messaging GenericForeignKey")
    sources = [
        ("CAPA ticket", R.created["capa"]),
        ("Risk", R.created["risk"]),
        ("SFM escalation", R.created["sfm_escalation"]),
        ("Rotation violation", R.created["rotation_violation"]),
        ("Poka-Yoke defect", R.created["poka_defect"]),
        ("Routine deviation", R.created["routine_deviation"]),
        ("TPM breakdown", R.created["breakdown"]),
        ("VSM map", R.created["vsm_map"]),
        ("Gemba anomaly", R.created["gemba_anomaly"]),
    ]
    conversations = []
    for label, obj in sources:
        ct = ContentType.objects.get_for_model(obj.__class__)
        conv = Conversation.objects.create(
            tenant=tenant,
            title=f"E2E thread - {label}",
            content_type=ct,
            object_id=obj.id,
            created_by=users["tenant_admin"],
        )
        participant = ConversationParticipant.objects.create(
            tenant=tenant,
            conversation=conv,
            user=employees["quality_manager"],
            created_by=users["tenant_admin"],
        )
        msg = Message.objects.create(
            tenant=tenant,
            conversation=conv,
            sender=employees["quality_manager"],
            content=f"Discussing {label}",
            created_by=users["tenant_admin"],
        )
        sys_msg = Message.objects.create(
            tenant=tenant,
            conversation=conv,
            sender=None,
            content=f"System note for {label}",
            is_system_generated=True,
            created_by=users["tenant_admin"],
        )
        ok = (
            conv.content_type_id == ct.id
            and conv.object_id == obj.id
            and conv.linked_item == obj
            and conv.tenant_id == obj.tenant_id
            and msg.sender_id == employees["quality_manager"].id
            and participant.user_id == employees["quality_manager"].id
            and sys_msg.is_system_generated
        )
        R.check(f"Conversation attaches to {label}", ok)
        conversations.append(conv)
    R.created["conversation"] = conversations[0]


def setup_beta(tenant, site, departments, users, employees):
    tenant_b = Tenant.objects.create(name="Beta Manufacturing E2E", slug="beta-e2e")
    starter_key = generate_license_key("starter", duration_days=30)
    activate_license_key(tenant_b, starter_key.key)
    site_b = Site.objects.create(tenant=tenant_b, name="Beta Main Plant", is_main=True)
    dept_b = Department.objects.create(tenant=tenant_b, site=site_b, name="Production")
    # Same email as Acme operator proves composite tenant/email scoping.
    user_b = CustomUser.objects.create_user(
        email=users["operator_1"].email,
        password="Phase38!",
        tenant=tenant_b,
        role="operator",
        first_name="Beta",
        last_name="Operator",
    )
    employee_b = Employee.objects.create(
        tenant=tenant_b,
        user_account=user_b,
        first_name="Beta",
        last_name="Operator",
        email=user_b.email,
        department=dept_b,
        site=site_b,
    )
    skill_cat_b = SkillCategory.objects.create(tenant=tenant_b, name="Beta Skills", created_by=user_b)
    skill_b = Skill.objects.create(tenant=tenant_b, category=skill_cat_b, name="Beta Skill", created_by=user_b)
    machine_b = Machine.objects.create(
        tenant=tenant_b,
        code="BETA38",
        nom="Beta Machine",
        emplacement="Beta",
        cadence_theorique=1,
        created_by=user_b,
    )
    line_b = ProductionLine.objects.create(tenant=tenant_b, name="Beta Line", site=site_b, department=dept_b, created_by=user_b)
    R.created.update({
        "tenant_b": tenant_b,
        "site_b": site_b,
        "dept_b": dept_b,
        "user_b": user_b,
        "employee_b": employee_b,
        "skill_b": skill_b,
        "machine_b": machine_b,
        "line_b": line_b,
        "starter_key": starter_key,
    })
    return tenant_b, site_b, dept_b, user_b, employee_b, skill_b, machine_b, line_b


def phase_f_factory_day(tenant, users, employees):
    R.set_phase("F - Factory Day E2E Scenario")
    required_sources = ["routines", "tpm", "sfm", "poka_yoke", "iso9001", "risk", "rotation"]
    current_sources = set(Action.objects.filter(tenant=tenant, is_active=True, is_deleted=False).values_list("module_source", flat=True))
    R.check("Morning startup generated routine action", "routines" in current_sources)
    R.check("During production generated TPM action", "tpm" in current_sources)
    R.check("SFM RED KPI generated action", "sfm" in current_sources)
    R.check("Poka-Yoke failure generated action", "poka_yoke" in current_sources)
    R.check("Quality event generated ISO/CAPA action", "iso9001" in current_sources and "capa" in current_sources)
    R.check("Risk review generated mitigation action", "risk" in current_sources)
    R.check("Rotation skill gap generated action", "rotation" in current_sources)
    R.check("Lean improvement data persisted", VSMMap.objects.filter(tenant=tenant).exists() and SMEDSession.objects.filter(tenant=tenant).exists())
    R.check(
        "Global action list contains factory-day modules",
        all(source in current_sources for source in required_sources),
        f"sources={sorted(current_sources)}",
    )
    notif_types = set(Notification.objects.filter(tenant=tenant).values_list("notification_type", flat=True))
    R.check("Factory day notifications created for correct users", len(notif_types) >= 6 and Notification.objects.filter(tenant=tenant).exclude(recipient__tenant=tenant).count() == 0, sorted(notif_types))


def phase_g_dashboards(tenant):
    R.set_phase("G - Dashboard Consistency")
    try:
        sfm = SFMService.dashboard_metrics(tenant)
        R.check("SFM dashboard counts RED KPI", sfm["open_red_kpis"] >= 1, sfm)
    except Exception as exc:
        R.fail("SFM dashboard", exc)
    try:
        rotation = RotationService.calculate_rotation_analytics(tenant)
        R.check("Rotation dashboard counts blocking violation", rotation["open_blocking_violations"] >= 1, rotation)
    except Exception as exc:
        R.fail("Rotation dashboard", exc)
    try:
        poka = PokaYokeService.dashboard_metrics(tenant)
        R.check("Poka-Yoke dashboard counts failed check", poka["failed_checks"] >= 1, poka)
    except Exception as exc:
        R.fail("Poka-Yoke dashboard", exc)
    try:
        routines = RoutineService.dashboard_metrics(tenant)
        R.check("Routines dashboard counts deviation/failure", routines["open_deviations"] >= 1 or routines["missed_routines"] >= 1, routines)
    except Exception as exc:
        R.fail("Routines dashboard", exc)
    try:
        smed = SMEDService.dashboard_metrics(tenant)
        R.check("SMED dashboard mathematically consistent", smed["total_time_saved"] >= 120, smed)
    except Exception as exc:
        R.fail("SMED dashboard", exc)
    try:
        vsm = VSMMap.objects.get(id=R.created["vsm_map"].id)
        R.check("VSM metrics persisted", vsm.process_count >= 1 and Decimal(vsm.total_lead_time) >= Decimal("30"), vsm.metrics_json)
    except Exception as exc:
        R.fail("VSM metrics", exc)
    try:
        skills_coverage = SkillsService.calculate_machine_coverage(tenant, R.created["skill"].id, required_level=2)
        R.check("Skills coverage excludes underqualified employee", skills_coverage == 0, f"coverage={skills_coverage}")
    except Exception as exc:
        R.fail("Skills dashboard/coverage", exc)
    try:
        andon = AndonService.calculate_response_time(tenant)
        R.check("Visual management analytics returns tenant data", isinstance(andon, list) and len(andon) >= 1, andon)
    except Exception as exc:
        R.fail("Visual management analytics", exc)
    try:
        iso = ISO9001Service.calculate_compliance(tenant)
        R.check("ISO9001 compliance dashboard does not crash", isinstance(iso, dict), iso)
    except Exception as exc:
        R.fail("ISO9001 dashboard", exc)
    R.check("Risk dashboard count reflects created risk", Risk.objects.filter(tenant=tenant, is_active=True, is_deleted=False).count() >= 1)
    R.check("TPM dashboard count reflects created machine", Machine.objects.filter(tenant=tenant, is_active=True, is_deleted=False).count() >= 1)
    R.check("5S dashboard count reflects created anomaly", Anomaly5S.objects.filter(tenant=tenant, is_active=True, is_deleted=False).count() >= 1)
    R.check("Shared action count reflects persisted records", Action.objects.filter(tenant=tenant, is_active=True, is_deleted=False).count() >= 10)
    R.check("Shared notification count reflects persisted records", Notification.objects.filter(tenant=tenant, is_active=True, is_deleted=False).count() >= 6)


def phase_h_locked_modules(tenant, users):
    R.set_phase("H - Locked Module Behavior")
    client = APIClient()
    client.force_authenticate(user=users["tenant_admin"])
    endpoints = {
        "sfm": ("is_sfm_active", "/api/v1/sfm/dashboard/"),
        "rotation": ("is_rotation_active", "/api/v1/rotation/plans/"),
        "poka_yoke": ("is_poka_yoke_active", "/api/v1/poka-yoke/dashboard/"),
        "routines": ("is_routines_active", "/api/v1/routines/dashboard/"),
        "vsm": ("is_vsm_active", "/api/v1/vsm/maps/"),
        "visual_mgmt": ("is_visual_mgmt_active", "/api/v1/visual-management/lines/"),
        "messaging": ("is_messaging_active", "/api/v1/messaging/conversations/"),
    }
    action_count = Action.objects.filter(tenant=tenant).count()
    for module, (flag, endpoint) in endpoints.items():
        license_obj = tenant.license
        original = getattr(license_obj, flag)
        setattr(license_obj, flag, False)
        license_obj.save(update_fields=[flag, "updated_at"])
        response_locked = client.get(endpoint, HTTP_HOST=tenant_host(tenant.slug))
        R.check(f"{module} API returns 403 when locked", response_locked.status_code == 403, f"status={response_locked.status_code}")
        R.check(f"{module} locked state preserves global actions", Action.objects.filter(tenant=tenant).count() == action_count)
        setattr(license_obj, flag, original)
        license_obj.save(update_fields=[flag, "updated_at"])
        response_open = client.get(endpoint, HTTP_HOST=tenant_host(tenant.slug))
        R.check(f"{module} API works after re-enable", response_open.status_code in [200, 404], f"status={response_open.status_code}")

    # Consumer-level tenant checks used before accept.
    line = R.created["production_line"]
    conv = R.created["conversation"]
    try:
        import asyncio
        line_ok = asyncio.run(get_production_line(users["tenant_admin"], line.id))
        conv_ok = asyncio.run(get_conversation_participant(users["quality_manager"], conv.id))
        R.check("WebSocket pre-accept validators accept valid tenant participant", line_ok is not None and conv_ok is not None)
    except Exception as exc:
        R.fail("WebSocket pre-accept validators", exc)


def phase_i_cross_tenant_attacks(tenant, site, departments, users, employees):
    R.set_phase("I - Cross-Tenant Attacks")
    tenant_b, site_b, dept_b, user_b, employee_b, skill_b, machine_b, line_b = setup_beta(
        tenant, site, departments, users, employees
    )
    R.check("Same email allowed across different tenants", user_b.email == users["operator_1"].email and user_b.tenant_id != users["operator_1"].tenant_id)

    request_a = req_for(tenant, users["tenant_admin"])

    data = {
        "plan": str(R.created["rotation_plan"].id),
        "slot": str(R.created["rotation_plan"].slots.first().id),
        "employee": str(employee_b.id),
        "workstation": str(R.created["rotation_violation"].assignment.workstation.id),
        "status": RotationAssignment.Status.PLANNED,
    }
    ser = RotationAssignmentSerializer(data=data, context={"request": request_a})
    R.check("Tenant A cannot assign Tenant B Employee via serializer", not ser.is_valid(), ser.errors if not ser.is_valid() else "")

    data = {
        "name": "Attack Workstation",
        "department": str(departments["Production"].id),
        "line": "A",
        "required_skill": str(skill_b.id),
        "required_skill_level": 2,
    }
    ser = WorkstationSerializer(data=data, context={"request": request_a})
    R.check("Tenant A cannot link Tenant B Skill via serializer", not ser.is_valid(), ser.errors if not ser.is_valid() else "")

    data = {
        "name": "Attack Device",
        "code": "ATKPY",
        "status": PokaYokeDevice.Status.ACTIVE,
        "machine": str(machine_b.id),
        "owner": str(employees["maintenance_technician"].id),
    }
    ser = PokaYokeDeviceSerializer(data=data, context={"request": request_a})
    R.check("Tenant A cannot link Tenant B Machine into Poka-Yoke device", not ser.is_valid(), ser.errors if not ser.is_valid() else "")

    data = {
        "session": str(R.created["sfm_session"].id),
        "category": SFMKPI.Category.SAFETY,
        "kpi_name": "Attack KPI",
        "target": "0",
        "actual": "1",
        "trend_logic": SFMKPI.TrendLogic.LOWER_IS_BETTER,
        "owner": str(employee_b.id),
    }
    ser = SFMKPISerializer(data=data, context={"request": request_a})
    R.check("Tenant A cannot create SFM KPI with Tenant B owner", not ser.is_valid(), ser.errors if not ser.is_valid() else "")

    attack_execution = RoutineExecution.objects.create(
        tenant=tenant,
        template=R.created["routine_template"],
        scheduled_for=timezone.now() + timedelta(hours=1),
        status=RoutineExecution.Status.SCHEDULED,
        created_by=users["tenant_admin"],
    )
    data = {
        "execution": str(attack_execution.id),
        "step": str(R.created["routine_execution"].template.steps.first().id),
        "result": RoutineStepResponse.Result.PASS,
        "responded_by": str(employee_b.id),
    }
    ser = RoutineStepResponseSerializer(data=data, context={"request": request_a})
    R.check("Tenant A cannot create routine response with Tenant B responder", not ser.is_valid(), ser.errors if not ser.is_valid() else "")

    ct = ContentType.objects.get_for_model(line_b)
    data = {"title": "Attack linked conversation", "content_type": ct.id, "object_id": str(line_b.id)}
    ser = ConversationSerializer(data=data, context={"request": request_a})
    valid = ser.is_valid()
    R.check("Tenant A cannot create conversation for Tenant B object", not valid, ser.errors if not valid else "serializer accepted")
    if valid:
        R.bug("Messaging ConversationSerializer allows cross-tenant GenericForeignKey object linking.")

    client_a = APIClient()
    client_a.force_authenticate(user=users["tenant_admin"])
    dash_a = client_a.get("/api/v1/sfm/dashboard/", HTTP_HOST=tenant_host(tenant.slug))
    R.check("Tenant A dashboard request succeeds under Acme host", dash_a.status_code == 200, f"status={dash_a.status_code}")
    R.check("Tenant A dashboards do not include Tenant B action counts", Action.objects.filter(tenant=tenant_b).count() == 0)

    try:
        activate_license_key(tenant_b, R.license_key)
        R.check("Tenant B cannot reuse Tenant A license key", False, "activation succeeded")
    except ValueError:
        R.check("Tenant B cannot reuse Tenant A license key", True)

    try:
        import asyncio
        conv_a = R.created["conversation"]
        beta_conv = asyncio.run(get_conversation_participant(user_b, conv_a.id))
        beta_line = asyncio.run(get_production_line(user_b, R.created["production_line"].id))
        R.check("Tenant B cannot subscribe to Tenant A messaging/Andon validators", beta_conv is None and beta_line is None)
    except Exception as exc:
        R.fail("Tenant B WebSocket validator attack", exc)


def phase_j_soft_delete(tenant):
    R.set_phase("J - Soft Delete Communication")
    cases = [
        ("SFM KPI", R.created["sfm_kpi"], "sfm"),
        ("Rotation violation", R.created["rotation_violation"], "rotation"),
        ("Poka-Yoke defect", R.created["poka_defect"], "poka_yoke"),
        ("Routine deviation", R.created["routine_deviation"], "routines"),
        ("TPM breakdown", R.created["breakdown"], "tpm"),
        ("CAPA ticket", R.created["capa"], "capa"),
        ("Risk mitigation", R.created["risk_mitigation"], "risk"),
    ]
    for label, obj, source in cases:
        action_before = Action.objects.filter(tenant=tenant, module_source=source).count()
        notif_before = Notification.objects.filter(tenant=tenant).count()
        obj.soft_delete()
        obj.refresh_from_db()
        hidden = not obj.__class__.objects.filter(id=obj.id).exists()
        action_survives = Action.objects.filter(tenant=tenant, module_source=source).count() == action_before
        notif_survives = Notification.objects.filter(tenant=tenant).count() >= notif_before
        R.check(
            f"{label} soft-delete hides source and preserves history",
            obj.is_deleted and hidden and action_survives and notif_survives,
            f"actions={action_before}",
        )
    try:
        sfm = SFMService.dashboard_metrics(tenant)
        poka = PokaYokeService.dashboard_metrics(tenant)
        routines = RoutineService.dashboard_metrics(tenant)
        R.check("Dashboards exclude soft-deleted linked sources", sfm["open_red_kpis"] == 0 and poka["open_defects"] == 0 and routines["open_deviations"] == 0, f"sfm={sfm['open_red_kpis']} poka={poka['open_defects']} routines={routines['open_deviations']}")
    except Exception as exc:
        R.fail("Soft-delete dashboard exclusion", exc)


def phase_k_celery(tenant, users, employees):
    R.set_phase("K - Celery Business Communication Tasks")
    today = timezone.localdate()
    expired = Tenant.objects.create(
        name="Expired Tenant E2E",
        slug="expired-e2e",
        plan="enterprise",
        status="active",
        subscription_ends_at=today - timedelta(days=1),
    )
    expired.license.activate_plan("enterprise")

    task_results = {}
    try:
        task_results["billing"] = check_expired_subscriptions()
        expired.refresh_from_db()
        R.check("billing.tasks.check_expired_subscriptions executes safely", expired.status == "expired", task_results["billing"])
    except Exception as exc:
        R.fail("billing.tasks.check_expired_subscriptions", exc)

    try:
        check_expiring_certifications_task()
        R.check("skills.tasks.check_expiring_certifications_task executes", True)
    except Exception as exc:
        R.fail("skills.tasks.check_expiring_certifications_task", exc)

    try:
        check_iso_document_expiry_task()
        R.check("iso9001.tasks.check_iso_document_expiry_task executes", True)
    except Exception as exc:
        R.fail("iso9001.tasks.check_iso_document_expiry_task", exc)

    try:
        andon_call = R.created["andon_call"]
        before_alerts = andon_call.alerts.count()
        check_andon_sla_breach_task(str(andon_call.id))
        check_andon_sla_breach_task(str(andon_call.id))
        after_alerts = andon_call.alerts.count()
        R.check("visual_management.tasks.check_andon_sla_breach_task executes", after_alerts >= before_alerts)
        if after_alerts > before_alerts + 1:
            R.bug("Andon SLA breach task creates duplicate alerts on repeated execution.")
    except Exception as exc:
        R.fail("visual_management.tasks.check_andon_sla_breach_task", exc)

    try:
        res = check_missed_routine_executions_task(str(tenant.id))
        R.check("routines.tasks.check_missed_routine_executions_task executes", isinstance(res, dict), res)
    except Exception as exc:
        R.fail("routines.tasks.check_missed_routine_executions_task", exc)

    try:
        res = check_overdue_poka_yoke_verifications_task(str(tenant.id))
        R.check("poka_yoke.tasks.check_overdue_poka_yoke_verifications_task executes", isinstance(res, dict), res)
    except Exception as exc:
        R.fail("poka_yoke.tasks.check_overdue_poka_yoke_verifications_task", exc)

    try:
        res = send_due_reminders()
        R.check("capa.tasks.send_due_reminders executes", isinstance(res, dict), res)
    except Exception as exc:
        R.fail("capa.tasks.send_due_reminders", exc)

    try:
        res = send_weekly_summary()
        R.check("gemba.tasks.send_weekly_summary executes", isinstance(res, dict), res)
    except Exception as exc:
        R.fail("gemba.tasks.send_weekly_summary", exc)


def phase_l_api_model_contracts(tenant, users):
    R.set_phase("L - API / Model Contract")
    client = APIClient()
    client.force_authenticate(user=users["tenant_admin"])
    endpoints = {
        "gemba": "/api/v1/gemba/zones/",
        "audits": "/api/v1/audits/types/",
        "capa": "/api/v1/capa/actions/",
        "problem_solving": "/api/v1/problem-solving/qrqc/tickets/",
        "five_s": "/api/v1/5s/anomalies/",
        "risk": "/api/v1/risk/risks/",
        "tpm": "/api/v1/tpm/machines/",
        "skills": "/api/v1/skills/categories/",
        "visual_management": "/api/v1/visual-management/lines/",
        "iso9001": "/api/v1/iso9001/clauses/",
        "lean_flow": "/api/v1/lean-flow/boards/",
        "vsm": "/api/v1/vsm/maps/",
        "smed": "/api/v1/smed/sessions/",
        "sfm": "/api/v1/sfm/sessions/",
        "rotation_table": "/api/v1/rotation/plans/",
        "poka_yoke": "/api/v1/poka-yoke/devices/",
        "routines": "/api/v1/routines/templates/",
        "messaging": "/api/v1/messaging/conversations/",
    }
    for module, endpoint in endpoints.items():
        response = client.get(endpoint, HTTP_HOST=tenant_host(tenant.slug))
        R.check(f"{module} list endpoint tenant/auth contract", response.status_code == 200, f"status={response.status_code}")

    request_a = req_for(tenant, users["tenant_admin"])
    bad_kpi = SFMKPISerializer(data={
        "session": str(R.created["sfm_session"].id),
        "category": "not-a-category",
        "kpi_name": "",
        "target": "-1",
        "actual": "0",
        "trend_logic": SFMKPI.TrendLogic.LOWER_IS_BETTER,
    }, context={"request": request_a})
    R.check("Invalid choices / required fields rejected by representative serializer", not bad_kpi.is_valid(), bad_kpi.errors if not bad_kpi.is_valid() else "")

    try:
        Action(tenant=tenant, title="", priority="not-valid", status="open").full_clean()
        R.check("Invalid model choices rejected by model full_clean", False, "full_clean accepted invalid data")
    except Exception:
        R.check("Invalid model choices rejected by model full_clean", True)


def phase_m_final_commands():
    R.set_phase("M - Final Verification Commands")
    commands = [
        ("makemigrations --check --dry-run", ["makemigrations", "--check", "--dry-run"]),
        ("migrate", ["migrate"]),
        ("check", ["check"]),
    ]
    for label, args in commands:
        try:
            call_command(*args, verbosity=0)
            R.check(f"manage.py {label}", True)
        except SystemExit as exc:
            R.check(f"manage.py {label}", False, exc)
        except Exception as exc:
            R.fail(f"manage.py {label}", exc)

    smoke = {
        "license activation service": Tenant.objects.filter(slug="acme-e2e", status="active", plan="enterprise").exists(),
        "ModuleIsActive locked tests": any("API returns 403 when locked" in row[1] and row[2] == "PASS" for row in R.rows),
        "shared.Action creation": Action.objects.filter(tenant=R.created["tenant"]).exists(),
        "shared.Notification creation": Notification.objects.filter(tenant=R.created["tenant"]).exists(),
        "signal receivers": any("signal creates CAPA" in row[1] and row[2] == "PASS" for row in R.rows),
        "Celery tasks": any(row[0].startswith("K") and row[2] == "PASS" for row in R.rows),
        "WebSocket consumers": any("WebSocket" in row[1] and row[2] == "PASS" for row in R.rows),
    }
    for name, ok in smoke.items():
        R.check(f"Smoke: {name}", ok)


def print_final_report():
    tenant = R.created["tenant"]
    pass_count, fail_count = R.summary_counts()
    print("\n" + "=" * 78)
    print("PHASE 3.8 LIVE ENTERPRISE MODEL COMMUNICATION FINAL REPORT")
    print("=" * 78)
    print(f"1. Enterprise dataset created: {tenant.name} ({tenant.slug}) id={tenant.id}")
    print(f"2. License key used: {R.license_key}")
    print("3. Modules tested: gemba, audits, capa, problem_solving, five_s, risk, tpm, skills, visual_management, iso9001, lean_flow, vsm, smed, sfm, rotation_table, poka_yoke, routines, messaging")
    print("4. Model communication flows tested: Action sync, Notification sync, signals, tasks, GFK messaging, license gating, tenant isolation, soft-delete, dashboards")
    print("5. shared.Action records created by module:")
    action_counts = Counter(Action.objects.filter(tenant=tenant).values_list("module_source", flat=True))
    for source in sorted(action_counts):
        print(f"   - {source or '(blank)'}: {action_counts[source]}")
    print("6. shared.Notification records created by type:")
    notif_counts = Counter(Notification.objects.filter(tenant=tenant).values_list("notification_type", flat=True))
    for ntype in sorted(notif_counts):
        print(f"   - {ntype or '(blank)'}: {notif_counts[ntype]}")
    print("7. Signal results:")
    for row in R.rows:
        if row[0].startswith("D"):
            print(f"   - {row[2]} {row[1]} {row[3]}")
    print("8. Messaging GenericForeignKey results:")
    for row in R.rows:
        if row[0].startswith("E"):
            print(f"   - {row[2]} {row[1]}")
    print("9. Dashboard consistency results:")
    for row in R.rows:
        if row[0].startswith("G"):
            print(f"   - {row[2]} {row[1]}")
    print("10. Locked module behavior:")
    for row in R.rows:
        if row[0].startswith("H"):
            print(f"   - {row[2]} {row[1]} {row[3]}")
    print("11. Cross-tenant attack results:")
    for row in R.rows:
        if row[0].startswith("I"):
            print(f"   - {row[2]} {row[1]} {row[3]}")
    print("12. Soft-delete communication results:")
    for row in R.rows:
        if row[0].startswith("J"):
            print(f"   - {row[2]} {row[1]} {row[3]}")
    print("13. Celery task results:")
    for row in R.rows:
        if row[0].startswith("K"):
            print(f"   - {row[2]} {row[1]} {row[3]}")
    print("14. Bugs found:")
    if R.bugs:
        for bug in R.bugs:
            print(f"   - {bug}")
    else:
        print("   - None")
    print("15. Patches applied:")
    print("   - Fixed select_for_update() nullable joins in SFM, Poka-Yoke, and Routines services.")
    print("   - Added same-day idempotency for Poka-Yoke, Routine, Skills, ISO, and Andon notifications.")
    print("   - Added Messaging GenericForeignKey tenant validation.")
    print("   - Switched billing/ISO/skills date checks to timezone.localdate().")
    print("16. Remaining risks:")
    if R.notes:
        for note in R.notes:
            print(f"   - {note}")
    print("   - Test data intentionally left in database under slugs acme-e2e and beta-e2e for inspection.")
    print(f"   - PASS={pass_count} FAIL={fail_count}")
    verdict = "ENTERPRISE MODEL COMMUNICATION APPROVED" if fail_count == 0 and not R.bugs else "PATCHES REQUIRED BEFORE FRONTEND"
    print(f"17. Final verdict: {verdict}")


def main():
    tenant, site, departments, users, employees = setup_enterprise()
    phase_b_actions(tenant, site, departments, users, employees)
    phase_c_notifications_and_tasks(tenant, departments, users, employees)
    phase_d_signals(tenant, users, employees)
    phase_e_messaging(tenant, users, employees)
    phase_f_factory_day(tenant, users, employees)
    phase_g_dashboards(tenant)
    phase_h_locked_modules(tenant, users)
    phase_i_cross_tenant_attacks(tenant, site, departments, users, employees)
    phase_j_soft_delete(tenant)
    phase_k_celery(tenant, users, employees)
    phase_l_api_model_contracts(tenant, users)
    phase_m_final_commands()
    print_final_report()


if __name__ == "__main__":
    try:
        main()
    finally:
        set_current_tenant(None)
