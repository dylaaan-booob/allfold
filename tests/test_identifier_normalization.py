from allfold.identifiers import normalize_external_id, supported_preprint_uri


def test_pmc_numeric_identifier_requires_official_uri_context():
    assert normalize_external_id('pmcid','https://www.ncbi.nlm.nih.gov/pmc/articles/5815332') == 'PMC5815332'
    assert normalize_external_id('pmcid','5815332') is None
    assert normalize_external_id('pmcid','https://other.example/pmc/articles/5815332') is None
    assert normalize_external_id('europe_pmc','MED:123 OR 1') is None


def test_official_preprint_urls_have_anchored_paths_and_normalized_versions():
    assert supported_preprint_uri('https://arxiv.org/pdf/2201.12345v2.pdf') == ('arxiv','2201.12345')
    assert supported_preprint_uri('https://biorxiv.org/content/10.1101/123456v2.full') == ('biorxiv','10.1101/123456')
    assert supported_preprint_uri('https://arxiv.org:444/abs/2201.12345') is None
    assert supported_preprint_uri('https://arxiv.org/other/2201.12345') is None
