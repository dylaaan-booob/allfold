from allfold.persistence.paper_repository import PaperRepository
from allfold.persistence.library_models import PaperMetadata
from allfold.models import ExternalIds, MetadataSource
from test_web_app import write_valid_config

FORMAL = '10.5555/decision'


def create_paper(tmp_path, **metadata):
    config, workspace = write_valid_config(tmp_path)
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id,
            direct_ids=ExternalIds(doi=FORMAL), metadata=PaperMetadata(title='Saved formal article',
                publication_type='journal', journal='Biometrics', journal_issns=('0006-341X',),
                **metadata)).paper
    return config, workspace, paper


def read_paper(workspace, paper_id):
    with PaperRepository.open(workspace) as repository:
        return repository.get(paper_id)
