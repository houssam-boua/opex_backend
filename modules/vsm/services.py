# modules/vsm/services.py
"""
VSM Service Layer -- ALL business logic lives here.
ViewSets remain thin: they call services, not the other way around.
"""
from django.db import transaction
from .models import VSMMap, VSMElement, VSMVersion


class VSMService:
    """Business logic for VSM operations."""

    @staticmethod
    @transaction.atomic
    def create_snapshot(vsm_map, user, label=""):
        """
        Create an immutable version snapshot of the current VSM map state.

        1. Serialize all current elements into a diagram_data JSON blob
        2. Find the highest existing version_num and increment
        3. Freeze the current metrics
        4. Create an immutable VSMVersion record

        Uses @transaction.atomic to prevent duplicate version numbers
        under concurrent requests (the unique_together constraint acts
        as a safety net).
        """
        # 1. Serialize current elements
        elements = VSMElement.objects.filter(
            vsm_map=vsm_map, is_active=True
        ).order_by("z_index", "created_at")

        elements_data = []
        for el in elements:
            elements_data.append({
                "id": str(el.id),
                "element_type": el.element_type,
                "position_x": el.position_x,
                "position_y": el.position_y,
                "width": el.width,
                "height": el.height,
                "properties": el.properties,
                "connections": el.connections,
                "z_index": el.z_index,
            })

        snapshot_data = {
            "elements": elements_data,
            "map_name": vsm_map.name,
            "map_state": vsm_map.state,
            "status": vsm_map.status,
            "visibility": vsm_map.visibility,
            "tags": vsm_map.tags,
            "description": vsm_map.description,
        }

        # 2. Determine next version number (select_for_update prevents race)
        latest = (
            VSMVersion.objects
            .filter(vsm_map=vsm_map)
            .select_for_update()
            .order_by("-version_num")
            .first()
        )
        next_version = (latest.version_num + 1) if latest else 1

        # 3. Freeze metrics
        metrics_snapshot = dict(vsm_map.metrics_json) if vsm_map.metrics_json else {}
        metrics_snapshot.update({
            "total_lead_time": str(vsm_map.total_lead_time),
            "value_added_time": str(vsm_map.value_added_time),
            "takt_time": str(vsm_map.takt_time),
            "process_count": vsm_map.process_count,
            "bottleneck_node_id": vsm_map.bottleneck_node_id,
        })

        # 4. Create immutable version
        version = VSMVersion.objects.create(
            vsm_map=vsm_map,
            version_num=next_version,
            label=label,
            diagram_data=snapshot_data,
            metrics_snapshot=metrics_snapshot,
            tenant=vsm_map.tenant,
            created_by=user,
        )

        return version

    @staticmethod
    def recalculate_metrics(vsm_map):
        """
        Recalculate VSM metrics from current elements.
        Mirrors the legacy calculateVsmMetrics() from calculations.ts.
        """
        elements = VSMElement.objects.filter(
            vsm_map=vsm_map, is_active=True
        )

        processes = [e for e in elements if e.element_type == "process"]
        inventories = [e for e in elements if e.element_type == "inventory"]
        customers = [e for e in elements if e.element_type == "customer"]

        # Value-added time = sum of process cycleTime
        value_added_time = sum(
            e.properties.get("cycleTime", 0) for e in processes
        )

        # Lead time = cycle times + changeover times + inventory storage
        total_cycle = sum(
            e.properties.get("cycleTime", 0) + e.properties.get("changeoverTime", 0)
            for e in processes
        )
        total_inventory = sum(
            e.properties.get("storageTime", 0) * 8 * 3600  # days -> seconds (8h day)
            for e in inventories
        )
        total_lead_time = total_cycle + total_inventory

        # Takt time
        customer_demand = 100  # default
        if customers:
            customer_demand = customers[0].properties.get("demandRate", 100) or 100
        available_time = 8 * 3600  # 8h day in seconds
        takt_time = available_time / customer_demand if customer_demand > 0 else 0

        # Bottleneck (highest effective cycle time)
        bottleneck_id = ""
        max_ct = 0
        for p in processes:
            ct = p.properties.get("cycleTime", 0)
            avail = p.properties.get("availability", 100) or 100
            quality = 100 - (p.properties.get("defectRate", 0) or 0)
            effective_rate = (avail / 100) * (quality / 100)
            effective_ct = ct / effective_rate if effective_rate > 0 else ct
            if effective_ct > max_ct:
                max_ct = effective_ct
                bottleneck_id = str(p.id)

        # TRS (OEE)
        avg_trs = 0
        if processes:
            total_trs = 0
            for p in processes:
                avail = p.properties.get("availability", 100) or 100
                uptime = p.properties.get("uptime", 100) or 100
                quality = 100 - (p.properties.get("defectRate", 0) or 0)
                trs = (avail / 100) * (uptime / 100) * (quality / 100) * 100
                total_trs += trs
            avg_trs = total_trs / len(processes)

        va_ratio = (value_added_time / total_lead_time * 100) if total_lead_time > 0 else 0

        # Update map
        vsm_map.total_lead_time = total_lead_time
        vsm_map.value_added_time = value_added_time
        vsm_map.takt_time = takt_time
        vsm_map.process_count = len(processes)
        vsm_map.bottleneck_node_id = bottleneck_id
        vsm_map.metrics_json = {
            "totalLeadTime": total_lead_time,
            "totalCycleTime": value_added_time,
            "valueAddedTime": value_added_time,
            "nonValueAddedTime": total_lead_time - value_added_time,
            "valueAddedRatio": round(va_ratio, 2),
            "taktTime": round(takt_time, 2),
            "processEfficiency": round(va_ratio, 2),
            "trs": round(avg_trs, 2),
            "bottleneckProcess": bottleneck_id,
            "totalInventoryTime": sum(
                e.properties.get("storageTime", 0) for e in inventories
            ),
        }
        vsm_map.save(update_fields=[
            "total_lead_time", "value_added_time", "takt_time",
            "process_count", "bottleneck_node_id", "metrics_json", "updated_at",
        ])
        return vsm_map
