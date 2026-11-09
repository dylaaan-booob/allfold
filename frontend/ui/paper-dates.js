(() => {
  const formalKinds = new Map([
    ['received', 'received'],
    ['accepted', 'accepted'],
    ['published', 'published'],
    ['published-online', 'published'],
  ]);

  function dateValue({year, month, day}) {
    return String(year).padStart(4, '0')
      + (month == null ? '' : '-' + String(month).padStart(2, '0'))
      + (day == null ? '' : '-' + String(day).padStart(2, '0'));
  }

  function sourceURL(value) {
    if (!/^https?:\/\//i.test(value) || /[\s\\\x00-\x1f\x7f]/.test(value)) return null;
    try {
      const url = new URL(value);
      return url.username || url.password ? null : url;
    } catch {
      return null;
    }
  }

  function evidenceRow({item, date}) {
    const row = document.createElement('li');
    const event = document.createElement('span');
    event.textContent = [date, item.kind].join(' · ');
    row.append(event);
    const fields = [item.provider, item.record_id, item.source_label,
      item.version && 'Version ' + item.version,
      item.version_family && 'Family ' + item.version_family,
      item.publication_type === 'preprint' && typeof item.first_version === 'boolean'
        && 'First version: ' + item.first_version,
      item.publication_type].filter(Boolean);
    if (fields.length) {
      const details = document.createElement('span');
      details.textContent = fields.join(' · ');
      row.append(details);
    }
    const url = sourceURL(item.url);
    if (url) {
      const link = document.createElement('a');
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = item.url;
      row.append(link);
    }
    return row;
  }

  window.allfoldPaperDates = {
    render(paper, summary, evidenceList) {
      // ISO dates of these precisions are either disjoint or nested. String
      // order puts the earlier disjoint interval or the enclosing interval first.
      const evidence = (paper?.date_evidence || []).map(item => ({item, date: dateValue(item)}))
        .sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0);
      const dates = new Map([['first-public', paper?.first_public_at || '']]);
      for (const {item, date} of evidence) {
        const kind = formalKinds.get(item.kind);
        if (kind && item.publication_type === 'journal' && item.provider && item.record_id && !dates.has(kind)) {
          dates.set(kind, date);
        }
      }
      for (const field of summary.querySelectorAll('[data-date-kind]')) {
        field.textContent = dates.get(field.dataset.dateKind) || '';
      }
      evidenceList.replaceChildren(...evidence.map(evidenceRow));
    },
  };
})();
