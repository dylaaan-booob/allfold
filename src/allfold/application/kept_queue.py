"""Lightweight Kept inventory from the same globally checked plan as Import."""
from allfold.application.workspace import load_workspace, paper_service_assignment


def kept_queue(workspace, journals, services, plan):
    saved = load_workspace(workspace, journals)
    eligible = {paper.paper_id for paper in (plan.inventory or plan.papers)} if plan else set()
    rows = [dict(id='all', name='All Services', access_method=None),
            *(dict(id=service.id, name=service.name, access_method=service.access_method) for service in services),
            dict(id='unassigned', name='Unassigned', access_method=None),
            dict(id='ambiguous', name='Ambiguous', access_method=None)]
    for row in rows:
        row.update(kept=0, eligible=0)
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
            reason=('A valid primary DOI is required for Import' if not paper.external_ids.doi else
                    'Preprint Import is not supported' if paper.publication_type == 'preprint' else
                    'Saved Journal mapping agrees' if service_id else
                    'Journal matches disagree; correct the saved mapping' if assignment == 'ambiguous' else
                    'No saved Service assignment') + ('' if qualified else '; excluded by Workspace safety plan')))
    return dict(services=rows, papers=papers, issues=[issue.message for issue in saved.issues])
