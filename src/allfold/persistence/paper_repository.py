"""SQLite Paper identity, metadata, collection qualification and short writes."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import re
from uuid import UUID, uuid4

from allfold.abstract_text import normalize_abstract_text
from allfold.identifiers import normalize_external_id, strong_identifiers
from allfold.models import ExternalIds
from allfold.persistence.library_database import (
    LibraryBusyError, LibraryCorruptError, LibraryDatabase, LibraryError, LibraryExistsError,
    LibraryMissingError, UnsafeLibraryPath, UnsupportedLibrarySchema,
)
from allfold.persistence.library_models import (
    BodyReference, CollectionAdmission, CollectionBranch, CollectionRecord, CollectionToken,
    CreationResult, DirectIdentity, MetadataDelta, PaperMetadata, PaperRecord, PreprintResult, WriteToken,
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
    "CollectionAdmission", "CollectionBranch", "CollectionRecord", "CollectionToken",
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
        collection = connection.execute("SELECT * FROM paper_collection WHERE paper_id = ?", (str(paper_id),)).fetchone()
        try:
            collection_record = None
            if collection is not None:
                if collection["metadata_generation"] != row["metadata_generation"]:
                    raise ValueError("Collection belongs to another metadata lifetime")
                branches = tuple(CollectionBranch(branch["name"], branch["state"], branch["last_sequence"], branch["reason"])
                                 for branch in connection.execute(
                                     "SELECT * FROM paper_collection_branch WHERE paper_id = ? ORDER BY name", (str(paper_id),)))
                collection_record = CollectionRecord(collection["metadata_generation"], collection["attempt"],
                                                     UUID(collection["lifecycle_id"]), collection["status"],
                                                     bool(collection["cancel_requested"]), collection["reason"], branches,
                                                     WriteToken(self.workspace_id, paper_id, collection["metadata_generation"],
                                                                collection["operation_generation"], collection["abstract_generation"],
                                                                collection["body_generation"]))
            return PaperRecord(self.workspace_id, UUID(row["paper_id"]), bool(row["excluded"]),
                               row["metadata_generation"], row["operation_generation"],
                               metadata["abstract_generation"] if metadata else None,
                               row["body_generation"], identities,
                               PaperMetadata.model_validate_json(metadata["payload"]) if metadata else None,
                               BodyReference.model_validate(dict(body)) if body else None,
                               DirectIdentity(projection[0], projection[1]) if projection[0] else None,
                               projection["revision"], collection_record)
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

    def touch_projection(self, paper_id: UUID) -> PaperRecord:
        """Order a runtime occupancy change without changing content qualification.

        The runtime holds its Paper gate and captured resource identity through
        this commit and the corresponding reservation change.
        """
        with self._database.transaction(write=True) as connection:
            self._read(connection, paper_id)
            self._changed(connection, paper_id)
            return self._read(connection, paper_id)

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
            return self._create_or_match(connection, direct_ids, identities, metadata)

    def _create_or_match(self, connection, direct_ids, identities, metadata):
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

    @staticmethod
    def _collection_branches(branches):
        names = tuple(branches)
        if len(names) > 16 or any(not isinstance(name, str) or re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", name) is None for name in names):
            raise ValueError("Collection requires at most 16 bounded branch names")
        return tuple(sorted(set(names)))

    def _queue_collection(self, connection, paper, lifecycle_id, branches, *, created=False):
        attempt = paper.collection.attempt + 1 if paper.collection else 1
        connection.execute("""INSERT INTO paper_collection VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, NULL)
            ON CONFLICT(paper_id) DO UPDATE SET attempt = excluded.attempt, lifecycle_id = excluded.lifecycle_id,
            operation_generation = excluded.operation_generation, abstract_generation = excluded.abstract_generation,
            body_generation = excluded.body_generation, status = 'queued', cancel_requested = 0, reason = NULL""",
                           (str(paper.id), paper.metadata_generation, paper.operation_generation,
                            paper.abstract_generation, paper.body_generation, attempt, str(lifecycle_id)))
        saved = {branch.name: branch for branch in paper.collection.branches} if paper.collection else {}
        connection.execute("DELETE FROM paper_collection_branch WHERE paper_id = ?", (str(paper.id),))
        for name in branches:
            previous = saved.get(name)
            state = previous.state if previous and previous.state in {"completed", "skipped"} else "queued"
            connection.execute("INSERT INTO paper_collection_branch VALUES (?, ?, ?, 0, ?)",
                               (str(paper.id), name, state, previous.reason if state == "skipped" else None))
        self._changed(connection, paper.id)
        paper = self._read(connection, paper.id)
        return CollectionAdmission(paper, CollectionToken(paper.token, attempt, lifecycle_id), True, created)

    def admit_collection(self, workspace_id: UUID, *, lifecycle_id: UUID, branches: tuple[str, ...],
                         direct_ids: ExternalIds, metadata: PaperMetadata,
                         additional_identities: tuple[DirectIdentity, ...] = ()) -> CollectionAdmission:
        """Commit identity creation/matching and queued authority in one short transaction."""
        lifecycle_id = UUID(str(lifecycle_id))
        branches = self._collection_branches(branches)
        identities = tuple(sorted(set(_identities(direct_ids) + _extra_identities(additional_identities))))
        metadata = self._new_metadata(PaperMetadata.model_validate(metadata))
        with self._database.transaction(write=True) as connection:
            if workspace_id != self.workspace_id:
                raise StaleWriteError("Different Workspace identity")
            result = self._create_or_match(connection, direct_ids, identities, metadata)
            paper = result.paper
            if paper.excluded:
                return CollectionAdmission(paper, None, False, result.created)
            if paper.metadata is None:
                paper = self._rebuild(connection, paper, identities, metadata)
            if paper.collection is not None:
                token = CollectionToken(paper.collection.write, paper.collection.attempt, paper.collection.lifecycle_id) if paper.collection.active else None
                return CollectionAdmission(paper, token, False, result.created)
            return self._queue_collection(connection, paper, lifecycle_id, branches, created=result.created)

    def retry_collection(self, token: WriteToken, *, lifecycle_id: UUID,
                         branches: tuple[str, ...]) -> CollectionAdmission:
        """Explicit retry only; the application also holds its shared Paper occupation gate."""
        lifecycle_id = UUID(str(lifecycle_id))
        branches = self._collection_branches(branches)
        with self._database.transaction(write=True) as connection:
            paper = self._require_token(connection, token, automatic=True)
            if paper.collection is None or paper.collection.status not in {"failed", "cancelled"}:
                raise InvalidPaperState("Retry requires a settled failed or cancelled collection")
            if not {branch.name for branch in paper.collection.branches} <= set(branches):
                raise InvalidPaperState("Retry cannot discard captured collection branches")
            return self._queue_collection(connection, paper, lifecycle_id, branches)

    def _require_collection(self, connection, token: CollectionToken, *, settlement=False) -> PaperRecord:
        if not isinstance(token, CollectionToken) or token.workspace_id != self.workspace_id:
            raise StaleWriteError("Different Workspace or missing captured collection authority")
        paper = self._read(connection, token.paper_id)
        collection = paper.collection
        if (collection is None or collection.attempt != token.attempt or collection.lifecycle_id != token.lifecycle_id
                or collection.write != token.write):
            raise StaleWriteError("Collection attempt or lifecycle changed")
        if not settlement:
            self._require_token(connection, token.write, automatic=True)
            if collection.cancel_requested or not collection.active:
                raise StaleWriteError("Collection execution authority has ended")
        return paper

    def require_collection(self, token: CollectionToken) -> PaperRecord:
        """Recheck captured execution authority without renewing an old result's token."""
        with self._database.transaction() as connection:
            return self._require_collection(connection, token)

    def mark_collection_running(self, token: CollectionToken) -> PaperRecord:
        with self._database.transaction(write=True) as connection:
            paper = self._require_collection(connection, token)
            if paper.collection.status == "queued":
                connection.execute("UPDATE paper_collection SET status = 'running' WHERE paper_id = ?", (str(paper.id),))
                self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    @staticmethod
    def _collection_reason(reason):
        if reason is not None and (not isinstance(reason, str) or len(reason) > 240):
            raise ValueError("Collection reason must be at most 240 characters")
        return reason

    def commit_collection_branch(self, token: CollectionToken, branch: str, *, sequence: int,
                                 delta: MetadataDelta | None = None, outcome: str = "running",
                                 reason: str | None = None, direct_ids: ExternalIds | None = None) -> PaperRecord:
        """Commit a captured branch increment/result once; sequence is local to this attempt."""
        if type(sequence) is not int or sequence <= 0:
            raise ValueError("Branch sequence must be a positive integer")
        if outcome not in {"running", "completed", "skipped", "failed", "cancelled"}:
            raise ValueError("Invalid branch outcome")
        reason = self._collection_reason(reason)
        if outcome == "skipped" and not reason:
            raise ValueError("A skipped branch requires an applicability reason")
        delta = MetadataDelta.model_validate(delta) if delta is not None else None
        identities = _identities(direct_ids) if direct_ids is not None else ()
        settlement = outcome in {"failed", "cancelled"} and delta is None and not identities
        with self._database.transaction(write=True) as connection:
            paper = self._require_collection(connection, token, settlement=True)
            saved = next((item for item in paper.collection.branches if item.name == branch), None)
            if saved is None:
                raise StaleWriteError("Branch was not captured at admission")
            if sequence <= saved.last_sequence:
                if not settlement:
                    self._require_token(connection, token.write, automatic=True)
                    if paper.collection.cancel_requested or paper.collection.status in {"failed", "cancelled"}:
                        raise StaleWriteError("Collection execution authority has ended")
                return paper
            if not settlement:
                self._require_collection(connection, token)
            if not paper.collection.active or saved.state in {"completed", "skipped", "failed", "cancelled"}:
                raise StaleWriteError("Collection branch already settled")
            if delta is not None or identities:
                self._merge_metadata(connection, paper, token.write, delta or MetadataDelta(), identities)
            connection.execute("""UPDATE paper_collection_branch SET state = ?, last_sequence = ?, reason = ?
                WHERE paper_id = ? AND name = ?""", (outcome, sequence, reason, str(paper.id), branch))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def request_collection_cancel(self, token: CollectionToken, *, reason: str | None = None) -> PaperRecord:
        """Invalidate execution now; queued/running continues to occupy the Paper through cleanup."""
        reason = self._collection_reason(reason)
        with self._database.transaction(write=True) as connection:
            paper = self._require_collection(connection, token, settlement=True)
            if paper.collection.active and not paper.collection.cancel_requested:
                connection.execute("UPDATE paper_collection SET cancel_requested = 1, reason = ? WHERE paper_id = ?",
                                   (reason, str(paper.id)))
                self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def finish_collection(self, token: CollectionToken, *, reason: str | None = None,
                          failed: bool = False) -> PaperRecord:
        """Aggregate only after the owner has joined all branch writes and real resource cleanup."""
        reason = self._collection_reason(reason)
        with self._database.transaction(write=True) as connection:
            paper = self._require_collection(connection, token, settlement=True)
            collection = paper.collection
            if not collection.active:
                return paper
            states = {branch.state for branch in collection.branches}
            if states & {"queued", "running"}:
                raise InvalidPaperState("Collection branches have not all settled")
            revoked = (collection.cancel_requested or paper.excluded
                       or paper.operation_generation != token.write.operation_generation)
            status = ("cancelled" if revoked else "failed" if failed or "failed" in states else
                      "cancelled" if "cancelled" in states else "completed")
            failure_reason = next((branch.reason for branch in collection.branches
                                   if branch.state in {"failed", "cancelled"} and branch.reason), None)
            connection.execute("UPDATE paper_collection SET status = ?, reason = ? WHERE paper_id = ?",
                               (status, reason or collection.reason or failure_reason, str(paper.id)))
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def interrupt_collections(self, lifecycle_id: UUID) -> tuple[UUID, ...]:
        """Explicit lifecycle initialization only: mark stale work failed, never replay it."""
        lifecycle_id = UUID(str(lifecycle_id))
        with self._database.transaction(write=True) as connection:
            ids = tuple(UUID(row[0]) for row in connection.execute(
                "SELECT paper_id FROM paper_collection WHERE lifecycle_id != ? AND status IN ('queued', 'running') ORDER BY paper_id",
                (str(lifecycle_id),)))
            for paper_id in ids:
                connection.execute("UPDATE paper_collection SET status = 'failed', reason = 'interrupted' WHERE paper_id = ?",
                                   (str(paper_id),))
                connection.execute("""UPDATE paper_collection_branch SET state = 'failed', reason = 'interrupted'
                    WHERE paper_id = ? AND state IN ('queued', 'running')""", (str(paper_id),))
                self._changed(connection, paper_id)
            return ids

    @staticmethod
    def _require_collection_idle(paper):
        if paper.collection is not None and paper.collection.active:
            raise InvalidPaperState("Collection owns this Paper until real cleanup settles")

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
            self._merge_metadata(connection, paper, token, delta, identities)
            self._changed(connection, paper.id)
            return self._read(connection, paper.id)

    def _merge_metadata(self, connection, paper, token, delta, identities):
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
            changes["abstract"] = normalize_abstract_text(delta.abstract)
        metadata = PaperMetadata.model_validate(paper.metadata.model_dump() | changes)
        connection.execute("UPDATE paper_metadata SET payload = ? WHERE paper_id = ?",
                           (metadata.model_dump_json(), str(paper.id)))

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
            self._require_collection_idle(paper)
            if paper.metadata is not None:
                connection.execute("DELETE FROM paper_collection WHERE paper_id = ?", (str(paper.id),))
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
            return self._rebuild(connection, paper, identities, metadata)

    def _rebuild(self, connection, paper, identities, metadata):
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
            self._require_collection_idle(paper)
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
