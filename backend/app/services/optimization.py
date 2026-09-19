"""Trusted optimization flow: context -> OR-Tools scheduler -> independent validator.

The validator is given the SAME backend-owned context and never the solver's verdict.
A candidate is only exposed as a schedule when the validator accepts it.
"""

from collections.abc import Callable

from app.models import OptimizeResponse, ScheduleInput
from app.services.scenario import OperationalContext, site_view, worker_roster
from app.services.scheduler import find_heat_conflicts, schedule
from app.services.validator import validate_schedule


def run_optimization(
    context: OperationalContext,
    scheduler_fn: Callable = schedule,
    validator_fn: Callable = validate_schedule,
) -> OptimizeResponse:
    windows = context.risk.windows
    # H9 is passed to the validator only when a wildfire assessment took part (baseline: unchanged).
    extra = {} if context.wildfire_restrictions is None else {"wildfire_restrictions": context.wildfire_restrictions}
    current_validation = validator_fn(context.current_plan, context.workers, context.tasks, windows, **extra)
    result = scheduler_fn(
        ScheduleInput(
            workers=context.workers, tasks=context.tasks,
            heat_windows=windows, current_plan=context.current_plan,
            wildfire_restrictions=context.wildfire_restrictions or [],
        )
    )

    status, message = result.status, result.message
    schedule_out, changes, validation, validated = result.schedule, result.changes, None, False
    if result.status == "FEASIBLE":
        validation = validator_fn(result.schedule, context.workers, context.tasks, windows, **extra)
        validated = validation.valid
        if not validated:
            status = "VALIDATION_FAILED"
            message = "Solver candidate was rejected by the independent validator"
            schedule_out, changes = [], []  # never expose an unvalidated plan
    else:
        schedule_out, changes = [], []

    return OptimizeResponse(
        scenario=context.scenario,
        data_label=context.data_label,
        risk=context.risk,
        site=site_view(context),
        workers=worker_roster(context),
        current_plan=context.current_plan,
        current_plan_conflicts=find_heat_conflicts(context.current_plan, context.tasks, windows),
        current_plan_validation=current_validation,
        status=status,
        solver=result.solver,
        validated=validated,
        schedule=schedule_out,
        changes=changes,
        validation=validation,
        message=message,
    )
