"""Lightweight Kept inventory from the same globally checked plan as Import."""
from allfold.application.workspace import load_workspace, paper_service_assignment


def kept_queue(workspace, journals, services, plan, batch):
    saved = load_workspace(workspace, journals)
    eligible = {paper.paper_id for paper in (plan.inventory or plan.papers)} if plan else set()
    rows = [dict(id='all', name='All Services', access_method=None),
            *(dict(id=service.id, name=service.name, access_method=service.access_method) for service in services),
            dict(id='unassigned', name='Unassigned', access_method=None),
            dict(id='ambiguous', name='Ambiguous', access_method=None)]
    known = {row['id'] for row in rows}
    for paper in batch.plan.papers if batch.plan else ():
        if paper.service_id and paper.service_id not in known:
            rows.append(dict(id=paper.service_id, name=paper.service_id + ' (batch)', access_method=None))
            known.add(paper.service_id)
    for row in rows:
        row.update(kept=0, eligible=0, planned=0, processed=0, confirmed=0,
                   pending=0, skipped=0, exceptions=0, uncertain=0, no_effect=0, pdf_unverified=0)
    by_id = {row['id']: row for row in rows}
    papers = []
    for paper in saved.kept:
        service_id, assignment = paper_service_assignment(paper, journals)
        group = service_id or assignment
        qualified = paper.paper_id in eligible
        for row in (by_id['all'], by_id[group]):
            row['kept'] += 1
            row['eligible'] += qualified
        papers.append(dict(paper_id=str(paper.paper_id), doi=paper.external_ids.doi,
            title=paper.title, service_id=service_id, assignment=assignment, eligible=qualified,
            reason=('Saved Journal mapping agrees' if service_id else
                    'Journal matches disagree; correct the saved mapping' if assignment == 'ambiguous' else
                    'No saved Service assignment') + ('' if qualified else '; excluded by Workspace safety plan')))
    if batch.plan:
        outcomes = {result.paper_id: result for result in batch.results}
        for paper in batch.plan.papers:
            # Historical identity belongs to the plan, never the current mapping.
            result = outcomes.get(paper.paper_id)
            for row in (by_id['all'], by_id.get(paper.service_id or paper.service_assignment)):
                if row is None:
                    continue
                row['planned'] += 1
                row['pending'] += result is None
                if result:
                    row['processed'] += result.outcome != 'skipped'
                    row['confirmed'] += result.parent_outcome == 'confirmed'
                    row['skipped'] += result.outcome == 'skipped'
                    row['exceptions'] += result.outcome == 'blocked' or bool(result.diagnostic)
                    row['uncertain'] += result.parent_outcome == 'uncertain'
                    row['no_effect'] += result.outcome == 'no_effect'
                    row['pdf_unverified'] += result.pdf_outcome is not None and result.pdf_outcome.value == 'unverified'
    return dict(services=rows, papers=papers, issues=[issue.message for issue in saved.issues])
