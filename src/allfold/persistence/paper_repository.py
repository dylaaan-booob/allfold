"""Explicit, independent SQLite Paper repository; production wiring belongs to WF02."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID, uuid4

from allfold.canonicalize import normalize_abstract
from allfold.identifiers import normalize_external_id, strong_identifiers
from allfold.models import ExternalIds
from allfold.persistence.library_database import (
    LibraryBusyError, LibraryCorruptError, LibraryDatabase, LibraryError, LibraryExistsError,
    LibraryMissingError, UnsafeLibraryPath, UnsupportedLibrarySchema,
)
from allfold.persistence.library_models import (
    BodyReference, CreationResult, DirectIdentity, MetadataDelta, PaperMetadata, PaperRecord,
    PreprintResult, WriteToken,
)


class IdentityConflict(LibraryError):
    """Direct identities have different saved owners; no implicit merge is allowed."""


class StaleWriteError(LibraryError):
    """Workspace, Paper or operation authority no longer matches."""


class PaperNotFoundError(LibraryError):
    pass


class InvalidPaperState(LibraryError):
    """An explicit local operation does not apply to the current content state."""


__all__ = [
    "BodyReference", "CreationResult", "DirectIdentity", "IdentityConflict", "InvalidPaperState",
    "LibraryBusyError", "LibraryCorruptError", "LibraryError", "LibraryExistsError", "LibraryMissingError",
    "MetadataDelta", "PaperMetadata", "PaperNotFoundError", "PaperRecord", "PaperRepository",
    "PreprintResult", "StaleWriteError", "UnsafeLibraryPath", "UnsupportedLibrarySchema", "WriteToken",
]


def _identities(direct_ids: ExternalIds) -> tuple[DirectIdentity, ...]:
    direct_ids = ExternalIds.model_validate(
        direct_ids.model_dump(exclude_none=True) if isinstance(direct_ids, ExternalIds) else direct_ids)
    identities = tuple(DirectIdentity(*pair) for pair in sorted(strong_identifiers(direct_ids)))
    if not identities:
        raise ValueError("At least one reliable direct Paper identity is required")
    return identities


def _extra_identities(values):
    identities = set()
    for identity in values:
        if not isinstance(identity, DirectIdentity):
            raise ValueError("Additional direct identities must be DirectIdentity values")
        value = normalize_external_id(identity.namespace, identity.value)
        if value is None:
            raise ValueError("Invalid reliable additional direct identity")
        identities.add(DirectIdentity(identity.namespace, value))
    return tuple(sorted(identities))


class PaperRepository:
    def __init__(self, database: LibraryDatabase):
        self._database = database
        self.workspace_id = database.workspace_id

    @classmethod
    def create(cls, workspace: Path, *, timeout: float = 2) -> PaperRepository:
        """Create only in an existing directory and only when the library is absent."""
        return cls(LibraryDatabase(workspace, create=True, timeout=timeout))

    @classmethod
    def open(cls, workspace: Path, *, expected_workspace_id: UUID | None = None,
             timeout: float = 2) -> PaperRepository:
        repository = cls(LibraryDatabase(workspace, create=False, timeout=timeout))
        if expected_workspace_id is not None and repository.workspace_id != expected_workspace_id:
            repository.close()
            raise StaleWriteError("Different Workspace identity")
        return repository

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._database.close()

    def _read(self, connection, paper_id: UUID) -> PaperRecord:
        row = connection.execute("SELECT * FROM paper_core WHERE paper_id = ?", (str(paper_id),)).fetchone()
        if row is None:
            raise PaperNotFoundError(str(paper_id))
        identities = tuple(DirectIdentity(*identity) for identity in connection.execute(
            "SELECT namespace, normalized_value FROM paper_identities WHERE paper_id = ? ORDER BY namespace, normalized_value",
            (str(paper_id),)))
        metadata = connection.execute("SELECT payload, abstract_generation FROM paper_metadata WHERE paper_id = ?",
                                      (str(paper_id),)).fetchone()
        body = connection.execute("SELECT relative_path, source_url, size_bytes FROM paper_body WHERE paper_id = ?",
                                  (str(paper_id),)).fetchone()
        projection = connection.execute("SELECT primary_namespace, primary_value, revision FROM paper_projection WHERE paper_id = ?",
                                        (str(paper_id),)).fetchone()
        if projection is None:
            raise LibraryCorruptError("Paper projection is missing")
        try:
            return PaperRecord(self.workspace_id, UUID(row["paper_id"]), bool(row["excluded"]),
                               row["metadata_generation"], row["operation_generation"],
                               metadata["abstract_generation"] if metadata else None,
                               row["body_generation"], identities,
                               PaperMetadata.model_validate_json(metadata["payload"]) if metadata else None,
                               BodyReference.model_validate(dict(body)) if body else None,
                               DirectIdentity(projection[0], projection[1]) if projection[0] else None,
                               projection["revision"])
        except ValueError as error:
            raise LibraryCorruptError("Invalid saved Paper") from error

    def get(self, paper_id: UUID) -> PaperRecord:
        with self._database.transaction() as connection:
            return self._read(connection, paper_id)

    @property
    def revision(self) -> int:
        with self._database.transaction() as connection:
            return connection.execute("SELECT revision FROM library_state WHERE singleton = 1").fetchone()[0]

    def snapshot(self) -> tuple[int, tuple[PaperRecord, ...]]:
        """One coherent UI snapshot; qualification tokens are not revisions."""
        with self._database.transaction() as connection:
            revision = connection.execute("SELECT revision FROM library_state WHERE singleton = 1").fetchone()[0]
            papers = tuple(self._read(connection, UUID(row[0])) for row in connection.execute(
                "SELECT paper_id FROM paper_core ORDER BY rowid"))
            return revision, papers

    def list_papers(self) -> tuple[PaperRecord, ...]:
        return self.snapshot()[1]

    def _changed(self, connection, paper_id):
        connection.execute("UPDATE library_state SET revision = revision + 1 WHERE singleton = 1")
        connection.execute("UPDATE paper_projection SET revision = revision + 1 WHERE paper_id = ?", (str(paper_id),))

    @staticmethod
    def _new_metadata(metadata):
        if metadata.discovered_at is None:
            return metadata.model_copy(update={"discovered_at": datetime.now(timezone.utc)})
        return metadata

    @staticmethod
    def _primary(direct_ids, identities):
        doi = normalize_external_id("doi", direct_ids.model_dump(exclude_none=True).get("doi"))
        if doi:
            return DirectIdentity("doi", doi)
        priority = ("pmid", "pmcid", "wos", "openalex", "europe_pmc", "arxiv", "biorxiv", "medrxiv")
        return min(identities, key=lambda item: (priority.index(item.namespace), item.value))

    def _match(self, connection, identities):
        owners = {row[0] for identity in identities for row in connection.execute(
            "SELECT paper_id FROM paper_identities WHERE namespace = ? AND normalized_value = ?",
            (identity.namespace, identity.value))}
        if len(owners) > 1:
            raise IdentityConflict(f"Direct identities belong to different Papers: {', '.join(sorted(owners))}")
        return UUID(next(iter(owners))) if owners else None

    def match(self, direct_ids: ExternalIds) -> PaperRecord | None:
        identities = _identities(direct_ids)
        with self._database.transaction() as connection:
            owner = self._match(connection, identities)
            return self._read(connection, owner) if owner else None

    def _add_identities(self, connection, paper_id, identities):
        owner = self._match(connection, identities)
        if owner is not None and owner != paper_id:
            raise IdentityConflict("A direct identity already belongs to another Paper")
        connection.executemany("INSERT OR IGNORE INTO paper_identities VALUES (?, ?, ?)",
                               [(identity.namespace, identity.value, str(paper_id)) for identity in identities])

    def create_or_match(self, workspace_id: UUID, *, direct_ids: ExternalIds,
                        metadata: PaperMetadata, additional_identities: tuple[DirectIdentity, ...] = ()) -> CreationResult:
        identities = tuple(sorted(set(_identities(direct_ids) + _extra_identities(additional_identities))))
        metadata = self._new_metadata(PaperMetadata.model_validate(metadata))
        with self._database.transaction(write=True) as connection:
            if workspace_id != self.workspace_id:
                raise StaleWriteError("Different Workspace identity")
            owner = self._match(connection, identities)
            if owner is not None:
                return CreationResult(self._read(connection, owner), False)
            paper_id = uuid4()
            connection.execute("INSERT INTO paper_core (paper_id) VALUES (?)", (str(paper_id),))
            self._add_identities(connection, paper_id, identities)
            primary = self._primary(direct_ids, identities)
            connection.execute("INSERT INTO paper_projection VALUES (?, ?, ?, 1)",
                               (str(paper_id), primary.namespace, primary.value))
            connection.execute("UPDATE library_state SET revision = revision + 1 WHERE singleton = 1")
            connection.execute("INSERT INTO paper_metadata (paper_id, payload) VALUES (?, ?)",
                               (str(paper_id), metadata.model_dump_json()))
            return CreationResult(self._read(connection, paper_id), True)

    def _require_token(self, connection, token: WriteToken, *, automatic=False) -> PaperRecord:
        if token.workspace_id != self.workspace_id:
            raise StaleWriteError("Different Workspace identity")
        paper = self._read(connection, token.paper_id)
        if (paper.metadata_generation != token.metadata_generation
                or paper.operation_generation != token.operation_generation):
            raise StaleWriteError("Paper metadata or operation generation changed")
        if automatic and (paper.excluded or paper.metadata is None):
            raise StaleWriteError("Automatic writes require unexcluded, complete metadata")
        return paper

    def merge_metadata(self, token: WriteToken, delta: MetadataDelta, *,
                       direct_ids: ExternalIds | None = None) -> PaperRecord:
        delta = MetadataDelta.model_validate(delta)
        identities = _identities(direct_ids) if direct_ids is not None else ()
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token, automatic=True)
            if identities:
                self._add_identities(connection, paper.id, identities)
            changes = {
                "ordinary_dates": paper.metadata.ordinary_dates + delta.ordinary_dates,
                "preprints": paper.metadata.preprints + delta.preprints,
                "sources": tuple(dict.fromkeys(paper.metadata.sources + delta.sources)),
                "preprint_evidence": tuple(dict.fromkeys(paper.metadata.preprint_evidence + delta.preprint_evidence)),
                "preprint_relations": tuple(dict.fromkeys(paper.metadata.preprint_relations + delta.preprint_relations)),
                "first_public_at": paper.metadata.first_public_at or delta.first_public_at,
            }
            if (delta.abstract and not paper.metadata.abstract
                    and paper.abstract_generation == token.abstract_generation):
                changes["abstract"] = normalize_abstract(delta.abstract)
            metadata = PaperMetadata.model_validate(paper.metadata.model_dump() | changes)
            connection.execute("UPDATE paper_metadata SET payload = ? WHERE paper_id = ?",
                               (metadata.model_dump_json(), str(paper.id)))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def edit_metadata(self, token: WriteToken, changes: dict) -> PaperRecord:
        """Apply explicitly named local edits to the latest payload, including in the recycle bin."""
        editable = {"title", "journal", "conference", "publication_type", "publication_date", "abstract",
                    "authors", "author_keywords", "journal_issns", "indexed_terms", "notes"}
        if not changes.keys() <= editable:
            raise ValueError("Local edit contains non-editable metadata fields")
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token)
            if paper.metadata is None:
                raise InvalidPaperState("An identity placeholder has no editable metadata")
            if "abstract" in changes and token.abstract_generation != paper.abstract_generation:
                raise StaleWriteError("Abstract was manually edited after this token")
            metadata = PaperMetadata.model_validate(paper.metadata.model_dump() | changes)
            connection.execute("UPDATE paper_metadata SET payload = ?, abstract_generation = abstract_generation + ? WHERE paper_id = ?",
                               (metadata.model_dump_json(), int("abstract" in changes), str(paper.id)))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def exclude(self, token: WriteToken) -> PaperRecord:
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token)
            if not paper.excluded:
                connection.execute("UPDATE paper_core SET excluded = 1, operation_generation = operation_generation + 1 WHERE paper_id = ?",
                                   (str(paper.id),))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def restore(self, token: WriteToken) -> PaperRecord:
        """Restore a full record; clearing exclusion on a placeholder uses unexclude."""
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token)
            if paper.metadata is None:
                raise InvalidPaperState("Use unexclude for a cleared identity placeholder")
            if paper.excluded:
                connection.execute("UPDATE paper_core SET excluded = 0, operation_generation = operation_generation + 1 WHERE paper_id = ?",
                                   (str(paper.id),))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def clear_metadata(self, token: WriteToken) -> PaperRecord:
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token)
            if not paper.excluded:
                raise InvalidPaperState("Metadata can only be cleared in the recycle bin")
            if paper.metadata is not None:
                connection.execute("DELETE FROM paper_metadata WHERE paper_id = ?", (str(paper.id),))
                connection.execute("UPDATE paper_core SET metadata_generation = metadata_generation + 1, operation_generation = operation_generation + 1 WHERE paper_id = ?",
                                   (str(paper.id),))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def unexclude(self, token: WriteToken) -> PaperRecord:
        """Release a cleared identity placeholder, without reconstructing its content."""
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token)
            if paper.metadata is not None:
                raise InvalidPaperState("Use restore for a complete Paper")
            if paper.excluded:
                connection.execute("UPDATE paper_core SET excluded = 0, operation_generation = operation_generation + 1 WHERE paper_id = ?",
                                   (str(paper.id),))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def rebuild_from_run(self, token: WriteToken, *, direct_ids: ExternalIds,
                         metadata: PaperMetadata, additional_identities: tuple[DirectIdentity, ...] = ()) -> PaperRecord:
        """Rebuild only a released placeholder from a caller-verified, new Run result."""
        identities = tuple(sorted(set(_identities(direct_ids) + _extra_identities(additional_identities))))
        metadata = self._new_metadata(PaperMetadata.model_validate(metadata))
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token)
            if paper.excluded or paper.metadata is not None:
                raise InvalidPaperState("Rebuild requires cleared metadata and released exclusion")
            if self._match(connection, identities) != paper.id:
                raise IdentityConflict("New Run result must directly identify this placeholder")
            self._add_identities(connection, paper.id, identities)
            connection.execute("INSERT INTO paper_metadata (paper_id, payload) VALUES (?, ?)",
                               (str(paper.id), metadata.model_dump_json()))
            connection.execute("UPDATE paper_core SET metadata_generation = metadata_generation + 1, operation_generation = operation_generation + 1 WHERE paper_id = ?",
                               (str(paper.id),))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def complete_body(self, token: WriteToken, body: BodyReference) -> PaperRecord:
        """Associate a newly completed result only while content and body authority remain valid."""
        body = BodyReference.model_validate(body)
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token, automatic=True)
            if token.body_generation != paper.body_generation:
                raise StaleWriteError("Body association changed after this operation started")
            connection.execute("""INSERT INTO paper_body VALUES (?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET relative_path = excluded.relative_path,
                source_url = excluded.source_url, size_bytes = excluded.size_bytes""",
                               (str(paper.id), body.relative_path, body.source_url, body.size_bytes))
            connection.execute("UPDATE paper_core SET body_generation = body_generation + 1 WHERE paper_id = ?",
                               (str(paper.id),))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def clear_body(self, token: WriteToken) -> PaperRecord:
        """Explicit local unlink, allowed with excluded or absent metadata; touches no file."""
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token)
            if token.body_generation != paper.body_generation:
                raise StaleWriteError("Body association changed after this local operation started")
            connection.execute("DELETE FROM paper_body WHERE paper_id = ?", (str(paper.id),))
            # Also revoke a pending result when there is currently no body.
            connection.execute("UPDATE paper_core SET body_generation = body_generation + 1 WHERE paper_id = ?",
                               (str(paper.id),))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)
