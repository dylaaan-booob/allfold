"""Select full offline CI unless the complete diff is known explanatory docs.

Uses only Git and the Python standard library, before dependency installation.
"""
import json
import os
from pathlib import Path
import re
import subprocess


# Reviewed against runtime, build scripts and tests. New/unknown paths run full CI.
# README.md is Python package metadata; list.md is a runtime/test input. UI and
# third-party notices can be copied into build output. None belongs in this set.
EXPLANATORY_DOCS = frozenset({
    'AGENTS.md',
    'docs/agents/issue-tracker.md',
    'docs/agents/triage-labels.md',
    'docs/architecture.md',
    'docs/biorxiv-doi-routing.md',
    'docs/body-downloads.md',
    'docs/browser-documents.md',
    'docs/browser-pages.md',
    'docs/browser-session.md',
    'docs/collection-runtime.md',
    'docs/development.md',
    'docs/gokb-api.md',
    'docs/http.md',
    'docs/logging.md',
    'docs/paper-identity.md',
    'docs/paper-library.md',
    'docs/pdf-source-discovery.md',
    'docs/providers.md',
    'docs/release.md',
    'docs/research-scope.md',
    'docs/safety.md',
    'docs/third-party.md',
    'docs/workspace-layout.md',
    'docs/wos-export.md',
})


def git(*args):
    return subprocess.check_output(['git', *args], stderr=subprocess.PIPE)


def commit_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('missing commit')
    # Also rejects zero SHAs, unavailable history and non-commit objects.
    git('cat-file', '-e', value + '^{commit}')
    return value


def select_scope(event_name, event):
    if event_name == 'workflow_dispatch':
        return True, 'manual dispatch always runs the complete offline suite'
    try:
        if event_name == 'pull_request':
            pr = event['pull_request']
            base = commit_sha(pr['base']['sha'])
            head = commit_sha(pr['head']['sha'])
            bases = git('merge-base', '--all', base, head).decode().splitlines()
            if len(bases) != 1:
                raise ValueError('ambiguous merge base')
            base = bases[0]
            scope = 'entire PR'
        elif event_name == 'push':
            base = commit_sha(event['before'])
            head = commit_sha(event['after'])
            scope = 'entire push'
        else:
            return True, 'unrecognized event'
        # Disabling rename detection includes both old and new paths. NUL framing
        # preserves spaces/newlines; deletions participate just like additions.
        raw = git('diff', '--name-only', '--no-renames', '-z', base, head, '--')
        paths = raw.decode('utf-8').split('\0')[:-1]
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError):
        return True, 'complete change set unavailable; defaulting to full validation'
    if not paths:
        return True, 'empty change set; defaulting to full validation'
    if any(path not in EXPLANATORY_DOCS for path in paths):
        return True, f'{scope} includes runtime/build/test inputs or unclassified paths'
    return False, f'all {len(paths)} changed paths in the {scope} are reviewed explanatory docs'


def main():
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    except (KeyError, OSError, ValueError):
        event = {}
    full, reason = select_scope(os.environ.get('GITHUB_EVENT_NAME', ''), event)
    message = f'CI scope: {"full offline validation" if full else "documentation only"} — {reason}.'
    print(message)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'full={str(full).lower()}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write(message + '\n')


if __name__ == '__main__':
    main()
