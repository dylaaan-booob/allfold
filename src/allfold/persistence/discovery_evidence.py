"""Compact Paper evidence handoff; no task queue or response cache."""
from contextlib import nullcontext
import os
import stat
from uuid import UUID

from allfold.models import DomainModel, ProviderWorkEvidence
from allfold.persistence.safe_write import workspace_operation_lock, workspace_text_directory


class DiscoveryScope(DomainModel):
    provider: str
    journal: str
    key: str
    issns: tuple[str, ...]
    from_date: str
    to_date: str


class DiscoveryEvidence(DomainModel):
    schema_version: int = 1
    scopes: tuple[DiscoveryScope, ...] = ()
    records: tuple[ProviderWorkEvidence, ...] = ()


def _read(lock, paper_id):
    name = str(UUID(str(paper_id))) + '.json'
    try:
        directory = os.open('Evidence', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=lock.directory)
    except FileNotFoundError:
        return DiscoveryEvidence(), None
    try:
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(descriptor, 'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError('Discovery evidence is not a regular file')
                text = handle.read().decode('utf-8')
        except FileNotFoundError:
            return DiscoveryEvidence(), None
        result = DiscoveryEvidence.model_validate_json(text)
        if result.schema_version != 1:
            raise ValueError('Unsupported discovery evidence schema; explicitly reset the Workspace')
        lock.verify()
        return result, text
    finally:
        os.close(directory)


def read_discovery_evidence(workspace, paper_id, *, operation_lock=None):
    with nullcontext(operation_lock) if operation_lock else workspace_operation_lock(workspace) as lock:
        return _read(lock, paper_id)[0]


def evidence_key(record):
    def facts(value):
        if isinstance(value, dict):
            return {key: facts(item) for key, item in value.items() if key != 'retrieved_at'}
        if isinstance(value, list):
            return [facts(item) for item in value]
        return value
    import json
    return json.dumps(facts(record.model_dump(mode='json')), sort_keys=True, ensure_ascii=False)


def append_discovery_evidence(lock, paper_id, records, scopes=()):
    previous, text = _read(lock, paper_id)
    combined = {evidence_key(record): record for record in previous.records}
    for record in records:
        combined.setdefault(evidence_key(record), record)
    updated = DiscoveryEvidence(records=tuple(combined[key] for key in sorted(combined)),
        scopes=tuple(sorted(set(previous.scopes + tuple(scopes)), key=lambda item: item.model_dump_json())))
    if updated == previous:
        return False
    name = str(UUID(str(paper_id))) + '.json'
    with workspace_text_directory(lock, 'Evidence') as directory:
        contents = updated.model_dump_json(indent=2) + '\n'
        if text is None:
            directory.create(name, contents)
        else:
            directory.replace(name, contents, expected_contents=text)
    return True
