"""WF01 contracts, using disposable Workspaces and real SQLite connections."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import permutations
from threading import Barrier
from uuid import uuid4

import pytest

from allfold.models import ExternalIds
from allfold.persistence.paper_repository import (
    BodyReference, IdentityConflict, InvalidPaperState, MetadataDelta, PaperMetadata,
    PaperNotFoundError, PaperRepository, PreprintResult, StaleWriteError,
)


def test_create_close_reopen_preserves_workspace_and_paper(tmp_path):
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    with PaperRepository.create(workspace) as library:
        workspace_id = library.workspace_id
        result = library.create_or_match(
            workspace_id,
            direct_ids=ExternalIds(doi="https://doi.org/10.1234/EXAMPLE"),
            metadata=PaperMetadata(title=" A real title ", notes="Keep my notes"),
        )
        paper = result.paper
        assert result.created
    with PaperRepository.open(workspace, expected_workspace_id=workspace_id) as reopened:
        assert reopened.workspace_id == workspace_id
        assert reopened.get(paper.id) == paper
        assert reopened.list_papers() == (paper,)
        assert paper.metadata.title == "A real title"
        assert paper.metadata.notes == "Keep my notes"
        assert {(identity.namespace, identity.value) for identity in paper.identities} == {
            ("doi", "10.1234/example"),
        }


@pytest.fixture
def library(tmp_path):
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        yield repository


def create(library, **ids):
    return library.create_or_match(library.workspace_id, direct_ids=ExternalIds(**(ids or {"doi": "10.1234/main"})),
                                   metadata=PaperMetadata(title="An article")).paper


@pytest.mark.parametrize("ids", [
    {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345/"}, {"wos": "wos:12345"},
    {"openalex": "https://openalex.org/W12345"}, {"pmcid": "pmc12345"},
    {"arxiv": "https://arxiv.org/abs/2401.12345v2"}, {"europe_pmc": "med:12345"},
    {"biorxiv": "10.1101/2026.01.01.123456"}, {"medrxiv": "10.1101/2026.01.01.123457"},
])
def test_supported_direct_identity_can_create_without_doi(library, ids):
    paper = create(library, **ids)
    assert library.match(ExternalIds(**ids)).id == paper.id


@pytest.mark.parametrize("ids", [{}, {"crossref": "unknown"}, {"doi": "not-a-doi"}, {"dblp": "retired", "pmid": "123"}])
def test_missing_or_retired_reliable_identity_cannot_create(library, ids):
    with pytest.raises(ValueError):
        library.create_or_match(library.workspace_id, direct_ids=ExternalIds(**ids),
                                metadata=PaperMetadata(title="A title"))
    assert library.list_papers() == ()


@pytest.mark.parametrize("title", [None, "", " \n\t"])
def test_invalid_title_cannot_create(library, title):
    with pytest.raises(ValueError):
        library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                metadata={"title": title})
    assert library.list_papers() == ()


def test_title_and_unknown_ids_never_merge_papers(library):
    first = create(library, pmid="123")
    second = create(library, pmid="456")
    assert first.id != second.id


def test_multi_identity_conflict_has_no_partial_rows_or_new_index(library):
    first, second = create(library, pmid="123"), create(library, doi="10.1234/other")
    with pytest.raises(IdentityConflict):
        create(library, pmid="123", doi="10.1234/other", wos="WOS:999")
    assert library.match(ExternalIds(wos="WOS:999")) is None
    assert set(library.list_papers()) == {first, second}


def test_concurrent_normalized_identity_creation_has_one_uuid(library, tmp_path):
    workspace_id = library.workspace_id
    barrier = Barrier(4)

    def worker(spelling):
        with PaperRepository.open(tmp_path / "Workspace") as connection:
            barrier.wait(timeout=5)
            return connection.create_or_match(workspace_id, direct_ids=ExternalIds(doi=spelling),
                                               metadata=PaperMetadata(title="Concurrent article"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = tuple(pool.map(worker, ("10.1234/SAME", "https://doi.org/10.1234/same",
                                          "doi:10.1234/Same", "10.1234/same")))
    assert len({result.paper.id for result in results}) == 1
    assert sum(result.created for result in results) == 1
    assert len(library.list_papers()) == 1


def test_wrong_workspace_does_not_create(library, tmp_path):
    with pytest.raises(StaleWriteError):
        library.create_or_match(uuid4(), direct_ids=ExternalIds(pmid="123"), metadata=PaperMetadata(title="Title"))
    assert library.list_papers() == ()
    with pytest.raises(StaleWriteError):
        PaperRepository.open(tmp_path / "Workspace", expected_workspace_id=uuid4())


def test_exclusion_clear_and_rebuild_keep_identity_and_invalidate_old_writes(library):
    from allfold.persistence.paper_repository import MetadataDelta

    paper = create(library, doi="10.1234/main", pmid="123")
    excluded = library.exclude(paper.token)
    with pytest.raises(StaleWriteError):
        library.merge_metadata(paper.token, MetadataDelta(abstract="Late result"))
    # Even a forged/current generation cannot bypass exclusion.
    with pytest.raises(StaleWriteError):
        library.merge_metadata(excluded.token, MetadataDelta(abstract="Late result"))
    cleared = library.clear_metadata(excluded.token)
    assert cleared.metadata is None
    assert cleared.excluded
    assert cleared.identities == paper.identities
    assert library.match(ExternalIds(pmid="123")).id == paper.id
    assert not library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                       metadata=PaperMetadata(title="Do not recreate")).created
    unexcluded = library.unexclude(cleared.token)
    assert unexcluded.metadata is None
    with pytest.raises(StaleWriteError):
        library.merge_metadata(unexcluded.token, MetadataDelta(abstract="Still no content"))
    rebuilt = library.rebuild_from_run(unexcluded.token, direct_ids=ExternalIds(pmid="123", wos="WOS:456"),
                                       metadata=PaperMetadata(title="Fresh Run result"))
    assert rebuilt.id == paper.id
    assert rebuilt.metadata.title == "Fresh Run result"
    assert rebuilt.metadata_generation > cleared.metadata_generation
    for old in (paper, excluded, cleared, unexcluded):
        with pytest.raises(StaleWriteError):
            library.merge_metadata(old.token, MetadataDelta(abstract="Old result"))
    assert library.merge_metadata(rebuilt.token, MetadataDelta(abstract="New result")).metadata.abstract == "New result"


def test_dates_merge_by_precision_without_preprint_or_publication_inference(library):
    from allfold.persistence.paper_repository import MetadataDelta, PreprintResult

    paper = library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                    metadata=PaperMetadata(title="Article", publication_date="2024")).paper
    first = MetadataDelta(ordinary_dates=("2027-02", "2024-02-29", "2027-02-03"),
                          preprints=(PreprintResult(provider="arxiv", identifier="2401.12345v2", date="2027-02-03"),))
    second = MetadataDelta(ordinary_dates=("2027-02-04", "2027-02", "2024-02-29"))
    expected = ("2024-02-29", "2027-02-03", "2027-02-04")
    merged = library.merge_metadata(paper.token, first)
    merged = library.merge_metadata(paper.token, second)
    assert merged.metadata.ordinary_dates == expected
    assert merged.metadata.publication_date == "2024"
    assert len(merged.metadata.preprints) == 1
    assert merged.metadata.preprints[0].identifier == "2401.12345"
    assert library.match(ExternalIds(arxiv="2401.12345")) is None
    other = create(library, pmid="456")
    library.merge_metadata(other.token, second)
    reversed_result = library.merge_metadata(other.token, first)
    assert reversed_result.metadata.ordinary_dates == expected
    assert reversed_result.metadata.publication_date is None
    preprint_only = create(library, pmid="789")
    result = library.merge_metadata(preprint_only.token, MetadataDelta(preprints=first.preprints))
    assert result.metadata.ordinary_dates == ()


@pytest.mark.parametrize("dates", tuple(permutations(("2026-03", "2026-03-13", "2026-03-14"))))
def test_date_arrival_order_and_duplicates_have_the_same_result(library, dates):
    paper = create(library)
    for value in dates:
        result = library.merge_metadata(paper.token, MetadataDelta(ordinary_dates=(value, value)))
    assert result.metadata.ordinary_dates == ("2026-03-13", "2026-03-14")


@pytest.mark.parametrize("value", ["2026", "2026-00", "2026-13", "2026-02-29", "2024-04-31", "2026-2", "0000-01"])
def test_invalid_or_year_only_ordinary_date_is_rejected_without_guessing(library, value):
    paper = create(library)
    with pytest.raises(ValueError):
        library.merge_metadata(paper.token, {"ordinary_dates": (value,)})
    assert library.get(paper.id) == paper


@pytest.mark.parametrize('original_abstract', ['Methods: Results: Existing formal abstract', 'Abstract', 'No abstract available.', '…', '  Literal <T> &lt; notation\n\nMethods  '])
def test_existing_abstract_and_user_fields_survive_all_automatic_candidates(library, original_abstract):
    metadata = PaperMetadata(title="  Title  ", abstract=original_abstract, notes="  Keep\nnotes\n ")
    paper = library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"), metadata=metadata).paper
    for candidate in (None, "", " \n", "New automatic abstract"):
        result = library.merge_metadata(paper.token, MetadataDelta(abstract=candidate))
        assert result.metadata == paper.metadata
        assert result.metadata.abstract == original_abstract


@pytest.mark.parametrize("candidate, expected", [
    ("We estimate <T> and x < y.", "We estimate <T> and x < y."),
    ("We refer to <p> and estimate <T>.", "We refer to <p> and estimate <T>."),
    ("<p>First line.<br/>Second line with &lt;T&gt;.</p>", "First line.\nSecond line with <T>."),
    ("<p>Scientific <T>notation</T> and <X/>.</p>", "Scientific <T>notation</T> and <X/>."),
    ("<h2>Abstract</h2><h3>Background</h3><p>α &lt; β; P &lt; 0.05.</p><h3>Methods</h3><p>First line.<br>Second line.</p><h3>Results</h3><p>n &gt; 2.</p>",
     "Background\nα < β; P < 0.05.\nMethods\nFirst line.\nSecond line.\nResults\nn > 2."),
    ("Abstract:\nBackground: α < β.\nMethods: n < 5.\nResults: x ≥ 2.",
     "Background: α < β.\nMethods: n < 5.\nResults: x ≥ 2."),
])
def test_new_abstract_preserves_internal_headings_science_and_paragraphs(library, candidate, expected):
    paper = create(library)
    result = library.merge_metadata(paper.token, MetadataDelta(abstract=candidate))
    assert result.metadata.abstract == expected
    result = library.edit_metadata(result.token, {"notes": "Human notes"})
    assert library.merge_metadata(result.token, MetadataDelta(ordinary_dates=("2026-11",))).metadata.abstract == expected


@pytest.mark.parametrize("candidate", ["Abstract", "Summary:", "<h2>Abstract</h2>", "<h3>Methods</h3>", "<script>unsafe()</script>", "<!-- no abstract -->", '<img alt="No text"/>',
    'No abstract available', 'No abstract available.', 'No abstract\navailable.', '<p>Abstract unavailable.</p>', 'Please sign in to read the abstract.', 'Read more', '…', '...'])
def test_ineligible_abstract_does_not_claim_first_candidate(library, candidate):
    paper = create(library)
    empty = library.merge_metadata(paper.token, MetadataDelta(abstract=candidate))
    assert empty.metadata.abstract is None
    assert library.merge_metadata(paper.token, MetadataDelta(abstract="Short complete result.")).metadata.abstract == "Short complete result."


def test_empty_abstract_does_not_claim_first_candidate_and_unrelated_edits_preserve_authority(library):
    paper = create(library)
    for empty in (None, "", " \n\t", "<p> </p>"):
        assert library.merge_metadata(paper.token, MetadataDelta(abstract=empty)).metadata.abstract is None
    edited = library.edit_metadata(paper.token, {"title": "Human title", "notes": "Human notes"})
    result = library.merge_metadata(paper.token, MetadataDelta(abstract="<p>First valid abstract</p>"))
    assert result.metadata.title == edited.metadata.title
    assert result.metadata.notes == "Human notes"
    assert result.metadata.abstract == "First valid abstract"
    assert library.merge_metadata(paper.token, MetadataDelta(abstract="Second")).metadata.abstract == "First valid abstract"


@pytest.mark.parametrize("manual", ["Human abstract", "", None])
def test_manual_abstract_edit_revokes_only_older_abstract_candidates(library, manual):
    paper = create(library)
    edited = library.edit_metadata(paper.token, {"abstract": manual, "notes": "Human notes"})
    result = library.merge_metadata(paper.token, MetadataDelta(abstract="Old candidate", ordinary_dates=("2026-11",)))
    assert result.metadata.abstract == (manual or None)
    assert result.metadata.ordinary_dates == ("2026-11",)
    assert result.metadata.notes == "Human notes"
    with pytest.raises(StaleWriteError):
        library.edit_metadata(paper.token, {"abstract": "Stale local edit"})
    if not manual:
        assert library.merge_metadata(edited.token, MetadataDelta(abstract="Fresh candidate")).metadata.abstract == "Fresh candidate"


def test_concurrent_automatic_abstracts_fill_once_without_lost_dates(library, tmp_path):
    paper = create(library)
    barrier = Barrier(3)

    def worker(index):
        with PaperRepository.open(tmp_path / "Workspace") as repository:
            barrier.wait(timeout=5)
            return repository.merge_metadata(paper.token, MetadataDelta(
                abstract=f"Candidate {index}", ordinary_dates=(f"2026-11-0{index}",)))

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(worker, (1, 2, 3)))
    assert len({result.metadata.abstract for result in results}) == 1
    assert library.get(paper.id).metadata.ordinary_dates == ("2026-11-01", "2026-11-02", "2026-11-03")


def test_incremental_identities_are_atomic_and_all_survive_clearing(library):
    paper = create(library, doi="10.1234/first")
    merged = library.merge_metadata(paper.token, MetadataDelta(), direct_ids=ExternalIds(doi="10.1234/second", pmid="123"))
    assert len(merged.identities) == 3
    assert library.match(ExternalIds(doi="10.1234/second")).id == paper.id
    other = create(library, wos="WOS:456")
    with pytest.raises(IdentityConflict):
        library.merge_metadata(merged.token, MetadataDelta(abstract="Must roll back"),
                               direct_ids=ExternalIds(wos="WOS:456", pmcid="PMC789"))
    assert library.get(paper.id) == merged
    assert library.get(other.id) == other
    assert library.match(ExternalIds(pmcid="PMC789")) is None
    cleared = library.clear_metadata(library.exclude(merged.token).token)
    assert cleared.identities == merged.identities
    assert library.match(ExternalIds(doi="10.1234/first")).id == paper.id
    assert library.match(ExternalIds(doi="10.1234/second")).id == paper.id


def test_restore_never_reactivates_pre_exclusion_tokens(library):
    paper = create(library)
    restored = library.restore(library.exclude(paper.token).token)
    assert not restored.excluded
    assert restored.metadata == paper.metadata
    with pytest.raises(StaleWriteError):
        library.merge_metadata(paper.token, MetadataDelta(abstract="Stale"))
    with pytest.raises(StaleWriteError):
        library.complete_body(paper.token, BodyReference(relative_path="Documents/late.pdf"))
    assert library.merge_metadata(restored.token, MetadataDelta(abstract="Fresh")).metadata.abstract == "Fresh"


def test_only_released_placeholders_accept_new_run_results(library):
    paper = create(library)
    arguments = dict(direct_ids=ExternalIds(doi="10.1234/main"), metadata=PaperMetadata(title="New result"))
    with pytest.raises(InvalidPaperState):
        library.clear_metadata(paper.token)
    with pytest.raises(InvalidPaperState):
        library.rebuild_from_run(paper.token, **arguments)
    with pytest.raises(InvalidPaperState):
        library.unexclude(paper.token)
    excluded = library.exclude(paper.token)
    with pytest.raises(InvalidPaperState):
        library.rebuild_from_run(excluded.token, **arguments)
    cleared = library.clear_metadata(excluded.token)
    with pytest.raises(InvalidPaperState):
        library.rebuild_from_run(cleared.token, **arguments)
    with pytest.raises(InvalidPaperState):
        library.restore(cleared.token)
    released = library.unexclude(cleared.token)
    with pytest.raises(IdentityConflict):
        library.rebuild_from_run(released.token, direct_ids=ExternalIds(pmid="999"), metadata=arguments["metadata"])
    with pytest.raises(InvalidPaperState):
        library.edit_metadata(released.token, {"notes": "Cannot invent content"})
    with pytest.raises(ValueError):
        library.rebuild_from_run(released.token, direct_ids=arguments["direct_ids"], metadata={"title": " "})
    assert library.get(paper.id) == released


def test_wrong_workspace_or_missing_paper_tokens_do_not_mutate(library):
    paper = create(library)
    with pytest.raises(StaleWriteError):
        library.merge_metadata(replace(paper.token, workspace_id=uuid4()), MetadataDelta(abstract="Wrong Workspace"))
    with pytest.raises(PaperNotFoundError):
        library.merge_metadata(replace(paper.token, paper_id=uuid4()), MetadataDelta(abstract="Missing Paper"))
    assert library.get(paper.id) == paper


def test_arxiv_doi_mapping_reuses_existing_direct_normalization(library):
    paper = create(library, arxiv="2401.12345v1")
    matched = create(library, doi="10.48550/arXiv.2401.12345v2")
    assert matched.id == paper.id


def test_concurrent_body_completions_have_one_current_slot(library, tmp_path):
    paper = create(library)
    barrier = Barrier(2)

    def worker(name):
        with PaperRepository.open(tmp_path / "Workspace") as repository:
            barrier.wait(timeout=5)
            try:
                return repository.complete_body(paper.token, BodyReference(relative_path=f"Documents/{name}.pdf"))
            except StaleWriteError:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(worker, ("first", "second")))
    accepted = tuple(result for result in results if result is not None)
    assert len(accepted) == 1
    assert library.get(paper.id).body == accepted[0].body
    replacement = library.complete_body(accepted[0].token, BodyReference(relative_path="Documents/replacement.pdf"))
    assert replacement == accepted[0]
    assert library.get(paper.id).body == accepted[0].body
    cleared = library.clear_body(replacement.token)
    with pytest.raises(StaleWriteError):
        library.complete_body(replacement.token, BodyReference(relative_path="Documents/late.pdf"))
    assert library.get(paper.id) == cleared


def test_rebuild_conflicting_identity_is_atomic_and_retains_placeholder(library):
    paper = create(library, pmid="123")
    other = create(library, wos="WOS:456")
    placeholder = library.unexclude(library.clear_metadata(library.exclude(paper.token).token).token)
    with pytest.raises(IdentityConflict):
        library.rebuild_from_run(placeholder.token, direct_ids=ExternalIds(pmid="123", wos="WOS:456", pmcid="PMC789"),
                                 metadata=PaperMetadata(title="Conflicting Run result"))
    assert library.get(paper.id) == placeholder
    assert library.get(other.id) == other
    assert library.match(ExternalIds(pmcid="PMC789")) is None


def test_invalid_model_copy_is_revalidated_before_creation(library):
    with pytest.raises(ValueError):
        library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                metadata=PaperMetadata(title="Valid").model_copy(update={"title": " "}))
    with pytest.raises(ValueError):
        library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123").model_copy(update={"dblp": "retired"}),
                                metadata=PaperMetadata(title="Valid"))
    assert library.list_papers() == ()


def test_body_slot_survives_metadata_clear_and_can_be_obtained_again(library, tmp_path):
    from allfold.persistence.paper_repository import BodyReference, MetadataDelta

    paper = create(library)
    body = BodyReference(relative_path="Documents/paper.pdf", source_url="https://example.org/paper.pdf", size_bytes=42)
    linked = library.complete_body(paper.token, body)
    assert linked.body == body
    assert not (tmp_path / "Workspace" / "Documents").exists()
    with pytest.raises(StaleWriteError):
        library.complete_body(paper.token, body)
    excluded = library.exclude(linked.token)
    with pytest.raises(StaleWriteError):
        library.complete_body(excluded.token, body)
    cleared = library.clear_metadata(excluded.token)
    assert cleared.body == body
    with pytest.raises(StaleWriteError):
        library.complete_body(cleared.token, body)
    unexcluded = library.unexclude(cleared.token)
    with pytest.raises(StaleWriteError):
        library.complete_body(unexcluded.token, body)
    without_body = library.clear_body(unexcluded.token)
    assert without_body.body is None
    rebuilt = library.rebuild_from_run(without_body.token, direct_ids=ExternalIds(doi="10.1234/main"),
                                       metadata=PaperMetadata(title="New result"))
    reacquired = library.complete_body(rebuilt.token, body)
    assert reacquired.body == body
    without_body = library.clear_body(reacquired.token)
    assert without_body.metadata == reacquired.metadata
    assert without_body.identities == paper.identities
    # A body-local edit does not invalidate unrelated metadata work.
    assert library.merge_metadata(rebuilt.token, MetadataDelta(abstract="Valid metadata")).metadata.abstract == "Valid metadata"
    assert library.complete_body(without_body.token, body).body == body
    with PaperRepository.open(tmp_path / "Workspace") as reopened:
        assert reopened.get(paper.id).body == body


def test_library_snapshot_revision_covers_local_edits_and_identity_primary_is_stable(library):
    from datetime import datetime, timezone
    from allfold.persistence.paper_repository import DirectIdentity

    discovered = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
    first_revision, papers = library.snapshot()
    assert first_revision == 0 and papers == ()
    created = library.create_or_match(library.workspace_id,
        direct_ids=ExternalIds(doi='10.1234/primary', pmid='123'),
        metadata=PaperMetadata(title='Original title', discovered_at=discovered)).paper
    assert created.primary_identity == DirectIdentity('doi', '10.1234/primary')
    before, _ = library.snapshot()
    edited = library.edit_metadata(created.token, {'title': 'Human title'})
    merged = library.merge_metadata(created.token, MetadataDelta(), direct_ids=ExternalIds(doi='10.1234/alias'))
    revision, papers = library.snapshot()
    assert revision > before > first_revision
    assert papers == (merged,)
    assert merged.revision > edited.revision > created.revision
    assert merged.primary_identity == created.primary_identity
    assert merged.metadata.discovered_at == discovered


def test_primary_identity_and_all_formal_ids_survive_multi_identity_capture(library):
    from allfold.persistence.paper_repository import DirectIdentity
    identities = (DirectIdentity('doi', '10.1234/another'), DirectIdentity('openalex', 'W123'))
    paper = library.create_or_match(library.workspace_id, direct_ids=ExternalIds(doi='10.1234/primary'),
        additional_identities=identities, metadata=PaperMetadata(title='Article')).paper
    assert paper.primary_identity == DirectIdentity('doi', '10.1234/primary')
    assert library.match(ExternalIds(doi='10.1234/another')).id == paper.id
    cleared = library.clear_metadata(library.exclude(paper.token).token)
    assert cleared.primary_identity == paper.primary_identity
    assert set(cleared.identities) == {DirectIdentity('doi', '10.1234/primary'), *identities}
