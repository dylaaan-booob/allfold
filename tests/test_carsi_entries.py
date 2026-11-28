from allfold.application import carsi_entry
from allfold.application.carsi_catalog import CarsiResource, get_carsi_catalog
from allfold.application.carsi_entry import service_entry
from allfold.config import AccessService, InstitutionConfig
from allfold.url_safety import normalize_public_http_url


def test_bundled_catalog_has_public_evidence_and_valid_product_types():
    catalog = get_carsi_catalog()
    assert catalog
    for name, row in catalog.items():
        assert name == row.production and name and row.searchStr.strip() and row.url.strip()
        assert row.sptype in {'1', '2'}
        assert row.entry_sources and all(normalize_public_http_url(url) for url in row.entry_sources)
        assert not (row.wayfless_url_template and row.unavailable_reason)


def test_selected_entries_require_only_their_own_institution_parameters(monkeypatch):
    base = 'https://journals.example/'
    fixtures = [
        CarsiResource('Gale', 'Gale', base, '1', 'https://link.gale.com/apps/menu?u={gale_location_id}'),
        CarsiResource('Tenant', 'Tenant', base, '1',
                      base + 'auth?entity={idp_entity_id}&target=https%3A%2F%2Fjournals.example%2F%3Fstate%3D{product_tenant_id}'),
        CarsiResource('Institution URL', 'Institution URL', base, '2',
                      base + 'auth?state={institution_resource_url}&idp={idp_entity_id}'),
        CarsiResource('Statista', 'Statista', base, '1',
                      'https://shibboleth.statista.com/Shibboleth.sso/Login?entityID={idp_entity_id}&target={statista_auth_target}'),
        CarsiResource('Stopped', 'Stopped', base, '1', unavailable_reason='Service closed'),
    ]
    monkeypatch.setattr(carsi_entry, 'get_carsi_catalog', lambda: {row.production: row for row in fixtures})
    idp = 'https://idp.example/idp/shibboleth'

    def entry(name, **params):
        service = AccessService.create(name, 'https://previous.example/')
        return service_entry(service, InstitutionConfig(**params))

    missing = entry('Gale', idp_entity_id=idp, use_shibboleth=True)
    assert missing['wayfless_url'] is None
    assert missing['portal_login_url'] == (
        'https://ds.carsi.edu.cn/Shibboleth.sso/Login?entityID=https%3A%2F%2Fidp.example%2Fidp%2Fshibboleth'
        '&target=https%3A%2F%2Fds.carsi.edu.cn%2Fwxds')
    assert missing['access_url'] == base
    assert entry('Gale', gale_location_id='A/B +中')['wayfless_url'] == 'https://link.gale.com/apps/menu?u=A%2FB%20%2B%E4%B8%AD'
    assert entry('Gale', gale_location_id='other')['wayfless_url'] == 'https://link.gale.com/apps/menu?u=other'
    assert entry('Tenant', idp_entity_id=idp)['wayfless_url'] is None
    assert 'A%252FB%2520%252B' in entry('Tenant', idp_entity_id=idp, product_tenant_id='A/B +')['wayfless_url']
    assert entry('Institution URL', idp_entity_id=idp)['wayfless_url'] is None
    assert 'state=https%3A%2F%2Fread.example%2Fpart%252Fkeep%3Fstate%3Dx' in entry(
        'Institution URL', idp_entity_id=idp, institution_resource_url='https://read.example/part%2Fkeep?state=x')['wayfless_url']
    assert entry('Statista', idp_entity_id='https://idp.example/中')['wayfless_url'] == (
        'https://shibboleth.statista.com/Shibboleth.sso/Login?entityID=https%3A%2F%2Fidp.example%2F%E4%B8%AD'
        '&target=https%3A%2F%2Fshibboleth.statista.com%2Findex.php%3Fidp%3DaHR0cHM6Ly9pZHAuZXhhbXBsZS%252FkuK0%253D')
    assert entry('Stopped', idp_entity_id=idp, use_shibboleth=True) == {'unavailable_reason': 'Service closed'}
