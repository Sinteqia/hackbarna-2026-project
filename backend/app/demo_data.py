"""SYNTHETIC DEMO DATA for the hackathon scheduling demo. Not real workers or projects."""

from app.models import Company, Environment, Intensity, ScheduledTask, Site, Task, Worker, WorkZone

DATA_LABEL = "SYNTHETIC DEMO DATA"

COMPANY = Company(id="company_demo", name="Operational Adaptation demo company")

# Illustrative demo coordinates (Barcelona). Owned here, not by the weather adapter.
SITE = Site(
    id="site_barcelona",
    name="Construction Site — Barcelona",
    location_name="Barcelona",
    latitude=41.3874,
    longitude=2.1686,
)

# The WorkZone owns the environment classification; tasks derive theirs from it.
ZONES = [
    WorkZone(id="zone_loading", site_id=SITE.id, name="Loading", environment=Environment.OUTDOOR),
    WorkZone(id="zone_structural", site_id=SITE.id, name="Structural", environment=Environment.OUTDOOR),
    WorkZone(
        id="zone_covered_installation", site_id=SITE.id, name="Covered Installation",
        environment=Environment.PARTIAL,
    ),
    WorkZone(id="zone_site_office", site_id=SITE.id, name="Site Office", environment=Environment.INDOOR),
]
_ZONE_ENVIRONMENT = {z.id: z.environment for z in ZONES}

WORKERS = [
    Worker(id="w_marc", name="Marc", skills=["GENERAL"], available_from="07:00", available_to="16:00"),
    Worker(id="w_laura", name="Laura", skills=["ELECTRICAL"], available_from="08:00", available_to="17:00"),
    Worker(id="w_joan", name="Joan", skills=["GENERAL"], available_from="07:00", available_to="17:00"),
    Worker(id="w_alex", name="Alex", skills=["CONCRETE"], available_from="07:00", available_to="18:00"),
]


def _task(work_zone_id: str, **fields) -> Task:
    """Build a task in a zone; its environment (read by H5) comes from the zone, never set twice."""
    return Task(work_zone_id=work_zone_id, environment=_ZONE_ENVIRONMENT[work_zone_id], **fields)


TASKS = [
    _task(
        "zone_loading", id="t_unload", name="Material unloading", duration_hours=1,
        required_skill="GENERAL", intensity=Intensity.HIGH,
    ),
    _task(
        "zone_structural", id="t_concrete", name="Concrete pouring", duration_hours=2,
        required_skill="CONCRETE", intensity=Intensity.HIGH, dependencies=["t_unload"],
    ),
    _task(
        "zone_covered_installation", id="t_electrical", name="Electrical installation", duration_hours=2,
        required_skill="ELECTRICAL", intensity=Intensity.MEDIUM,
    ),
    _task(
        "zone_structural", id="t_assembly", name="Outdoor assembly", duration_hours=2,
        required_skill="GENERAL", intensity=Intensity.HIGH, dependencies=["t_concrete"],
        mandatory_deadline="17:00",
    ),
    _task(
        "zone_site_office", id="t_docs", name="Documentation", duration_hours=1,
        required_skill="GENERAL", intensity=Intensity.LOW, mandatory_deadline="17:00",
    ),
]

_TASK_NAMES = {t.id: t.name for t in TASKS}
_WORKER_NAMES = {w.id: w.name for w in WORKERS}


def _item(task_id: str, worker_id: str, start: str, end: str) -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id, task_name=_TASK_NAMES[task_id],
        worker_id=worker_id, worker_name=_WORKER_NAMES[worker_id],
        start=start, end=end,
    )


# CURRENT PLAN (not solver-generated): the schedule that existed before the heat constraint.
# It respects the task sequence but has high-intensity outdoor work inside 12:00-16:00.
CURRENT_PLAN = [
    _item("t_unload", "w_marc", "08:00", "09:00"),
    _item("t_concrete", "w_alex", "11:00", "13:00"),
    _item("t_electrical", "w_laura", "12:00", "14:00"),
    _item("t_assembly", "w_marc", "14:00", "16:00"),
    _item("t_docs", "w_joan", "16:00", "17:00"),
]
