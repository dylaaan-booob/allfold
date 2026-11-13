"""One admission boundary for configuration writes and new task snapshots."""
from allfold.application.coordinators.run_coordinator import CoordinatorStatus


def settings_task_active(app) -> bool:
    # Destructive/control operations wait for every admitted owner, including
    # native cleanup. Their terminal workers release admission without taking
    # the configuration write lock.
    return (bool(app.state.browser_task_lock.owners)
            or app.state.run_coordinator.snapshot().status is CoordinatorStatus.RUNNING
            or app.state.wos_coordinator.running)


def settings_input_active(app) -> bool:
    """Foreground snapshot writers and actual controls retain their old gate."""
    return (any(owner.exclusive or owner.kind in {'wos', 'preprint-lookup'}
                for owner in app.state.browser_task_lock.owners)
            or app.state.run_coordinator.snapshot().status is CoordinatorStatus.RUNNING
            or app.state.wos_coordinator.running)


def settings_access_change(before, after):
    previous = {service.id: service for service in before.access_services}
    current = {service.id: service for service in after.access_services}
    authentication_changed = before.institution != after.institution
    affected = (set(previous) | set(current) if authentication_changed else
                {key for key in previous.keys() | current.keys() if previous.get(key) != current.get(key)})
    return affected, authentication_changed


def settings_write_context(app, before, after):
    """Called under admission; returns old keys, never authority for new contexts."""
    from allfold.application.browser_services import browser_scope_id
    if settings_input_active(app):
        return True, None
    if (before.output_dir != after.output_dir or any(
            getattr(after, f'{provider}_key_action') != 'keep' for provider in ('pubmed', 'openalex'))):
        if settings_task_active(app):
            return True, None
    affected, authentication_changed = settings_access_change(before, after)
    if not affected and not authentication_changed:
        return False, None
    scope = browser_scope_id(app.state.config_path)
    if app.state.browser_task_lock.conflicts(f'service:{scope}:{service_id}' for service_id in affected):
        return True, None
    return False, app.state.login.access_invalidation(scope, affected, authentication_changed)


def settle_settings_effects(app, effects):
    """Wait outside configuration locks; captured old keys cannot touch new work."""
    try:
        invalidation = effects.get('invalidation')
        if invalidation and app.state.electron_bridge.connected:
            app.state.electron_bridge.execute('invalidate_access', invalidation).result()
        if effects.get('page_limits'):
            refresh = getattr(app.state.electron_bridge, 'refresh_page_limits', None)
            if refresh and (pending := refresh()) is not None:
                pending.result()
    finally:
        if effects.get('owner') is not None:
            app.state.browser_task_lock.release(effects['owner'])


def record_settings_effects(app, effects, invalidation, before, after):
    # Keep controls and overlapping Prepare behind actual native cleanup without
    # holding a configuration lock while the bridge result is in flight.
    affected, authentication_changed = settings_access_change(before, after)
    if invalidation:
        keys = {key: value for key, value in invalidation['preparation_keys'].items() if key in affected}
        authentication = invalidation['authentication_key'] if authentication_changed else None
        invalidation = {**invalidation, 'preparation_keys': keys, 'authentication_key': authentication} if keys or authentication else None
    effects.update(invalidation=invalidation, page_limits=before.workflow != after.workflow)
    if invalidation and app.state.electron_bridge.connected:
        effects['owner'] = app.state.browser_task_lock.acquire('access-cleanup', scopes={
            f"service:{invalidation['scope_id']}:{service_id}" for service_id in invalidation['preparation_keys']})
        if effects['owner'] is None:
            raise RuntimeError('Browser access cleanup admission changed')
