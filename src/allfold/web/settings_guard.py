"""Configuration admission, scoped task revocation and lock-free settlement."""
from allfold.application.browser_services import browser_scope_id, service_access
from allfold.application.carsi_entry import school_identity
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
    previous = {service.id: service_access(service) for service in before.access_services}
    current = {service.id: service_access(service) for service in after.access_services}
    affected = {key for key in previous.keys() | current.keys() if previous.get(key) != current.get(key)}
    return affected, school_identity(before.institution) != school_identity(after.institution)


def settings_write_context(app, before, after):
    """Read-only preflight; rejected drafts never stop background work."""
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
    return False, scope


def settings_revisions_current(before, after):
    return (before.monitor_revision == after.monitor_revision and before.journal_revision == after.journal_revision
            and all(getattr(after, f'{provider}_key_action') == 'keep'
                    or getattr(after, f'{provider}_key_revision') == getattr(before, f'{provider}_key_revision')
                    for provider in ('pubmed', 'openalex')))


def prepare_settings_effects(app, effects, invalidation, before, after):
    """Reserve a validated change under short settings admission; never wait."""
    affected, school_changed = settings_access_change(before, after)
    providers = {provider for provider in ('pubmed', 'openalex')
                 if getattr(after, f'{provider}_key_action') != 'keep'}
    whole = before.output_dir != after.output_dir
    if not (whole or affected or school_changed or providers):
        return
    scopes = {f'service:{browser_scope_id(app.state.config_path)}:{service_id}' for service_id in affected}
    if school_changed:
        scopes.add('authentication:' + browser_scope_id(app.state.config_path))
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
            providers=providers)
    except BaseException:
        if slot:
            app.state.run_slot.release()
        app.state.browser_task_lock.release_control(control)
        raise
    auth_scope = 'authentication:' + browser_scope_id(app.state.config_path)
    cancel_login = school_changed and any(owner.kind == 'login' and auth_scope in owner.scopes
                                         for owner in app.state.browser_task_lock.owners)
    effects.update(change=change, control=control, slot=slot, school_changed=school_changed, cancel_login=cancel_login)
    if cancel_login:
        app.state.login.shutdown()


def drain_settings_effects(app, effects):
    change = effects.get('change')
    if change is None:
        return
    if effects.get('cancel_login'):
        app.state.login.join()
    app.state.workspace_tasks.drain_change(change)
    if effects.get('school_changed') and app.state.electron_bridge.connected:
        result = app.state.electron_bridge.execute('pause_authentication', {}).result()
        if result.get('ok') is not True:
            raise RuntimeError('School authentication could not be paused')
        effects['authentication_paused'] = True
    control = effects['control']
    with app.state.settings_write_lock:
        owner = app.state.browser_task_lock.acquire(control.kind, scopes=control.scopes, control=control)
        if owner is None:
            raise RuntimeError('Affected Browser work did not settle')
        effects['owner'] = owner


def record_settings_effects(app, effects, invalidation, before, after):
    affected, _ = settings_access_change(before, after)
    invalidation = {'scope_id': invalidation, 'service_ids': sorted(affected)} if invalidation and affected else None
    limits = ('managed_page_global_limit', 'managed_page_service_limit')
    effects.update(invalidation=invalidation, page_limits=any(
        getattr(before.workflow, field) != getattr(after.workflow, field) for field in limits))


def settle_settings_effects(app, effects):
    """All native waits and exact releases happen outside configuration locks."""
    try:
        invalidation = effects.get('invalidation')
        if invalidation:
            app.state.login.forget_services(invalidation['scope_id'], invalidation['service_ids'])
            if app.state.electron_bridge.connected:
                app.state.electron_bridge.execute('invalidate_access', invalidation).result()
        if effects.get('page_limits'):
            refresh = getattr(app.state.electron_bridge, 'refresh_page_limits', None)
            if refresh and (pending := refresh()) is not None:
                pending.result()
    finally:
        try:
            if effects.get('authentication_paused'):
                app.state.electron_bridge.execute('resume_authentication', {}).result()
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
