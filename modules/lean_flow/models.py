# modules/lean_flow/models.py
"""
Lean Flow Module -- OPEX SaaS
Manufacturing flow control: Kanban cards, CONWIP tickets, DDMRP buffers.

Merged from legacy standalone Kanban/CONWIP/DDMRP apps into the enterprise
multi-tenant platform with BaseModel, tenant isolation, and shared Actions.

Layer 1 -- Visual Board (FlowBoard / FlowColumn / FlowCard)
Layer 2 -- Kanban Card System (KanbanFlowConfig / KanbanCard)
Layer 3 -- CONWIP Ticket System (ConwipLine / ConwipLineStation / ConwipTicket)
Layer 4 -- DDMRP Buffer Engine (DDMRPBuffer / DDMRPRecommendation)
"""
import uuid
import math
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from shared.base import BaseModel
from accounts.managers import TenantManager


# =====================================================================
# LAYER 1 -- VISUAL BOARD (generic task board)
# =====================================================================

class FlowBoard(BaseModel):
    """A Kanban / CONWIP / DDMRP board container."""
    class BoardType(models.TextChoices):
        KANBAN = "kanban", "Kanban"
        CONWIP = "conwip", "CONWIP"
        DDMRP  = "ddmrp",  "DDMRP"

    name        = models.CharField(max_length=200)
    board_type  = models.CharField(max_length=20, choices=BoardType.choices, default=BoardType.KANBAN)
    description = models.TextField(blank=True)
    wip_limit   = models.PositiveIntegerField(default=0, help_text="Global WIP limit (0 = unlimited)")

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_boards"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_board_type_display()})"


class FlowColumn(models.Model):
    """Configuration entity (hard delete). Column inside a FlowBoard."""
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board          = models.ForeignKey(FlowBoard, on_delete=models.CASCADE, related_name="columns")
    tenant         = models.ForeignKey("core.Tenant", on_delete=models.CASCADE, related_name="lean_flow_columns")
    name           = models.CharField(max_length=100)
    position       = models.IntegerField(default=0)
    wip_limit      = models.PositiveIntegerField(default=0)
    is_done_column = models.BooleanField(default=False)

    class Meta:
        db_table = "lean_flow_columns"
        ordering = ["board", "position"]

    def __str__(self):
        return f"{self.board.name} / {self.name}"


class FlowCard(BaseModel):
    """Work item card on a board. Syncs to shared.models.Action."""
    class Priority(models.TextChoices):
        LOW      = "low",      "Bas"
        MEDIUM   = "medium",   "Moyen"
        HIGH     = "high",     "Eleve"
        CRITICAL = "critical", "Critique"

    board       = models.ForeignKey(FlowBoard, on_delete=models.CASCADE, related_name="cards")
    column      = models.ForeignKey(FlowColumn, on_delete=models.CASCADE, related_name="cards")
    title       = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    priority    = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_to = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="lean_flow_cards"
    )
    due_date    = models.DateField(null=True, blank=True)
    position    = models.IntegerField(default=0)

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_cards"
        ordering = ["column", "position"]

    def __str__(self):
        return f"{self.title} ({self.get_priority_display()})"

    def sync_to_shared_action(self):
        from shared.models import Action
        status = "done" if self.column.is_done_column else "in_progress"
        if self.position == 0 and not self.column.is_done_column:
            status = "open"
        action, _ = Action.objects.update_or_create(
            reference_id=self.id, module_source="lean_flow", tenant=self.tenant,
            defaults={
                "title": f"[Lean Flow] {self.title}",
                "description": self.description,
                "priority": self.priority,
                "status": status,
                "assigned_to": self.assigned_to,
                "due_date": self.due_date,
                "created_by": self.created_by,
                "action_type": f"lean_flow_{self.board.board_type}",
            }
        )
        return action


# =====================================================================
# LAYER 2 -- KANBAN CARD SYSTEM (from legacy kanban app)
# =====================================================================

class KanbanFlowConfig(BaseModel):
    """
    Configuration of a Kanban flow between two workstations.
    Optimal card count is auto-calculated on save using:
      cards = ceil(demand_avg * lead_time_days / container_capacity * 1.1)
    """
    board = models.ForeignKey(FlowBoard, on_delete=models.CASCADE, related_name="kanban_flows")
    reference = models.CharField(max_length=100, help_text="Article / SKU reference")
    supplier_station = models.CharField(max_length=150, help_text="Upstream workstation name")
    consumer_station = models.CharField(max_length=150, help_text="Downstream workstation name")
    demand_avg = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))],
        help_text="Average daily demand (units/day)"
    )
    lead_time_days = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0"))],
        help_text="Replenishment lead time in days"
    )
    container_capacity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)], help_text="Units per Kanban card/container"
    )
    optimal_card_count = models.PositiveIntegerField(
        default=0, help_text="Auto-calculated on save"
    )

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_kanban_configs"
        ordering = ["reference"]
        unique_together = ("board", "reference", "supplier_station", "consumer_station")

    def __str__(self):
        return f"Kanban {self.reference}: {self.supplier_station} -> {self.consumer_station}"

    def calculate_optimal_cards(self):
        """Kanban formula with 10% safety factor."""
        if self.container_capacity > 0:
            need = float(self.demand_avg) * float(self.lead_time_days)
            self.optimal_card_count = math.ceil((need / self.container_capacity) * 1.1)
        else:
            self.optimal_card_count = 0

    def save(self, *args, **kwargs):
        self.calculate_optimal_cards()
        super().save(*args, **kwargs)


class KanbanCard(BaseModel):
    """
    Physical Kanban card with FULL/EMPTY status.
    Transition to EMPTY can trigger replenishment actions.
    """
    class CardStatus(models.TextChoices):
        FULL  = "full",  "Plein"
        EMPTY = "empty", "Vide"

    flow = models.ForeignKey(KanbanFlowConfig, on_delete=models.CASCADE, related_name="cards")
    code = models.CharField(max_length=50, unique=True, help_text="Unique card code (auto-generated)")
    status = models.CharField(max_length=10, choices=CardStatus.choices, default=CardStatus.FULL)
    quantity = models.PositiveIntegerField(default=0, help_text="Current quantity in container")
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    scanned_by = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="kanban_scans"
    )

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_kanban_cards"
        ordering = ["-last_scanned_at"]

    def __str__(self):
        return f"Card {self.code} - {self.get_status_display()}"

    def scan(self, employee=None):
        """Toggle status on scan. Returns new status."""
        if self.status == self.CardStatus.FULL:
            self.status = self.CardStatus.EMPTY
            self.quantity = 0
        else:
            self.status = self.CardStatus.FULL
            self.quantity = self.flow.container_capacity
        self.last_scanned_at = timezone.now()
        self.scanned_by = employee
        self.save(update_fields=["status", "quantity", "last_scanned_at", "scanned_by", "updated_at"])
        return self.status

    def sync_to_shared_action(self):
        """Creates replenishment action when card goes EMPTY."""
        if self.status == self.CardStatus.EMPTY:
            from shared.models import Action
            action, _ = Action.objects.update_or_create(
                reference_id=self.id, module_source="lean_flow", tenant=self.tenant,
                defaults={
                    "title": f"[Kanban Replenish] {self.flow.reference} @ {self.flow.supplier_station}",
                    "description": f"Card {self.code} is EMPTY. Qty needed: {self.flow.container_capacity}",
                    "priority": "high",
                    "status": "open",
                    "created_by": self.created_by,
                    "action_type": "kanban_replenishment",
                }
            )
            return action
        return None


# =====================================================================
# LAYER 3 -- CONWIP TICKET SYSTEM (from legacy conwip app)
# =====================================================================

class ConwipLine(BaseModel):
    """
    Production line with a critical WIP limit.
    Tickets circulate through the line; new work starts only when a ticket is free.
    """
    board = models.ForeignKey(FlowBoard, on_delete=models.CASCADE, related_name="conwip_lines")
    name = models.CharField(max_length=150)
    wip_critical = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Max CONWIP tickets allowed in circulation"
    )

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_conwip_lines"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_current_wip(self):
        return self.tickets.filter(status__in=["waiting", "in_progress"]).count()

    def is_saturated(self):
        return self.get_current_wip() >= self.wip_critical


class ConwipLineStation(models.Model):
    """Ordered station sequence within a CONWIP line. Config entity (hard delete)."""
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line     = models.ForeignKey(ConwipLine, on_delete=models.CASCADE, related_name="stations")
    tenant   = models.ForeignKey("core.Tenant", on_delete=models.CASCADE, related_name="conwip_stations")
    name     = models.CharField(max_length=150)
    position = models.PositiveIntegerField(help_text="Order in the sequence (1-based)")
    is_bottleneck = models.BooleanField(default=False)

    class Meta:
        db_table = "lean_flow_conwip_stations"
        ordering = ["line", "position"]
        unique_together = ("line", "position")

    def __str__(self):
        bn = " (BOTTLENECK)" if self.is_bottleneck else ""
        return f"{self.line.name} #{self.position}: {self.name}{bn}"


class ConwipTicket(BaseModel):
    """
    CONWIP ticket circulating through a production line.
    State machine: free -> waiting -> in_progress -> (back to free on release).
    """
    class TicketStatus(models.TextChoices):
        FREE        = "free",        "Libre"
        WAITING     = "waiting",     "En attente"
        IN_PROGRESS = "in_progress", "En cours"

    line = models.ForeignKey(ConwipLine, on_delete=models.CASCADE, related_name="tickets")
    number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=TicketStatus.choices, default=TicketStatus.FREE)
    current_station = models.ForeignKey(
        ConwipLineStation, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="current_tickets"
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_conwip_tickets"
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"Ticket {self.number} - {self.get_status_display()}"

    def assign(self, station):
        """Assign ticket to start of line."""
        self.status = self.TicketStatus.WAITING
        self.current_station = station
        self.assigned_at = timezone.now()
        self.released_at = None
        self.save(update_fields=["status", "current_station", "assigned_at", "released_at", "updated_at"])

    def start(self):
        if self.status == self.TicketStatus.WAITING:
            self.status = self.TicketStatus.IN_PROGRESS
            self.save(update_fields=["status", "updated_at"])

    def advance(self, next_station):
        self.current_station = next_station
        self.save(update_fields=["current_station", "updated_at"])

    def release(self):
        """Release ticket back to free pool."""
        self.status = self.TicketStatus.FREE
        self.current_station = None
        self.released_at = timezone.now()
        self.save(update_fields=["status", "current_station", "released_at", "updated_at"])


# =====================================================================
# LAYER 4 -- DDMRP BUFFER ENGINE (from legacy ddmrp app)
# =====================================================================

class DDMRPBuffer(BaseModel):
    """
    DDMRP buffer with auto-calculated zone thresholds.
    Formulas (legacy-compatible):
      red_zone   = ADU * lead_time * lt_factor
      yellow_zone = ADU * lead_time
      green_zone  = ADU * lead_time * variability_factor + MOQ
    """
    class BufferStatus(models.TextChoices):
        RED    = "red",    "Rouge (critique)"
        YELLOW = "yellow", "Jaune (alerte)"
        GREEN  = "green",  "Vert (nominal)"

    board = models.ForeignKey(FlowBoard, on_delete=models.CASCADE, related_name="buffers")
    reference = models.CharField(max_length=100, help_text="SKU or part reference")

    # Input parameters
    adu = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Average Daily Usage"
    )
    lead_time_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=1,
        validators=[MinValueValidator(Decimal("0"))]
    )
    lt_factor = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Lead time factor (typically 0.5)"
    )
    variability_factor = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Demand variability factor (0.0 - 1.0)"
    )
    moq = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Minimum Order Quantity"
    )

    # Auto-calculated zone thresholds
    red_zone = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    yellow_zone = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    green_zone = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    current_stock = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))]
    )
    current_status = models.CharField(max_length=10, choices=BufferStatus.choices, default=BufferStatus.GREEN)
    last_calculated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_ddmrp_buffers"
        ordering = ["reference"]
        unique_together = ("board", "reference")

    def __str__(self):
        return f"{self.reference} ({self.get_current_status_display()})"

    def calculate_zones(self):
        """DDMRP zone calculation formulas."""
        adu_f = float(self.adu)
        lt_f = float(self.lead_time_days)
        self.red_zone = Decimal(adu_f * lt_f * float(self.lt_factor))
        self.yellow_zone = Decimal(adu_f * lt_f)
        self.green_zone = Decimal(adu_f * lt_f * float(self.variability_factor) + float(self.moq))
        self.last_calculated_at = timezone.now()

    def recalculate_status(self):
        """Determines buffer status from current_stock vs cumulative zones."""
        stock = float(self.current_stock)
        if stock <= float(self.red_zone):
            self.current_status = self.BufferStatus.RED
        elif stock <= float(self.red_zone + self.yellow_zone):
            self.current_status = self.BufferStatus.YELLOW
        else:
            self.current_status = self.BufferStatus.GREEN
        self.save(update_fields=["current_status", "updated_at"])

    def get_optimal_replenishment_qty(self):
        """Target level = red + yellow + green. Returns qty needed."""
        target = float(self.red_zone + self.yellow_zone + self.green_zone)
        qty = max(0, target - float(self.current_stock))
        if qty > 0 and qty < float(self.moq):
            qty = float(self.moq)
        return Decimal(qty)

    def save(self, *args, **kwargs):
        self.calculate_zones()
        super().save(*args, **kwargs)


class DDMRPRecommendation(BaseModel):
    """
    System-generated recommendation from DDMRP analysis.
    Types: replenish, accelerate, slow_down, cancel.
    """
    class RecoType(models.TextChoices):
        REPLENISH  = "replenish",  "Reapprovisionner"
        ACCELERATE = "accelerate", "Accelerer production"
        SLOW_DOWN  = "slow_down",  "Ralentir production"
        CANCEL     = "cancel",     "Annuler commande"

    class RecoStatus(models.TextChoices):
        PENDING  = "pending",  "En attente"
        APPROVED = "approved", "Approuvee"
        EXECUTED = "executed", "Executee"
        REJECTED = "rejected", "Rejetee"

    buffer = models.ForeignKey(DDMRPBuffer, on_delete=models.CASCADE, related_name="recommendations")
    recommendation_type = models.CharField(max_length=20, choices=RecoType.choices)
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))]
    )
    priority = models.IntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1=highest, 5=lowest"
    )
    status = models.CharField(max_length=20, choices=RecoStatus.choices, default=RecoStatus.PENDING)
    justification = models.TextField(blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    executed_by = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="ddmrp_executions"
    )

    objects = TenantManager()

    class Meta:
        db_table = "lean_flow_ddmrp_recommendations"
        ordering = ["priority", "-created_at"]

    def __str__(self):
        return f"{self.get_recommendation_type_display()} - {self.buffer.reference} (P{self.priority})"

    def execute(self, employee):
        if self.status != self.RecoStatus.PENDING:
            raise ValueError("Only pending recommendations can be executed")
        self.status = self.RecoStatus.EXECUTED
        self.executed_at = timezone.now()
        self.executed_by = employee
        self.save(update_fields=["status", "executed_at", "executed_by", "updated_at"])

    def sync_to_shared_action(self):
        from shared.models import Action
        priority_map = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "low"}
        status_map = {"pending": "open", "approved": "in_progress", "executed": "done", "rejected": "done"}
        action, _ = Action.objects.update_or_create(
            reference_id=self.id, module_source="lean_flow", tenant=self.tenant,
            defaults={
                "title": f"[DDMRP] {self.get_recommendation_type_display()} - {self.buffer.reference}",
                "description": self.justification,
                "priority": priority_map.get(self.priority, "medium"),
                "status": status_map.get(self.status, "open"),
                "assigned_to": self.executed_by,
                "created_by": self.created_by,
                "action_type": "ddmrp_recommendation",
            }
        )
        return action
