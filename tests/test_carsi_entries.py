import json
from collections import Counter
from dataclasses import asdict

import httpx

from allfold.application.carsi_catalog import CATALOG_KEY, get_carsi_catalog
from allfold.persistence.resource_cache import read_snapshot, write_snapshot


def test_bundled_defaults_initialize_and_upgrade_the_catalog(tmp_path):
    fresh = tmp_path / 'fresh.sqlite'
    catalog = get_carsi_catalog(fresh)
    assert Counter(
        'unavailable' if row.unavailable_reason else 'wayfless' if row.wayfless_url_template else 'portal'
        for row in catalog.resources
    ) == {'wayfless': 180, 'portal': 181, 'unavailable': 1}
    assert all(row.entry_sources for row in catalog.resources)
    assert all(url.startswith(('http://', 'https://')) for row in catalog.resources for url in row.entry_sources)

    rows = read_snapshot(fresh, CATALOG_KEY).payload['resources']
    official = [{k: row[k] for k in ('production', 'searchStr', 'url', 'sptype')} for row in rows]
    upgrade = tmp_path / 'existing.sqlite'
    old = write_snapshot(upgrade, CATALOG_KEY, {'resources': official})
    assert get_carsi_catalog(upgrade).resources == catalog.resources
    assert read_snapshot(upgrade, CATALOG_KEY).fetched_at == old.fetched_at

    first = dict(official[0], searchStr=official[0]['searchStr'] + ' Updated search label')
    replacement = dict(production='Different product', searchStr='Different product',
                       url=official[1]['url'], sptype=official[1]['sptype'])
    html = '<script>var SPList=' + json.dumps([first, replacement]) + ';</script>'
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={'content-type': 'text/html'}))
    updated = get_carsi_catalog(upgrade, refresh=True, transport=transport)
    assert updated.resources[0].searchStr == first['searchStr']
    assert updated.resources[0].wayfless_url_template == catalog.resources[0].wayfless_url_template
    assert updated.resources[1].wayfless_url_template is None
    assert any(row.unavailable_reason for row in updated.resources)
    assert get_carsi_catalog(upgrade).resources == updated.resources
    raw = read_snapshot(upgrade, CATALOG_KEY).payload
    assert any(row['entry_sources'] for row in raw['retired_resources'])


def test_selected_templates_preserve_fixed_bytes_and_apply_only_required_parameters(tmp_path):
    from allfold.application.carsi_entry import service_entry
    from allfold.config import AccessService, InstitutionConfig

    catalog = get_carsi_catalog(tmp_path / 'resources.sqlite')
    rows = {row.production: row for row in catalog.resources}
    def entry(name, **params):
        row = rows[name]
        return service_entry(tmp_path / 'config.yaml',
            AccessService.create(name, row.access_url), InstitutionConfig(**params), catalog=catalog)
    gale = next(name for name in rows if rows[name].wayfless_url_template
                and '{gale_location_id}' in rows[name].wayfless_url_template)
    assert entry(gale)['wayfless_url'] is None
    assert entry(gale, gale_location_id='A/B +中')['wayfless_url'] == (
        'https://link.gale.com/apps/menu?u=A%2FB%20%2B%E4%B8%AD')
    tenant = next(name for name in rows if rows[name].wayfless_url_template
                  and '{product_tenant_id}' in rows[name].wayfless_url_template)
    idp = 'https://idp.example/idp/shibboleth'
    assert entry(tenant, idp_entity_id=idp)['wayfless_url'] is None
    assert 'A%252FB%2520%252B' in entry(tenant, idp_entity_id=idp, product_tenant_id='A/B +')['wayfless_url']
    longyuan = next(name for name in rows if rows[name].wayfless_url_template
                   and '{institution_resource_url}' in rows[name].wayfless_url_template)
    assert entry(longyuan, idp_entity_id=idp)['wayfless_url'] is None
    assert 'state=https%3A%2F%2Fread.example%2Fpart%252Fkeep%3Fstate%3Dx' in entry(
        longyuan, idp_entity_id=idp, institution_resource_url='https://read.example/part%2Fkeep?state=x')['wayfless_url']
    assert entry('Statista', idp_entity_id='https://idp.example/中')['wayfless_url'] == (
        'https://shibboleth.statista.com/Shibboleth.sso/Login?entityID=https%3A%2F%2Fidp.example%2F%E4%B8%AD'
        '&target=https%3A%2F%2Fshibboleth.statista.com%2Findex.php%3Fidp%3DaHR0cHM6Ly9pZHAuZXhhbXBsZS%252FkuK0%253D')
    for source in ('brillonline.nl/Shibboleth.sso/', 'karger.com/ExternalAuthentication/'):
        name = next(name for name, row in rows.items() if source in (row.entry_note or ''))
        assert entry(name, idp_entity_id=idp)['wayfless_url'] is None
        assert 'https://' in rows[name].entry_note


def test_refresh_keeps_conflicting_catalog_identity_evidence_without_using_it(tmp_path):
    path = tmp_path / 'resources.sqlite'
    original = read_snapshot(path, CATALOG_KEY)
    assert original is None
    row = asdict(next(row for row in get_carsi_catalog(path).resources if row.wayfless_url_template))
    changed = {key: row[key] for key in ('production', 'url', 'sptype')} | {'searchStr': 'Different vendor and product'}
    write_snapshot(path, CATALOG_KEY, {'resources': [changed]})
    assert get_carsi_catalog(path).resources[0].wayfless_url_template is None
    html = '<script>var SPList=' + json.dumps([changed]) + ';</script>'
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={'content-type': 'text/html'}))
    refreshed = get_carsi_catalog(path, refresh=True, transport=transport)
    assert refreshed.resources[0].wayfless_url_template is None
    assert any(item['production'] == row['production'] and item['entry_sources'] == list(row['entry_sources'])
               for item in read_snapshot(path, CATALOG_KEY).payload['retired_resources'])
