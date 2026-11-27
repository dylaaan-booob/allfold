"""Convert the reviewed CARSI Markdown handoff to the shipped catalog seed."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def convert(document: str) -> list[dict]:
    sections = document.split('\n## 7. ', 1)[1].split('\n## 8. ', 1)
    data = json.loads(sections[0].split('```json\n', 1)[1].split('\n```', 1)[0])
    urls = dict(re.findall(r'^- \*\*(S\d+)\*\*：<(https?://[^>]+)>$', sections[1], re.M))
    if Counter(entry['default_route'] for entry in data['services']) != {
        'wayfless': 180, 'portal': 181, 'unavailable': 1,
    }:
        raise ValueError('Unexpected CARSI handoff counts')
    rows = []
    for entry in data['services']:
        source = entry['source_service']
        default = entry['wayfless_rule']
        conditional = entry.get('conditional_wayfless_rule')
        rule = default or conditional or {}
        note = [entry.get('reason'), entry.get('evidence_gap'), rule.get('scope'), *rule.get('conditions', ())]
        if conditional:
            note.append(conditional['url_template'])
        row = {field: source[field] for field in ('production', 'searchStr', 'url')}
        rows.append({
            **row, 'sptype': str(source['sptype']),
            'wayfless_url_template': default['url_template'] if default else None,
            'unavailable_reason': entry['reason'] if entry['default_route'] == 'unavailable' else None,
            'entry_sources': list(dict.fromkeys(urls[ref] for ref in rule.get('source_refs', entry.get('source_refs', ())))),
            'entry_note': '\n'.join(part for part in note if part) or None,
        })
    if len({row['production'] for row in rows}) != len(rows) or any(not row['entry_sources'] for row in rows):
        raise ValueError('Unexpected CARSI identity or missing sources')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('handoff', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    rows = convert(args.handoff.read_text(encoding='utf-8'))
    args.destination.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
