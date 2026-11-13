"""Failure-isolated observations at coordinator boundaries, never workflow authority."""
import sys


def observe(store, method, *args, **kwargs):
    if store is None:
        return None
    try:
        return getattr(store, method)(*args, **kwargs)
    except Exception:
        print('Allfold diagnostics: coordinator observation unavailable.', file=sys.stderr)
        return None


def finish_run(store, task_id, result, *, provider=None, diagnostic=None, interrupted=False, recovery=None):
    if store is None:
        return
    from allfold.application.run_summary import build_run_result_summary
    try:
        summary = build_run_result_summary(result) if result is not None else None
    except Exception:
        print("Allfold diagnostics: Run summary unavailable.", file=sys.stderr)
        return
    if summary is None:
        observe(store, 'finish', task_id, 'failed', details={'reason':'failed', 'recovery':recovery})
        return
    status = summary['status']
    outcome = ('interrupted' if interrupted else 'partial' if status in {'incomplete', 'capture_issues'} else
        status if status in {'failed', 'cancelled'} else 'completed')
    stats = summary['statistics']
    retrieved = stats.get('returned_records', 0) if provider == 'wos' else sum(
        value for key,value in stats.items() if key in {'integrated_candidates'})
    sources = {}
    for run in summary['details'].get('provider_totals', summary['details'].get('provider_runs', [])):
        if run.get('provider') not in {'wos', 'pubmed', 'openalex'}:
            continue
        source = sources.setdefault(run['provider'], dict(provider=run['provider'], status='empty', candidates=0, created=0, existing=0, problems=0))
        for key in ('candidates', 'created', 'existing'):
            source[key] += run.get(key) or 0
        source['problems'] += len(run.get('limitations') or [])
        before, after = source['status'], run.get('status')
        if 'cancelled' in {before, after}: source['status']='cancelled'
        elif after in {'failed','partial','skipped'} or before in {'failed','partial','skipped'}:
            source['status']='failed' if after=='failed' and before in {'empty','failed'} else 'partial'
        elif after=='complete': source['status']='complete'
    checks = {}
    if 'batches' in summary['details']:
        batches=summary['details']['batches']
        checks=dict(batches=len(batches), completed_batches=sum(batch.get('complete') is True for batch in batches),
            journal_hints=sum(journal.get('status')=='hint' for journal in summary['journals']),
            date_hints=len(summary['details'].get('date_warnings') or []),
            unmatched_records=stats.get('unmatched_journal_records',0))
    observe(store, 'finish', task_id, outcome,
        statistics={'created':summary['created_papers'], 'unchanged':summary['existing_papers'],
            'retrieved':retrieved, 'warnings':sum(i.get('severity') != 'error' for i in summary['issues']),
            'errors':sum(i.get('severity') == 'error' for i in summary['issues']),
            **{key:value for key,value in stats.items() if key in {
                'integrated_candidates','integrated_deduplicated','work_location_targets','completion_targets',
                'pmid_resolution_matched','pmid_resolution_no_match','pmid_resolution_conflicts',
                'pmid_resolution_failed','pmid_resolution_cancelled',
                'completion_requests','completion_date_facts_added','first_public_recorded','first_public_no_association',
                'first_public_known_unresolved','first_public_conflict','first_public_failed','first_public_cancelled'}}},
        diagnostic=diagnostic, details={'result_status':status, 'coverage_status':summary['coverage_status'], 'recovery':recovery,
            'run_sources':list(sources.values()), 'wos_checks':checks,
            'discovery_status':summary['details'].get('discovery_status'),
            'completion_status':summary['details'].get('completion_status'),
            'reason':'connection_lost' if interrupted else 'partial' if outcome == 'partial' else outcome if outcome in {'failed','cancelled'} else None})
