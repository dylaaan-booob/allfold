"""One admission boundary for configuration writes and new task snapshots."""
from allfold.application.coordinators.run_coordinator import CoordinatorStatus


def settings_task_active(app) -> bool:
    # Browser ownership spans Kept waiting/transition, native settlement and the
    # standalone Prepare/Import/Enrich/Cover tasks. Do not take their controller
    # locks while holding admission: their terminal workers release ownership.
    return (app.state.browser_task_lock.owner is not None
            or app.state.run_coordinator.snapshot().status is CoordinatorStatus.RUNNING
            or app.state.wos_coordinator.running)
