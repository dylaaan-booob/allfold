"""Finite refusal for native sinks that lack object-safe cancellation.

Pinned Electron 45's pathname sink can delete a substituted file after done.
Until a qualified sink exists, original browser actions gain no native, network,
file or progress capability. Other source consumers remain independent.
"""
from dataclasses import dataclass

from allfold.pdf_discovery import CandidateResult
from allfold.pdf_responses import reader_context


@dataclass(frozen=True)
class NativeTransferResult:
    result: CandidateResult
    output: object = None
    final_url: str = ''


def native_applicable(candidate):
    """Select fixed action/current-reader contexts, never arbitrary URL likeness."""
    if candidate.credential:
        return False
    if candidate.action:
        return (candidate.action == 'refresh_form' and candidate.platform == 'microbiology'
            and candidate.rule_id == 'R059')
    if candidate.platform != 'sciencedirect' or candidate.rule_id != 'R024':
        return False
    return (reader_context(candidate) or {}).get('platform') == 'sciencedirect'


def transfer_native(reservation, repository, files, candidate, progress=None):
    """Return a condition skip without acquiring or using any capability."""
    return NativeTransferResult(CandidateResult('skipped', diagnostic='native-unsupported'))
