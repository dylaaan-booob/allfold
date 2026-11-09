const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function render(paper) {
  const createElement = tagName => ({
    tagName, children: [],
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  });
  const context = {window: {}, URL, document: {createElement}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../frontend/ui/paper-dates.js'), 'utf8'), context);
  const fields = ['first-public', 'received', 'accepted', 'published'].map(dateKind => ({dataset: {dateKind}}));
  const summary = {querySelectorAll: () => fields};
  const evidence = createElement('ol');
  context.window.allfoldPaperDates.render(paper, summary, evidence);
  return {dates: fields.map(field => field.textContent), evidence: evidence.children};
}

function journal(kind, provider, parts, extra = {}) {
  const [year, month, day] = parts;
  return {kind, provider, record_id: 'record-' + provider, publication_type: 'journal', year, month, day, ...extra};
}

test('four Reader dates use earliest sourced formal events and keep the verified First public', () => {
  const {dates} = render({first_public_at: '2020-03', publication_date: '2027', date_evidence: [
    journal('published', 'crossref', [2027], {source_label: 'published-print'}),
    journal('published-online', 'wos', [2026, 9], {source_label: 'EA'}),
    journal('accepted', 'pubmed', [2026, 8]),
    journal('received', 'crossref', [2026, 7]),
    journal('accepted', 'translator-web', [2026, 5, 9]),
    journal('received', 'pubmed', [2026, 6, 30]),
  ]});
  assert.deepEqual(dates, ['2020-03', '2026-06-30', '2026-05-09', '2026-09']);
});

test('only bound, explicitly typed formal journal facts support journal dates', () => {
  const {dates} = render({publication_type: 'journal', publication_date: '2026-01', date_evidence: [
    journal('source-date', 'crossref', [2024, 7], {source_label: 'created'}),
    journal('published', 'crossref', [2024, 9], {publication_type: 'conference'}),
    journal('published-online', 'arxiv', [2022, 8], {publication_type: 'preprint'}),
    journal('accepted', 'pubmed', [2022, 8], {publication_type: 'preprint'}),
    journal('preprint', 'biorxiv', [2022, 8], {publication_type: 'preprint', first_version: true}),
    journal('received', 'pubmed', [2025, 2], {record_id: null}),
    journal('accepted', null, [2025, 1]),
  ]});
  assert.deepEqual(dates, ['', '', '', '']);
});

test('overlapping dates preserve the coarser precision and disjoint intervals preserve the earlier date', () => {
  const events = [
    journal('published', 'pubmed', [2026, 3, 13]),
    journal('published-online', 'crossref', [2026, 3]),
    journal('published', 'wos', [2026, 4, 1]),
    journal('received', 'crossref', [2025, 12, 31]),
    journal('received', 'pubmed', [2026]),
    journal('accepted', 'crossref', [2026, 1, 1]),
    journal('accepted', 'pubmed', [2026]),
  ];
  for (const date_evidence of [events, [...events].reverse()]) {
    assert.deepEqual(render({date_evidence}).dates, ['', '2025-12-31', '2026', '2026-03']);
  }
});

test('Info retains each raw event in date order and links only safe source URLs', () => {
  const sameDate = journal('published', 'crossref', [2026, 3], {
    record_id: '10.5555/formal', source_label: 'published-print', url: 'https://doi.org/10.5555/formal',
  });
  const date_evidence = Object.freeze([
    Object.freeze(sameDate),
    Object.freeze({...sameDate, source_label: 'issued', url: 'javascript:alert(1)'}),
    Object.freeze(journal('published-online', 'wos', [2026, 3], {source_label: 'EA', url: '//example.test/formal'})),
    Object.freeze(journal('source-date', 'crossref', [2025, 3, 1], {source_label: 'indexed', url: 'https://user:secret@example.test'})),
    Object.freeze({
      kind: 'preprint', year: 2022, month: 4, provider: 'arxiv', record_id: '2204.12345',
      publication_type: 'preprint', version: 'v1', version_family: 'arxiv:2204.12345', first_version: true,
      source_label: 'published', url: 'https://arxiv.org/abs/2204.12345',
    }),
  ]);
  const {evidence} = render({date_evidence});
  assert.deepEqual(Array.from(evidence, row => row.children[0].textContent), [
    '2022-04 · preprint', '2025-03-01 · source-date', '2026-03 · published', '2026-03 · published', '2026-03 · published-online',
  ]);
  assert.match(evidence[0].children[1].textContent, /arxiv · 2204\.12345 · published · Version v1 · Family arxiv:2204\.12345 · First version: true/);
  assert.match(evidence[1].children[1].textContent, /indexed/);
  assert.match(evidence[2].children[1].textContent, /crossref · 10\.5555\/formal · published-print/);
  assert.match(evidence[3].children[1].textContent, /issued/);
  assert.match(evidence[4].children[1].textContent, /wos · record-wos · EA/);
  const links = Array.from(evidence).flatMap(row => row.children.filter(item => item.tagName === 'a'));
  assert.deepEqual(links.map(link => link.href), ['https://arxiv.org/abs/2204.12345', 'https://doi.org/10.5555/formal']);
  assert.ok(links.every(link => link.target === '_blank' && link.rel === 'noopener noreferrer'));
});
