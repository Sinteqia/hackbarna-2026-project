"""Norrsken: Deepfire signal -> Site -> WorkZone/Task -> configured operational restriction (H9).

Flow: Deepfire hotspots near the Site -> spatial applicability (configured radius + freshness) ->
OUTDOOR WorkZones and their tasks -> WildfireRestriction -> OR-Tools -> independent validator.

Semantics that must never be violated:
  * a hotspot is a candidate fire signal, not a confirmed fire;
  * no hotspot / stale data / unavailable API NEVER means "low risk" or "safe";
  * Deepfire does not provide when a risk ends, so no safe-work window is inferred: the configured
    rule restricts OUTDOOR work for the whole planning day while an applicable signal exists;
  * the restriction is a CONFIGURED OPERATIONAL RULE of this prototype, not a legal prohibition.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.models import (
    Environment,
    HotspotEvidence,
    OptimizeResponse,
    WildfireAssessment,
    WildfireOptimizeResponse,
    WildfireRestriction,
)
from app.services import deepfire
from app.services.optimization import run_optimization
from app.services.scenario import OperationalContext, load_scenario
from app.services.scheduler import DAY_END_HOUR, DAY_START_HOUR, schedule

# --- CONFIGURED DEMO OPERATIONAL RULE PARAMETERS ---
# These two values are choices of this demo's operational rule. They are NOT Deepfire
# recommendations, NOT legal thresholds, NOT wildfire safety distances and NOT official
# exclusion zones. They were not tuned to obtain any particular optimization result.
RADIUS_KM = 25.0  # applicability radius around the Site
FRESH_HOURS = 24  # observation window: how recent a hotspot must be to apply
MAX_EVIDENCE = 5

PARAMETERS_NOTE = (
    f"CONFIGURED DEMO OPERATIONAL RULE PARAMETERS: applicability radius {RADIUS_KM:g} km and observation "
    f"window {FRESH_HOURS} h. They are not Deepfire recommendations, legal thresholds, wildfire safety "
    f"distances or official exclusion zones."
)

RULE_DESCRIPTION = (
    f"CONFIGURED OPERATIONAL RULE (demo): while at least one active Deepfire hotspot observed in the last "
    f"{FRESH_HOURS} h lies within {RADIUS_KM:g} km of the site, work in OUTDOOR work zones is restricted for "
    f"the whole planning day. Deepfire does not provide when the risk ends and none is inferred."
)
DISCLAIMER = (
    "A hotspot is a satellite candidate-fire signal, not a confirmed fire. Absence of hotspots, stale data or "
    "an unavailable service does not mean the site is safe. This rule is an operational configuration of this "
    "prototype, not a legal prohibition and not a Deepfire statement."
)

Fetcher = Callable[[float, float, float], tuple[list[deepfire.Hotspot], bool]]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assess_wildfire(
    context: OperationalContext,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> WildfireAssessment:
    fetcher = fetcher or deepfire.fetch_active_hotspots  # resolved at call time (testable)
    now = now or datetime.now(timezone.utc)
    site = context.site
    base = dict(
        site_id=site.id, data_source="Deepfire OGC API Features (deepfire:hotspots)", queried_at=_iso(now),
        radius_km=RADIUS_KM, fresh_hours=FRESH_HOURS, parameters_note=PARAMETERS_NOTE,
        rule_description=RULE_DESCRIPTION, disclaimer=DISCLAIMER,
    )

    try:
        hotspots, truncated = fetcher(site.latitude, site.longitude, RADIUS_KM)
    except deepfire.DeepfireUnavailable as exc:
        return WildfireAssessment(status="UNAVAILABLE", hotspots_in_radius=0, error=str(exc), **base)

    near = sorted(
        ((deepfire.haversine_km(site.latitude, site.longitude, h.lat, h.lon), h) for h in hotspots),
        key=lambda x: x[0],
    )
    near = [(d, h) for d, h in near if d <= RADIUS_KM]
    fresh_after = now - timedelta(hours=FRESH_HOURS)
    fresh = [(d, h) for d, h in near if h.observed_at >= fresh_after]

    evidence_src = fresh or near
    evidence = [
        HotspotEvidence(
            id=h.id, distance_km=round(d, 1), observed_at=_iso(h.observed_at),
            confidence=h.confidence, source=h.source,
        )
        for d, h in evidence_src[:MAX_EVIDENCE]
    ]
    common = dict(
        hotspots_in_radius=len(near),
        nearest_km=round(near[0][0], 1) if near else None,
        latest_observed_at=_iso(max(h.observed_at for _, h in near)) if near else None,
        evidence=evidence,
        **base,
    )

    if fresh:
        outdoor_zones = [z for z in context.zones if z.environment == Environment.OUTDOOR]
        zone_ids = {z.id for z in outdoor_zones}
        restriction = WildfireRestriction(
            from_time=f"{DAY_START_HOUR:02d}:00", to_time=f"{DAY_END_HOUR:02d}:00",
            outdoor_work_allowed=False, source="deepfire", rule=RULE_DESCRIPTION,
        )
        return WildfireAssessment(
            status="APPLICABLE_SIGNAL",
            affected_zone_ids=sorted(zone_ids),
            affected_task_ids=[t.id for t in context.tasks if t.work_zone_id in zone_ids],
            restriction=restriction,
            **common,
        )
    if near:  # active hotspots nearby but none recent enough: uncertain, NOT low risk
        return WildfireAssessment(status="STALE_SIGNAL", **common)
    if truncated:  # the result may be incomplete: cannot claim "no applicable signal"
        return WildfireAssessment(
            status="UNAVAILABLE", error="result truncated; applicability could not be established", **common
        )
    return WildfireAssessment(status="NO_APPLICABLE_SIGNAL", **common)


_BLOCKING = {
    "UNAVAILABLE": ("SIGNAL_UNAVAILABLE", "Deepfire data could not be obtained. No plan is presented as wildfire-cleared."),
    "STALE_SIGNAL": ("SIGNAL_STALE", "Nearby Deepfire hotspots are too old to assess. No plan is presented as wildfire-cleared."),
}


def run_wildfire_optimization(
    scenario: str,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
    scheduler_fn: Callable = schedule,
) -> WildfireOptimizeResponse:
    base = load_scenario(scenario)
    assessment = assess_wildfire(base, fetcher=fetcher, now=now)

    if assessment.status in _BLOCKING:
        status, message = _BLOCKING[assessment.status]
        result = run_optimization(base, scheduler_fn=scheduler_fn)  # only for the presentation fields
        result = result.model_copy(
            update=dict(status=status, validated=False, schedule=[], changes=[], validation=None, message=message)
        )
    else:
        restrictions = [assessment.restriction] if assessment.restriction else []
        result = run_optimization(replace(base, wildfire_restrictions=restrictions), scheduler_fn=scheduler_fn)

    return WildfireOptimizeResponse(
        **{name: getattr(result, name) for name in OptimizeResponse.model_fields}, wildfire=assessment
    )
