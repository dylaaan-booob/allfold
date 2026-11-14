"""Configuration admission, scoped task revocation and lock-free settlement."""
from allfold.application.coordinators.run_coordinator import CoordinatorStatus


def settings_task_active(app) -> bool:
    return (bool(app.state.browser_task_lock.owners) or app.state.workspace_tasks.active
            or app.state.workspace_tasks.changing
            or app.state.run_coordinator.snapshot().status is CoordinatorStatus.RUNNING
            or app.state.wos_coordinator.running)


def settings_input_active(app) -> bool:
    """Ordinary edits retain foreground snapshot protection only."""
    return (app.state.workspace_tasks.changing
            or any(owner.exclusive or owner.kind == 'wos'
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
    """Read-only preflight; rejected drafts never stop background work."""
    from allfold.application.browser_services import browser_scope_id
    if settings_input_active(app):
        return True, None
    owned = app.state.workspace_tasks.browser_owner_ids
    foreground = tuple(owner for owner in app.state.browser_task_lock.owners if owner.id not in owned)
    if (before.output_dir != after.output_dir or any(
            getattr(after, f'{provider}_key_action') != 'keep' for provider in ('pubmed', 'openalex'))):
        if foreground:
            return True, None
    affected, authentication_changed = settings_access_change(before, after)
    if not affected and not authentication_changed:
        return False, None
    scope = browser_scope_id(app.state.config_path)
    scopes = {f'service:{scope}:{service_id}' for service_id in affected}
    if any(owner.exclusive or owner.scopes & scopes for owner in foreground):
        return True, None
    return False, app.state.login.access_invalidation(scope, affected, authentication_changed)


def settings_revisions_current(before, after):
    return (before.monitor_revision == after.monitor_revision and before.journal_revision == after.journal_revision
            and all(getattr(after, f'{provider}_key_action') == 'keep'
                    or getattr(after, f'{provider}_key_revision') == getattr(before, f'{provider}_key_revision')
                    for provider in ('pubmed', 'openalex')))


def prepare_settings_effects(app, effects, invalidation, before, after):
    """Reserve a validated change under short settings admission; never wait."""
    from allfold.application.browser_services import browser_scope_id
    affected, all_access = settings_access_change(before, after)
    providers = {provider for provider in ('pubmed', 'openalex')
                 if getattr(after, f'{provider}_key_action') != 'keep'}
    whole = before.output_dir != after.output_dir
    if not (whole or affected or all_access or providers):
        return
    scopes = {f'service:{browser_scope_id(app.state.config_path)}:{service_id}' for service_id in affected}
    kind = 'workspace-reset' if whole else 'access-cleanup'
    control = app.state.browser_task_lock.reserve_control(kind, scopes=() if whole else scopes)
    if control is None:
        raise ValueError('Affected Browser control is already in progress')
    slot = False
    try:
        if whole:
            slot = app.state.run_slot.acquire(blocking=False)
            if not slot:
                raise ValueError('A foreground Run is active')
        change = app.state.workspace_tasks.begin_change(whole=whole, services=affected,
            all_access=all_access, providers=providers)
    except BaseException:
        if slot:
            app.state.run_slot.release()
        app.state.browser_task_lock.release_control(control)
        raise
    effects.update(change=change, control=control, slot=slot)


def drain_settings_effects(app, effects):
    change = effects.get('change')
    if change is None:
        return
    app.state.workspace_tasks.drain_change(change)
    control = effects['control']
    with app.state.settings_write_lock:
        owner = app.state.browser_task_lock.acquire(control.kind, scopes=control.scopes, control=control)
        if owner is None:
            raise RuntimeError('Affected Browser work did not settle')
        effects['owner'] = owner


def record_settings_effects(app, effects, invalidation, before, after):
    affected, authentication_changed = settings_access_change(before, after)
    if invalidation:
        keys = {key: value for key, value in invalidation['preparation_keys'].items() if key in affected}
        authentication = invalidation['authentication_key'] if authentication_changed else None
        invalidation = {**invalidation, 'preparation_keys': keys, 'authentication_key': authentication} if keys or authentication else None
    effects.update(invalidation=invalidation, page_limits=before.workflow != after.workflow)


def settle_settings_effects(app, effects):
    """All native waits and exact releases happen outside configuration locks."""
    try:
        invalidation = effects.get('invalidation')
        if invalidation:
            app.state.electron_bridge.execute('invalidate_access', invalidation).result()
        if effects.get('page_limits'):
            refresh = getattr(app.state.electron_bridge, 'refresh_page_limits', None)
            if refresh and (pending := refresh()) is not None:
                pending.result()
    finally:
        if effects.get('owner') is not None:
            app.state.browser_task_lock.release(effects['owner'])
        if effects.get('control') is not None:
            app.state.browser_task_lock.release_control(effects['control'])
        try:
            if effects.get('change') is not None:
                with app.state.settings_write_lock:
                    app.state.workspace_tasks.finish_change(effects['change'])
        finally:
            if effects.get('slot'):
                app.state.run_slot.release()
