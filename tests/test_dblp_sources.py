from allfold.providers.dblp_sources import journal_dblp_stream


def test_only_verified_issns_resolve_a_journal_stream():
    assert journal_dblp_stream(("1532-4435", "1533-7928")) == "streams/journals/jmlr"
    assert journal_dblp_stream(("1573-0565",)) == "streams/journals/ml"
    assert journal_dblp_stream(("0006-341X",)) is None
    assert journal_dblp_stream(("1532-4435", "0885-6125")) is None
