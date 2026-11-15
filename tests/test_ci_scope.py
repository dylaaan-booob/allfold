"""Exercise CI selection through its command using disposable Git histories."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'ci_scope.py'


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'repo'
    path.mkdir()
    git(path, 'init', '-q', '-b', 'main')
    git(path, 'config', 'user.name', 'CI fixture')
    git(path, 'config', 'user.email', 'fixture@example.invalid')
    commit(path, {'docs/development.md': 'guide', 'src/example.py': 'original'})
    return path


def commit(repo, files):
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            target.unlink()
        else:
            target.write_text(content)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'fixture change')
    return git(repo, 'rev-parse', 'HEAD')


def select(repo, event_name, event):
    event_path = repo.parent / 'event.json'
    event_path.write_text(json.dumps(event))
    output = repo.parent / 'output'
    summary = repo.parent / 'summary'
    output.write_text('')
    summary.write_text('')
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True,
        env={**os.environ, 'GITHUB_EVENT_NAME': event_name,
             'GITHUB_EVENT_PATH': str(event_path), 'GITHUB_OUTPUT': str(output),
             'GITHUB_STEP_SUMMARY': str(summary)},
    )
    assert result.returncode == 0, result.stderr
    values = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert summary.read_text().strip() and result.stdout.strip()
    return values['full'] == 'true'


def test_pr_uses_entire_diff_even_when_last_commit_is_only_documentation(repo):
    base = git(repo, 'rev-parse', 'HEAD')
    commit(repo, {'src/example.py': 'changed'})
    head = commit(repo, {'docs/development.md': 'updated guide'})
    assert select(repo, 'pull_request', {
        'pull_request': {'base': {'sha': base}, 'head': {'sha': head}},
    })


def test_document_pr_excludes_changes_only_on_base_branch(repo):
    git(repo, 'checkout', '-qb', 'feature')
    head = commit(repo, {'docs/development.md': 'feature documentation'})
    git(repo, 'checkout', '-q', 'main')
    base = commit(repo, {'src/example.py': 'independent main change'})
    assert not select(repo, 'pull_request', {
        'pull_request': {'base': {'sha': base}, 'head': {'sha': head}},
    })


@pytest.mark.parametrize(('changes', 'full'), [
    ({'docs/development.md': 'updated', 'AGENTS.md': 'agent guide'}, False),
    ({'docs/development.md': None}, False),
    # Both ends of a rename count, even when Git detects identical content.
    ({'docs/development.md': None, 'docs/safety.md': 'guide'}, False),
    ({'src/example.py': None, 'docs/safety.md': 'original'}, True),
    ({'docs/development.md': None, 'tools/example.py': 'guide'}, True),
    ({'docs/development.md': 'updated', 'src/example.py': 'changed'}, True),
    ({'.github/workflows/ci.yml': 'changed'}, True),
    ({'tools/check.py': 'changed'}, True),
    ({'tests/fixtures/example.md': 'test input'}, True),
    ({'pyproject.toml': 'changed'}, True),
    ({'uv.lock': 'changed'}, True),
    ({'config.template.yaml': 'changed'}, True),
    ({'README.md': 'package description'}, True),
    ({'list.md': 'journal seed'}, True),
    ({'docs/unclassified.md': 'unknown purpose'}, True),
])
def test_push_classifies_complete_changes_including_deletions_and_renames(repo, changes, full):
    before = git(repo, 'rev-parse', 'HEAD')
    commit(repo, changes)
    after = commit(repo, {'docs/logging.md': 'last commit is documentation'})
    assert select(repo, 'push', {'before': before, 'after': after}) is full


def test_manual_dispatch_always_runs_full_suite(repo):
    before = git(repo, 'rev-parse', 'HEAD')
    after = commit(repo, {'docs/development.md': 'updated'})
    assert select(repo, 'workflow_dispatch', {'before': before, 'after': after})


@pytest.mark.parametrize('event', [
    {}, {'before': '0' * 40, 'after': '1' * 40},
    {'before': 'not-a-sha', 'after': '1' * 40},
    {'pull_request': {'base': {'sha': '1' * 40}, 'head': {'sha': '2' * 40}}},
])
def test_missing_or_unavailable_history_runs_full_suite(repo, event):
    event_name = 'pull_request' if 'pull_request' in event else 'push'
    assert select(repo, event_name, event)


def test_empty_diff_runs_full_suite(repo):
    sha = git(repo, 'rev-parse', 'HEAD')
    assert select(repo, 'push', {'before': sha, 'after': sha})
