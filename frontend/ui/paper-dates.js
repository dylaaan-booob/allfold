'use strict';
(() => {
  function sourceURL(value) {
    if(typeof value!=='string' || !/^https?:\/\//i.test(value) || /[\s\\\x00-\x1f\x7f]/.test(value))return null;
    try {const url=new URL(value);return url.username || url.password?null:url;}catch{return null;}
  }
  function proofRow(item) {
    const row=document.createElement('li'),description=document.createElement('span');
    const date=item.date || (item.year?String(item.year).padStart(4,'0')+(item.month?'-'+String(item.month).padStart(2,'0'):'')+(item.day?'-'+String(item.day).padStart(2,'0'):''):null);
    description.textContent=[date,item.provider,item.identifier || item.record_id,
      item.version && 'Version '+item.version,item.version_family && 'Family '+item.version_family,
      typeof item.first_version==='boolean' && 'First version: '+item.first_version].filter(Boolean).join(' · ');
    row.append(description);
    const url=sourceURL(item.url);
    if(url){const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent=item.url;row.append(link);}
    return row;
  }
  window.allfoldPaperDates={
    render(paper,summary,preprintList) {
      const dates=[...new Set(paper?.ordinary_dates || [])].sort();
      for(const field of summary.querySelectorAll('[data-date-set]'))
        field.textContent=(field.dataset.dateSet==='ordinary'?dates.join(' · '):paper?.first_public_at) || '—';
      const facts=[...(paper?.preprints || []),...(paper?.preprint_evidence || [])];
      const unique=new Map(facts.map(item=>[JSON.stringify(item),item]));
      preprintList.replaceChildren(...[...unique.values()].map(proofRow));
    },
  };
})();
