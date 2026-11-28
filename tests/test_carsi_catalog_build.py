import csv
from pathlib import Path
import subprocess
import sys


def test_build_loads_reviewed_products_and_the_process_reuses_them(tmp_path):
    source, database = tmp_path / 'reviewed.csv', tmp_path / 'catalog.sqlite'
    fields = ('production', 'searchStr', 'url', 'sptype', 'wayfless_url_template',
              'unavailable_reason', 'entry_sources', 'entry_note')
    with source.open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(fields)
        writer.writerow(('Journal Platform', 'JOURNALS', 'https://journals.example/ ', '2',
            'https://journals.example/login?entity={idp_entity_id}', '',
            'https://carsi.example/catalog\nhttps://journals.example/help', 'Requires federation membership'))
        writer.writerow(('Stopped', 'STOPPED', 'www.stopped.example', '1', '',
            'Service closed', 'https://stopped.example/notice', ''))
    builder = Path(__file__).resolve().parents[1] / 'tools/build_carsi_catalog.py'
    subprocess.run([sys.executable, str(builder), str(source), '--output', str(database)], check=True)

    # Start a fresh process so no other fixture can have loaded the catalog.
    subprocess.run([sys.executable, '-c', """
from pathlib import Path
import sys
from allfold.application import carsi_catalog

carsi_catalog.CATALOG_PATH = Path(sys.argv[1])
catalog = carsi_catalog.get_carsi_catalog()
assert set(catalog) == {'Journal Platform', 'Stopped'}
assert catalog['Journal Platform'].url == 'https://journals.example/ '
assert catalog['Journal Platform'].sptype == '2'
assert catalog['Journal Platform'].wayfless_url_template == 'https://journals.example/login?entity={idp_entity_id}'
assert catalog['Journal Platform'].entry_sources == ('https://carsi.example/catalog', 'https://journals.example/help')
assert catalog['Journal Platform'].entry_note == 'Requires federation membership'
assert catalog['Stopped'].unavailable_reason == 'Service closed'
assert catalog['Stopped'].access_url is None
carsi_catalog.CATALOG_PATH.unlink()
assert carsi_catalog.validate_carsi_service('Journal Platform') is catalog['Journal Platform']
assert carsi_catalog.get_carsi_catalog() is catalog
assert not carsi_catalog.CATALOG_PATH.exists()
""", str(database)], check=True)
