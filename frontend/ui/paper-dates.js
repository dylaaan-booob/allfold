(() => {
  const names={'accepted':'Accepted','published-online':'Published online','published-print':'Published print',published:'Published',issued:'Issued','source-date':'来源日期','early-access':'Early access'};
  const value=item=>[item.year,item.month,item.day].filter(part=>part!==undefined && part!==null).map((part,i)=>i?String(part).padStart(2,'0'):String(part).padStart(4,'0')).join('-');
  const detail=item=>[item.provider,item.record_id,item.version,item.url].filter(Boolean).join(' · ');
  window.allfoldPaperDates={render(paper,first,journal){
    const evidence=paper.date_evidence || [];
    first.textContent=paper.first_public_at || '—';
    first.title=evidence.filter(item=>item.kind==='preprint' && item.first_version && value(item)===paper.first_public_at).map(detail).join('\n');
    const events=evidence.filter(item=>item.publication_type==='journal' && item.kind!=='preprint').sort((a,b)=>{
      const key=item=>[item.year,item.month || 1,item.day || 1].map((part,i)=>String(part).padStart(i?2:4,'0')).join('-');
      return key(a).localeCompare(key(b)) || detail(a).localeCompare(detail(b));
    });
    journal.replaceChildren(...events.map(item=>{
      const line=document.createElement('div');
      line.textContent=`${names[item.kind] || '来源日期'} · ${value(item)} · ${item.provider || ''}`;
      line.title=detail(item);return line;
    }));
    if(!events.length)journal.textContent='—';
  }};
})();
