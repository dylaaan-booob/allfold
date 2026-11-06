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


def batch_history(snapshot):
    """Project the coordinator's settled Paper outcomes, keeping parent and PDF distinct."""
    stats = snapshot.statistics
    phase = snapshot.phase.value
    uncertain = stats.uncertain > 0
    outcome = ('uncertain' if uncertain else 'cancelled' if phase == 'stopped' else
        'failed' if phase == 'blocked' and not snapshot.results else
        'confirmed' if snapshot.successful else 'partial' if snapshot.results else
        'needs_attention' if phase in {'blocked', 'paused'} else 'no_effect')
    counts = dict(confirmed=sum(r.parent_outcome == "confirmed" for r in snapshot.results), exported=stats.exported_parent, no_effect=stats.no_effect, uncertain=stats.uncertain,
        skipped=stats.skipped_blocked, excluded=stats.normal_excluded,
        warnings=sum(bool(r.diagnostic and r.diagnostic.get("stage") == "attachment") for r in snapshot.results),
        total=len(snapshot.plan.papers) if snapshot.plan else 0, processed=sum(r.outcome != 'skipped' for r in snapshot.results))
    results = [dict(paper_id=str(r.paper_id), service_id=r.service_id, service_assignment=r.service_assignment,
        outcome={'exported':'confirmed', 'blocked':'needs_attention',
        'skipped':'no_effect'}.get(r.outcome, r.outcome), parent_outcome=r.parent_outcome,
        pdf_outcome='unverified', reason=r.reason_code, diagnostic=r.diagnostic) for r in snapshot.results]
    service_statistics = {}
    completed = {result.paper_id: result for result in snapshot.results}
    for paper in snapshot.plan.papers if snapshot.plan else ():
        key = paper.service_id or paper.service_assignment
        counts_by_service = service_statistics.setdefault(key, dict(service_id=paper.service_id,
            service_assignment=paper.service_assignment, total=0, processed=0, confirmed=0,
            no_effect=0, uncertain=0, skipped=0, warnings=0, pdf_unverified=0))
        counts_by_service['total'] += 1
        result = completed.get(paper.paper_id)
        if result:
            for name, count in dict(processed=result.outcome != 'skipped', confirmed=result.parent_outcome == 'confirmed',
                no_effect=result.outcome == 'no_effect', uncertain=result.parent_outcome == 'uncertain',
                skipped=result.outcome == 'skipped', warnings=bool(result.diagnostic),
                pdf_unverified=result.pdf_outcome is not None).items():
                counts_by_service[name] += count
    return outcome, counts, dict(batch_phase=phase, results=results,
        batch_scope='service' if snapshot.service_id else 'all', service_id=snapshot.service_id,
        service_statistics=list(service_statistics.values()),
        pdf_outcome='unverified', pdf_verified=False,
        requires_attention=outcome not in {'confirmed', 'no_effect'},
        reason='result_unconfirmed' if uncertain else 'pdf_unverified' if snapshot.successful else
            'cancelled' if phase == 'stopped' else 'partial' if snapshot.results else 'no_candidates')


def finish_run(store, task_id, result, *, provider=None, diagnostic=None, interrupted=False):
    if store is None:
        return
    from allfold.application.run_summary import build_run_result_summary
    try:
        summary = build_run_result_summary(result) if result is not None else None
    except Exception:
        print("Allfold diagnostics: Run summary unavailable.", file=sys.stderr)
        return
    if summary is None:
        observe(store, 'finish', task_id, 'failed', details={'reason':'failed'})
        return
    status = summary['status']
    outcome = ('interrupted' if interrupted else 'partial' if status in {'incomplete', 'capture_issues'} else
        status if status in {'failed', 'cancelled'} else 'completed')
    stats = summary['statistics']
    retrieved = stats.get('returned_records', 0) if provider == 'wos' else sum(
        value for key,value in stats.items() if key in {'openalex_records','crossref_discovery_records','integrated_candidates'})
    observe(store, 'finish', task_id, outcome,
        statistics={'created':summary['created_papers'], 'unchanged':summary['existing_papers'],
            'retrieved':retrieved, 'warnings':sum(i.get('severity') != 'error' for i in summary['issues']),
            'errors':sum(i.get('severity') == 'error' for i in summary['issues'])},
        diagnostic=diagnostic, details={'result_status':status, 'coverage_status':summary['coverage_status'],
            'reason':'connection_lost' if interrupted else 'partial' if outcome == 'partial' else outcome if outcome in {'failed','cancelled'} else None})
