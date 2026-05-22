# modules/vsm/models.py
"""
Value Stream Mapping Module -- OPEX SaaS

Legacy-compatible with the React/Supabase VSM 4.0 frontend.

Key data structures preserved:
- vsm_elements table: element_type, position_x/y, width/height, properties (JSON),
  connections (JSON array of element IDs), z_index
- project_versions table: version_number, snapshot (JSON)
- VSM element types: supplier, customer, process, inventory, transport,
  information_flow, material_flow, kaizen_burst
- Process properties: cycleTime, changeoverTime, operators, availability,
  uptime, defectRate, batchSize, workingHoursPerDay, shifts
- Inventory properties: quantity, storageTime, storageMethod, unit
- Customer properties: demandRate, taktTimeRequired, deliveryFrequency
"""
import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from shared.base import BaseModel
from accounts.managers import TenantManager


class VSMMap(BaseModel):
    """
    A Value Stream Map project.
    Contains metadata and the live diagram_data (elements + connections).
    The React frontend stores individual elements in vsm_elements rows,
    but the backend aggregates them into diagram_data JSON for snapshots.
    """
    class State(models.TextChoices):
        CURRENT = "current", "Etat actuel"
        FUTURE  = "future",  "Etat futur"

    class Status(models.TextChoices):
        DRAFT       = "draft",       "Brouillon"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED   = "completed",   "Termine"
        ARCHIVED    = "archived",    "Archive"

    class Visibility(models.TextChoices):
        PRIVATE    = "private",    "Prive"
        DEPARTMENT = "department", "Departement"
        PUBLIC     = "public",     "Public"

    name           = models.CharField(max_length=200)
    state          = models.CharField(
        max_length=20, choices=State.choices, default=State.CURRENT
    )
    status         = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    visibility     = models.CharField(
        max_length=20, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    description    = models.TextField(blank=True)
    tags           = models.JSONField(default=list, blank=True)

    # Aggregated diagram data (full JSON snapshot of all elements + connections)
    diagram_data   = models.JSONField(
        default=dict, blank=True,
        help_text="Full diagram payload: {elements: [...], connections: [...]}"
    )

    # Computed metrics (updated on save or via service)
    total_lead_time   = models.DecimalField(
        max_digits=12, decimal_places=4, default=0,
        help_text="Total lead time in seconds"
    )
    value_added_time  = models.DecimalField(
        max_digits=12, decimal_places=4, default=0,
        help_text="Value-added time in seconds"
    )
    takt_time         = models.DecimalField(
        max_digits=12, decimal_places=4, default=0,
        help_text="Takt time in seconds"
    )
    process_count     = models.PositiveIntegerField(default=0)
    bottleneck_node_id = models.CharField(
        max_length=100, blank=True, default="",
        help_text="ID of the bottleneck process element"
    )
    metrics_json      = models.JSONField(
        default=dict, blank=True,
        help_text="Full computed metrics: trs, valueAddedRatio, recommendations, etc."
    )

    # Ownership
    owner = models.ForeignKey(
        "accounts.Employee", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="vsm_maps"
    )
    department = models.ForeignKey(
        "accounts.Department", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="vsm_maps"
    )

    objects = TenantManager()

    class Meta:
        db_table = "vsm_maps"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.get_state_display()})"


class VSMElement(BaseModel):
    """
    Individual VSM diagram element, stored per-row for granular CRUD.
    Mirrors the legacy Supabase vsm_elements table exactly.

    element_type enum: supplier, customer, process, inventory, transport,
                       information_flow, material_flow, kaizen_burst
    properties: JSON blob specific to element_type (see legacy getDefaultProperties)
    connections: JSON array of target element UUIDs
    """
    class ElementType(models.TextChoices):
        SUPPLIER         = "supplier",         "Fournisseur"
        CUSTOMER         = "customer",         "Client"
        PROCESS          = "process",          "Processus"
        INVENTORY        = "inventory",        "Stock"
        TRANSPORT        = "transport",        "Transport"
        INFORMATION_FLOW = "information_flow", "Flux d'information"
        MATERIAL_FLOW    = "material_flow",    "Flux materiel"
        KAIZEN_BURST     = "kaizen_burst",     "Kaizen"

    vsm_map      = models.ForeignKey(
        VSMMap, on_delete=models.CASCADE, related_name="elements"
    )
    element_type = models.CharField(
        max_length=30, choices=ElementType.choices
    )
    position_x   = models.FloatField(default=100)
    position_y   = models.FloatField(default=100)
    width        = models.FloatField(default=150, null=True, blank=True)
    height       = models.FloatField(default=100, null=True, blank=True)
    properties   = models.JSONField(
        default=dict, blank=True,
        help_text="Element-specific properties (cycleTime, operators, etc.)"
    )
    connections  = models.JSONField(
        default=list, blank=True,
        help_text="Array of target element UUIDs this element connects to"
    )
    z_index      = models.IntegerField(default=0, null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "vsm_elements"
        ordering = ["z_index", "created_at"]

    def __str__(self):
        name = self.properties.get("name", self.element_type)
        return f"{name} ({self.get_element_type_display()})"


class VSMVersion(BaseModel):
    """
    Immutable snapshot of a VSMMap at a point in time.
    Once created, the diagram_data MUST NOT be modified.
    Maps to the legacy project_versions table.
    """
    vsm_map      = models.ForeignKey(
        VSMMap, on_delete=models.CASCADE, related_name="versions"
    )
    version_num  = models.PositiveIntegerField(
        help_text="Auto-incremented version number"
    )
    label        = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Optional human-readable label (e.g. 'Before Kaizen Event')"
    )
    diagram_data = models.JSONField(
        default=dict,
        help_text="Frozen snapshot of diagram state at version creation time"
    )
    metrics_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Frozen metrics at snapshot time"
    )

    objects = TenantManager()

    class Meta:
        db_table = "vsm_versions"
        ordering = ["-version_num"]
        unique_together = ("vsm_map", "version_num")

    def __str__(self):
        label = self.label or f"v{self.version_num}"
        return f"{self.vsm_map.name} - {label}"
