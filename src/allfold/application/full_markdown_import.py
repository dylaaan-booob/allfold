"""Incremental, revision-bound portable Research Scope exchange.

Preview reads user state, verifies Journal identities, and may fill shared remote
caches. Only Confirm writes the receiving configuration's user scope.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from allfold.application.carsi_catalog import get_carsi_catalog, validate_carsi_service, CatalogError
from allfold.application.journal_lookup import search_journals, normalized_title
from allfold.application.journal_resolver import resolve_journal
from allfold.config import ConfigurationError, JournalConfig, AccessService, SettingsList, normalize_journal_issn
from allfold.persistence.user_state import ContentRevision
from allfold.persistence.user_state import (
    read_user_state, compare_write_user_state, application_data_dir, validate_user_state,
)
from allfold.providers.openalex import OpenAlexError

MAX_MARKDOWN_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ScopeRow:
    index: int
    supplied: dict
    candidates: tuple[dict, ...]
    journal: JournalConfig | None
    status: str
    service_status: str
    messages: tuple[str, ...] = ()
    resolution: object | None = None


@dataclass(frozen=True)
class ResearchScopePreview:
    config_path: Path
    revision: ContentRevision
    proposed: SettingsList
    rows: tuple[ScopeRow, ...]
    services: tuple[dict, ...]
    changes: tuple[str, ...]


def _cells(line):
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def _parse(contents):
    sections = {'journals': [], 'groups': [], 'custom labels': [], 'access services': []}
    section, header = 'journals', None
    for line in contents.lstrip('\ufeff').splitlines():
        text = line.strip()
        if text.startswith('#'):
            heading = text.lstrip('#').strip().casefold()
            section = heading if heading in sections else ('journals' if text.startswith('# ') else heading)
            header = None
            continue
        if not text or text.startswith('<!--'):
            continue
        if section not in sections:
            continue
        if '|' in text:
            cells = _cells(text)
            if all(re.fullmatch(r':?-+:?', cell) for cell in cells):
                continue
            if header is None:
                header = [cell.casefold() for cell in cells]
                aliases = {'name': 'journal', 'title': 'journal', 'e-issn': 'eissn', 'labels': 'label',
                           'custom labels': 'label', 'access service': 'service', 'access service id': 'service id', 'url': 'access url',
                           'method': 'access method'}
                header = [aliases.get(key, key) for key in header]
                if len(set(header)) != len(header):
                    raise ConfigurationError('Duplicate Markdown table columns')
                continue
            if len(cells) != len(header):
                raise ConfigurationError('Markdown table row has a different number of columns')
            sections[section].append(dict(zip(header, cells)))
        elif text.startswith(('- ', '* ', '+ ')):
            key = {'journals': 'journal', 'groups': 'group', 'custom labels': 'label', 'access services': 'service'}[section]
            sections[section].append({key: text[2:].strip()})
    return sections


def _identity(list_path, row, *, client):
    name = row.get('journal', '').strip()
    identifiers = [normalize_journal_issn(row[key]) for key in ('issn', 'eissn') if row.get(key)]
    query = identifiers[0] if identifiers else name
    if not query:
        raise ValueError('Provide a Journal name or ISSN/eISSN')
    candidates = search_journals(list_path, query, client=client, limit=None)
    if identifiers:
        candidates = [candidate for candidate in candidates if set(identifiers).issubset(
            candidate.get('identifiers') or {candidate['issn'], candidate['eissn']})]
    exact = [candidate for candidate in candidates if not name or normalized_title(name) in {
        normalized_title(candidate['name']), *(normalized_title(s['title']) for s in candidate['sources'])}]
    selected = exact[0] if len(exact) == 1 and not exact[0].get('identity_conflict') else None
    return candidates, selected


def _service(source, existing, catalog):
    name, method = source.get('service', '').strip(), source.get('access method', 'carsi').strip().lower() or 'carsi'
    if not name:
        return None, 'unresolved', 'No Service supplied'
    url = source.get('access url', '').strip() or None
    if method == 'carsi':
        resource = validate_carsi_service(name, catalog=catalog())
        # New Services use the official URL; a shared file cannot inject a
        # credential URL under a trusted production name.
        url = resource.access_url
    elif method == 'manual':
        if not url:
            raise ValueError('Manual Service requires a public HTTP(S) access URL')
    else:
        raise ValueError('Access Method must be carsi or manual')
    candidate = AccessService.create(name, url, access_method=method)
    same_name = next((service for service in existing if service.name.casefold() == name.casefold()), None)
    if same_name is not None:
        if ((same_name.name, same_name.access_method) != (name, method)
                or (method == 'manual' and same_name.access_url != url)):
            raise ValueError('Same Service name has different local settings; preserved local Service')
        return same_name, 'verified', 'Reused local Service'
    return candidate, 'verified', 'Validated Service'


def preview_research_scope(config_path: Path, list_path: Path, contents: str, *, filename: str,
                           choices: dict | None = None, query_gokb=False, client=None, transport=None):
    if not filename.lower().endswith('.md') or Path(filename).name != filename:
        raise ConfigurationError('Choose a UTF-8 .md file')
    if not contents.strip() or len(contents.encode('utf-8')) > MAX_MARKDOWN_BYTES or '\x00' in contents:
        raise ConfigurationError('Markdown is empty, contains NUL, or exceeds 1 MiB')
    choices = choices or {}
    snapshot = read_user_state(config_path, allow_missing=True)
    parsed = _parse(contents)
    if not any(parsed.values()):
        raise ConfigurationError('No recognized Journal list or scope tables found')
    journals, services = list(snapshot.state.journals), list(snapshot.state.access_services)
    groups, labels = list(snapshot.state.groups), list(snapshot.state.custom_labels)
    reports, service_reports, changes = [], [], []
    catalog_value = None
    def catalog():
        nonlocal catalog_value
        if catalog_value is None:
            catalog_value = get_carsi_catalog(application_data_dir(config_path) / 'resources.sqlite', transport=transport)
        return catalog_value
    definitions = {}
    for index, definition in enumerate(parsed['access services']):
        key = definition.get('service id') or definition.get('service', '')
        if not key or key in definitions:
            raise ConfigurationError('Duplicate or missing Service definition')
        definitions[key] = definition
        try:
            service, status, detail = _service(definition, services, catalog)
            if service and all(s.id != service.id for s in services):
                services.append(service)
            service_reports.append(dict(name=definition.get('service', ''), status=status, message=detail))
        except (ValueError, CatalogError) as error:
            service_reports.append(dict(name=definition.get('service', ''), status='invalid', message=str(error)))
    # Independent registries are portable, including entries without members.
    for target, source, key, insensitive in ((groups, parsed['groups'], 'group', True), (labels, parsed['custom labels'], 'label', False)):
        for row in source:
            value = row.get(key, '').strip()
            if value and not any((old.casefold() == value.casefold()) if insensitive else old == value for old in target):
                target.append(value)
    for index, supplied in enumerate(parsed['journals']):
        row = dict(supplied)
        choice = choices.get(str(index), {})
        if not isinstance(choice, dict):
            raise ConfigurationError('Invalid Import choices')
        for field in ('journal', 'issn', 'eissn', 'service', 'access url', 'access method'):
            if field in choice:
                row[field] = str(choice[field])
        messages, candidates, journal, status, service_status, resolution = [], [], None, 'unresolved', 'unresolved', None
        try:
            if choice.get('skip'):
                reports.append(ScopeRow(index, row, (), None, 'skip', 'unresolved', ('Skipped by user',)))
                continue
            supplied_ids = {normalize_journal_issn(row[field]) for field in ('issn', 'eissn') if row.get(field)}
            overlaps = [old for old in journals if supplied_ids & set(old.identifiers)]
            if overlaps:
                status = 'conflict' if len(overlaps) > 1 else 'skip'
                journal = overlaps[0] if len(overlaps) == 1 else None
                message = ('Identifiers overlap multiple saved Journals; correct the identity' if len(overlaps) > 1
                           else 'Existing identity; name, Group, Labels and Service preserved' if overlaps
                           else 'Skipped by user')
                reports.append(ScopeRow(index, row, (), journal, status, 'preserved' if overlaps else 'unresolved', (message,)))
                continue
            candidates, selected = _identity(list_path, row, client=client)
            if choice.get('candidate') is not None:
                identity = choice['candidate']
                if not isinstance(identity, dict) or set(identity) != {'issn', 'eissn'}:
                    raise ValueError('Selected identity must include the ISSN/eISSN pair')
                matching = [item for item in candidates if (item['issn'], item['eissn']) ==
                            (identity['issn'], identity['eissn'])]
                if len(matching) != 1:
                    raise ValueError('Selected identity is no longer a candidate')
                selected = matching[0]
            if selected:
                titles = {normalized_title(selected['name']), *(normalized_title(s['title']) for s in selected['sources'])}
                name = row.get('journal', '')
                preserve_supplied_identity = choice.get('candidate') is None and bool(row.get('issn') or row.get('eissn'))
                journal = JournalConfig(name=name if normalized_title(name) in titles else selected['name'],
                                        issn=(row.get('issn') or None) if preserve_supplied_identity else selected['issn'],
                                        eissn=(row.get('eissn') or None) if preserve_supplied_identity else selected['eissn'])
                overlaps = [old for old in journals if set(journal.identifiers) & set(old.identifiers)]
                if overlaps:
                    status = 'conflict' if len(overlaps) > 1 else 'skip'
                    messages.append('Identifiers overlap multiple saved Journals; correct the identity' if len(overlaps) > 1
                                    else 'Existing identity; name, Group, Labels and Service preserved')
                elif choice.get('skip'):
                    status = 'skip'
                    messages.append('Skipped by user')
                else:
                    group = row.get('group', '').strip() or None
                    assigned = tuple(value.strip() for value in row.get('label', '').split(';') if value.strip())
                    definition = definitions.get(row.get('service id', ''), definitions.get(row.get('service', ''), row))
                    if row.get('service id') and row['service id'] not in definitions:
                        messages.append('Unknown foreign Service ID; never reused as local identity')
                    # Explicit corrections supersede a legacy Service definition.
                    if any(field in choice for field in ('service', 'access url', 'access method')):
                        definition = row
                    try:
                        service, service_status, detail = _service(definition, services, catalog)
                        messages.append(detail)
                    except (ValueError, CatalogError) as error:
                        service, service_status = None, 'invalid'
                        messages.append(str(error))
                    if not service and query_gokb and not choice.get('unresolved'):
                        try:
                            resolution = resolve_journal(config_path, journal, transport=transport)
                            if resolution.unique_candidate:
                                candidate = resolution.unique_candidate
                                service, service_status, _ = _service({'service': candidate.production}, services, catalog)
                            messages.append(f'Resolver: {resolution.status}')
                        except (ConfigurationError, ValueError, OSError) as error:
                            messages.append(f'Resolver unavailable: {error}')
                    elif not service:
                        messages.append('Unresolved by user choice' if choice.get('unresolved') else 'Optional GOKB query pending')
                    if service and all(s.id != service.id for s in services):
                        services.append(service)
                    if group and group.casefold() not in {g.casefold() for g in groups}:
                        groups.append(group)
                    group = next((g for g in groups if group and g.casefold() == group.casefold()), None)
                    for value in assigned:
                        if value not in labels:
                            labels.append(value)
                    journal = journal.model_copy(update=dict(group=group, labels=assigned, access_service_id=service.id if service else None))
                    journals.append(journal)
                    status = 'add'
                    changes.append(f'Add Journal: {journal.name} ({journal.key}); Service {service.name if service else "Unresolved"}')
            else:
                messages.append('Choose a candidate or correct the name/identifiers and Preview again')
        except (ValueError, ConfigurationError, OpenAlexError) as error:
            messages.append(str(error))
        reports.append(ScopeRow(index, row, tuple(candidates), journal, status, service_status, tuple(messages), resolution))
    proposed = validate_user_state(SettingsList(tuple(journals), tuple(groups), tuple(labels), tuple(services)))
    changes.extend(f'Add Group: {name}' for name in groups if name not in snapshot.state.groups)
    changes.extend(f'Add Label: {name}' for name in labels if name not in snapshot.state.custom_labels)
    previous_ids = {service.id for service in snapshot.state.access_services}
    changes.extend(f'Add Service: {service.name} ({service.access_method}); {service.access_url or "(no URL)"}'
                   for service in services if service.id not in previous_ids)
    return ResearchScopePreview(config_path.resolve(), snapshot.revision, proposed, tuple(reports), tuple(service_reports), tuple(changes))


def confirm_research_scope(preview: ResearchScopePreview, *, before_write=None):
    if before_write:
        before_write()
    return compare_write_user_state(preview.config_path, preview.proposed, preview.revision)


def export_user_data(config_path: Path) -> str:
    state = read_user_state(config_path).state
    services = {service.id: service.name for service in state.access_services}
    output = '# Allfold User Data\n\n## Journals\n\n| Journal | ISSN | eISSN | Group | Label | Service |\n| --- | --- | --- | --- | --- | --- |\n'
    output += ''.join(f'| {j.name} | {j.issn or ""} | {j.eissn or ""} | {j.group or ""} | {"; ".join(j.labels)} | {services.get(j.access_service_id, "")} |\n' for j in state.journals)
    for title, key, values in (('Groups', 'Group', state.groups), ('Custom Labels', 'Label', state.custom_labels)):
        output += f'\n## {title}\n\n| {key} |\n| --- |\n' + ''.join(f'| {value} |\n' for value in values)
    output += '\n## Access Services\n\n| Service | Access URL | Access Method |\n| --- | --- | --- |\n'
    output += ''.join(f'| {s.name} | {s.access_url or ""} | {s.access_method} |\n' for s in state.access_services)
    return output
