"""Save a Journal-level preference without turning it into shared resource fact."""
from pathlib import Path

from allfold.application.carsi_catalog import get_carsi_catalog, validate_carsi_service
from allfold.application.journal_resolver import resolve_journal
from allfold.application.settings import load_settings
from allfold.config import AccessService, ConfigurationError, SettingsList
from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import (
    ContentRevision, application_data_dir, read_user_state, compare_write_user_state,
)


def choose_journal_service(config_path: Path, key: str, *, method: str, name: str = '', url: str = '',
                           expected_revision: ContentRevision, expected_monitor_revision: ContentRevision):
    disk = load_settings(config_path)
    if disk.issues:
        raise ConfigurationError('Resolve Settings errors before choosing a Service')
    if disk.draft.monitor_revision != expected_monitor_revision:
        raise ContentChangedError('Monitor configuration changed; Reload')
    snapshot = read_user_state(config_path)
    if snapshot.revision != expected_revision:
        raise ContentChangedError('Journal scope changed; Reload')
    journal = next((j for j in snapshot.state.journals if j.key == key), None)
    if journal is None:
        raise ConfigurationError('Save the Journal first')
    services, service = list(snapshot.state.access_services), None
    if method in ('carsi', 'auto'):
        if method == 'auto':
            if journal.access_service_id:
                raise ContentChangedError('Existing default preserved; choose an explicit Service to change it')
            result = resolve_journal(config_path, journal)
            if result.unique_candidate is None:
                raise ConfigurationError('No unique reliable candidate')
            name, catalog = result.unique_candidate.production, result.catalog
        else:
            catalog = get_carsi_catalog(application_data_dir(config_path) / 'resources.sqlite')
        resource = validate_carsi_service(name, catalog=catalog)
        service = AccessService.create(resource.production, resource.access_url)
    elif method == 'manual':
        if not url.strip():
            raise ConfigurationError('Manual Service requires a public HTTP(S) URL')
        service = AccessService.create(name.strip(), url.strip(), access_method='manual')
    elif method != 'unresolved':
        raise ConfigurationError('Choose CARSI, Manual or Unresolved')
    if service:
        previous = next((s for s in services if s.name.casefold() == service.name.casefold()), None)
        if previous:
            if ((previous.name, previous.access_method) != (service.name, service.access_method)
                    or (service.access_method == 'manual' and previous.access_url != service.access_url)):
                raise ConfigurationError('Local Service name has different settings; edit it in Settings first')
            service = previous
        else:
            services.append(service)
    journals = tuple(j.model_copy(update={'access_service_id': service.id if service else None}) if j.key == key else j
                     for j in snapshot.state.journals)
    # Resource requests may take time; recheck YAML at the write boundary.
    if load_settings(config_path).draft.monitor_revision != expected_monitor_revision:
        raise ContentChangedError('Monitor configuration changed; Reload')
    return compare_write_user_state(config_path, SettingsList(journals, snapshot.state.groups,
        snapshot.state.custom_labels, tuple(services), snapshot.state.conferences), snapshot.revision)
