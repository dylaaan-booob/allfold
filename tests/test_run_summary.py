"""Current retrieval and capture classifications shared by results and History."""
import pytest

from allfold.application.monitor import RunOutcome, RunResult
from allfold.application.run_state import RunFacts, RunIssueFact, RunProvider
from allfold.application.run_summary import build_run_result_summary


@pytest.mark.parametrize('retrieval,outcome,issues,expected', [
    ('complete', RunOutcome.COMPLETED, (), 'completed'),
    ('empty', RunOutcome.COMPLETED, (), 'completed'),
    ('partial', RunOutcome.COMPLETED_WITH_ERRORS,
     (RunIssueFact(category='discovery', severity='error', message='europe_pmc / Test: unavailable'),), 'incomplete'),
    ('failed', RunOutcome.FAILED,
     (RunIssueFact(category='discovery', severity='error', message='openalex / Test: unavailable'),), 'failed'),
    ('cancelled', RunOutcome.CANCELLED, (), 'cancelled'),
    ('complete', RunOutcome.COMPLETED_WITH_ERRORS,
     (RunIssueFact(category='write', severity='error', message='Paper write failed'),), 'capture_issues'),
    ('complete', RunOutcome.COMPLETED_WITH_WARNINGS,
     (RunIssueFact(category='snapshot_write', message='Latest result not saved'),), 'completed_with_notices'),
])
def test_integrated_summary_uses_current_facts(retrieval, outcome, issues, expected):
    facts = RunFacts(created_papers=0, existing_papers=1, statistics={
        'integrated_candidates': 1, 'integrated_deduplicated': 1}, issues=issues,
        details={'discovery_status': retrieval, 'provider_runs': []})
    result = RunResult(RunProvider.INTEGRATED, None, (), (), outcome, facts)
    summary = build_run_result_summary(result)
    assert summary['status'] == expected and summary['coverage_status'] == retrieval
    assert summary['created_papers'] == 0 and summary['existing_papers'] == 1
    assert summary['statistics'] == {'integrated_candidates': 1, 'integrated_deduplicated': 1}
    assert 'coverage' not in summary


@pytest.mark.parametrize('finished,batches,returned,outcome,expected,coverage', [
    (True, [], 0, 'Completed', 'completed', 'complete'),
    (True, [{'complete': True}], 2, 'Completed', 'completed', 'complete'),
    (False, [{'complete': True}], 2, 'Partial', 'incomplete', 'partial'),
    (True, [{'complete': False}], 2, 'Partial', 'incomplete', 'partial'),
    (False, [], 0, 'Failed', 'failed', 'failed'),
    (False, [], 0, 'Cancelled', 'cancelled', 'failed'),
    (True, [{'complete': True}], 2, 'Partial', 'capture_issues', 'complete'),
])
def test_wos_summary_keeps_query_and_batch_completeness(finished, batches, returned, outcome, expected, coverage):
    batches = [dict(first=1, last=2, expected=2, exported=returned, eligible=returned, issues=[], **batch)
               for batch in batches]
    result = {'provider': 'wos', 'result': {'outcome': outcome, 'returned_records': returned,
        'facts': RunFacts(created_papers=returned, existing_papers=0,
            statistics={'returned_records': returned},
            details={'query_finished': finished, 'batches': batches}).model_dump(mode='json')}}
    summary = build_run_result_summary(result)
    assert summary['status'] == expected and summary['coverage_status'] == coverage
    assert summary['details']['batches'] == batches
    assert summary['statistics']['returned_records'] == returned


def test_unexpected_run_error_is_failed_with_unknown_counts():
    summary = build_run_result_summary({'provider': 'integrated', 'result': None,
        'unexpected_error': {'message': 'Run stopped unexpectedly'}})
    assert summary['status'] == 'failed' and summary['coverage_status'] == 'unknown'
    assert summary['created_papers'] is None and summary['existing_papers'] is None
    assert summary['issues'] == [{'category': 'runtime', 'severity': 'error', 'message': 'Run stopped unexpectedly'}]
