"""Small offline, evidence-backed Journal ISSN → DBLP Stream mappings.

Verified 2026-11-05 against the stream key and Venue Information on the official
pages below. Names are descriptive; only exact saved ISSNs select a stream.
Missing or conflicting mappings remain unsupported instead of broadening scope.
"""
from collections.abc import Iterable


# https://dblp.org/db/journals/jmlr/index.html
# https://www.jmlr.org/ (print/online ISSNs independently confirmed)
# https://dblp.org/db/journals/ml/index.html
JOURNAL_STREAMS = {
    "1532-4435": "streams/journals/jmlr",
    "1533-7928": "streams/journals/jmlr",
    "0885-6125": "streams/journals/ml",
    "1573-0565": "streams/journals/ml",
}


def journal_dblp_stream(issns: Iterable[str]) -> str | None:
    streams = {JOURNAL_STREAMS[value] for value in issns if value in JOURNAL_STREAMS}
    return next(iter(streams)) if len(streams) == 1 else None
